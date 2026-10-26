"""Enrich stage: company -> founders + funding, cached and graphed.

Evidence comes from TinyFish web search snippets (free budget shared with
discovery) parsed deterministically — no LLM guessing, no hallucinated
people. Results cache in company_osint (7d TTL) and land on the candidate
row plus Neo4j (FOUNDED_BY / HAS_FUNDING edges), so rels grow again.
"""

from __future__ import annotations

import contextlib
import os
import re
from typing import Any

from src.logging import get_logger

logger = get_logger("pipeline_enrich")

ENRICH_TTL_S = 7 * 86400
ENRICH_DAILY_CAP = 500

_FOUNDED_RX = [
    re.compile(
        r"founded by ([A-Z][a-zA-Z'’.-]+(?: [A-Z][a-zA-Z'’.-]+){0,2}"
        r"(?:,? and [A-Z][a-zA-Z'’.-]+(?: [A-Z][a-zA-Z'’.-]+){0,2})?)"
    ),
    re.compile(r"co-?founders? ([A-Z][a-zA-Z'’.-]+(?: [A-Z][a-zA-Z'’.-]+){0,2})"),
    re.compile(r"founder ([A-Z][a-zA-Z'’.-]+(?: [A-Z][a-zA-Z'’.-]+){0,2})"),
]
_FUNDING_RX = [
    (re.compile(r"raised \$([\d.,]+)\s*([BMK])", re.IGNORECASE), "amount"),
    (re.compile(r"Series ([A-F])\b"), "series"),
    (re.compile(r"(?<!pre-)\bseed (?:round|funding|investment)\b", re.IGNORECASE), "seed"),
    (re.compile(r"\bpre-seed\b", re.IGNORECASE), "pre-seed"),
    (re.compile(r"valued at \$([\d.,]+)\s*([BMK])", re.IGNORECASE), "valuation"),
]
_STOP_NAMES = {
    "The Company",
    "The Team",
    "Read More",
    "Learn More",
    "About Us",
    "Contact Us",
    "All Rights",
}


def parse_founders(snippets: list[str]) -> list[str]:
    """Founder names from evidence text (capitalized-name patterns only)."""
    found: list[str] = []
    for text in snippets:
        for rx in _FOUNDED_RX:
            for match in rx.finditer(text):
                chunk = match.group(1).strip().rstrip(".,;:")
                for name in re.split(r",?\s+and\s+|,\s*", chunk):
                    name = " ".join(w for w in name.strip().split() if w)
                    if (
                        len(name.split()) in (2, 3)
                        and name not in found
                        and name not in _STOP_NAMES
                        and len(name) < 40
                    ):
                        found.append(name)
    return found[:5]


def parse_funding(snippets: list[str]) -> dict[str, str]:
    """Funding signals from evidence text (amounts/rounds, verbatim)."""
    out: dict[str, str] = {}
    for text in snippets:
        for rx, kind in _FUNDING_RX:
            match = rx.search(text)
            if not match:
                continue
            if kind == "amount" and "amount" not in out:
                out["amount"] = f"${match.group(1)}{match.group(2).upper()}"
            elif kind == "series" and "stage" not in out:
                out["stage"] = f"Series {match.group(1).upper()}"
            elif kind in ("seed", "pre-seed") and "stage" not in out:
                out["stage"] = "Seed" if kind == "seed" else "Pre-seed"
            elif kind == "valuation" and "valuation" not in out:
                out["valuation"] = f"${match.group(1)}{match.group(2).upper()}"
    return out


def _day_key() -> str:
    import time

    return time.strftime("ho:budget:tfenrich:%Y%m%d", time.gmtime())


async def _budget_ok(redis: Any, cap: int = ENRICH_DAILY_CAP) -> bool:
    try:
        used = await redis.incr(_day_key())
        if used == 1:
            await redis.expire(_day_key(), 172800)
        return used <= cap
    except Exception:
        return True


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")[:60]


async def is_company_fresh(ctx: Any, company: str) -> bool:
    """False when this company was enriched recently (skip re-queue)."""
    try:
        seen = await ctx.bus.redis.get(f"ho:enriched:{_slug(company)}")
        return not seen
    except Exception:
        return True


async def enrich_company(ctx: Any, company: str) -> dict[str, Any] | None:
    """Enrich one company (cached). Returns {founders, funding} or None."""
    name = (company or "").strip()
    if not name or name.lower() in ("unknown", "n/a", ""):
        return None
    slug = _slug(name)
    try:
        seen = await ctx.bus.redis.get(f"ho:enriched:{slug}")
        if seen:
            return None
    except Exception:
        pass
    try:
        cached = await ctx.store.get_company_osint(name)
        if cached:
            return cached
    except Exception:
        pass
    if not await _budget_ok(ctx.bus.redis):
        return None
    api_key = os.environ.get("TINY_FISH_API_KEY", "").strip()
    if not api_key:
        return None
    snippets: list[str] = []
    try:
        import httpx

        from src.radar.sources.tinyfish_search import search_page

        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for query in (f"{name} founders", f"{name} funding raised series"):
                if not await _budget_ok(ctx.bus.redis):
                    break
                for item in await search_page(client, api_key, query):
                    snippets.append(f"{item.get('title', '')} {item.get('snippet', '')}")
    except Exception as exc:
        logger.debug(f"Enrich search failed for {name}: {exc}")
        return None
    founders = parse_founders(snippets)
    funding = parse_funding(snippets)
    if not founders and not funding:
        return None
    data = {"founders": founders, "funding": funding, "snippets": len(snippets)}
    with contextlib.suppress(Exception):
        await ctx.store.put_company_osint(name, data)
    with contextlib.suppress(Exception):
        await ctx.bus.redis.set(f"ho:enriched:{slug}", "1", ex=ENRICH_TTL_S)
    return data


async def apply_enrichment(ctx: Any, canonical_id: str, data: dict[str, Any]) -> None:
    """Write founders/funding onto the candidate row + Neo4j graph."""
    founders = data.get("founders") or []
    funding = data.get("funding") or {}
    try:
        async with ctx.store._pool.acquire() as conn:
            await conn.execute(
                """UPDATE radar_candidates
                   SET founders = $2::jsonb,
                       funding_stage = COALESCE(NULLIF($3, ''), funding_stage),
                       funding_info = radar_candidates.funding_info || $4::jsonb,
                       updated_at = NOW()
                   WHERE canonical_id = $1""",
                canonical_id,
                founders,
                funding.get("stage", ""),
                funding,
            )
    except Exception:
        pass
    if ctx.graph is None:
        return
    try:
        from src.graph.entity import EdgeType, GraphNode, NodeType, make_company_id, make_founder_id
        from src.graph.entity import company_node as _cn
        from src.graph.entity import edge as _edge

        company = ""
        try:
            async with ctx.store._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT normalized_company FROM radar_candidates WHERE canonical_id = $1",
                    canonical_id,
                )
                company = (row["normalized_company"] if row else "") or ""
        except Exception:
            return
        if not company:
            return
        comp_id = make_company_id(company)
        node = await ctx.graph.get_node(comp_id)
        if node is None:
            node, _ = await ctx.graph.upsert_node(_cn(company, source="enrich"))
        for fname in founders:
            try:
                fid = make_founder_id(fname, company)
                fnode = await ctx.graph.get_node(fid)
                if fnode is None:
                    fnode, _ = await ctx.graph.upsert_node(
                        GraphNode(id=fid, node_type=NodeType.FOUNDER, data={"name": fname})
                    )
                await ctx.graph.upsert_edge(_edge(comp_id, EdgeType.FOUNDED_BY, fid))
            except Exception:
                continue
        if funding.get("stage") or funding.get("amount"):
            with contextlib.suppress(Exception):
                await ctx.graph.upsert_edge(
                    _edge(
                        comp_id,
                        EdgeType.HAS_FUNDING,
                        comp_id,
                        stage=funding.get("stage", ""),
                        amount=funding.get("amount", ""),
                    )
                )
    except Exception as exc:
        logger.debug(f"Graph enrich failed: {exc}")


async def handle_enrich(ctx: Any, fields: dict[str, str]) -> None:
    """Consume one enrich message: company -> evidence -> row + graph."""
    company = (fields.get("company") or "").strip()
    canonical_id = (fields.get("canonical_id") or "").strip()
    if not company or not canonical_id:
        return
    try:
        data = await enrich_company(ctx, company)
    except Exception as exc:
        logger.warning(f"Enrich failed for {company}: {exc}")
        return
    if not data:
        return
    await apply_enrichment(ctx, canonical_id, data)
