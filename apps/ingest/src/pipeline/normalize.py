"""Normalize stage: raw stream -> gates -> candidates -> graph + streams.

Deterministic only: gates, signal extraction, underdog/rank scoring,
candidate upserts, Neo4j company upserts. No LLM anywhere on this path
(per-candidate LLM matching moved to the web app with Clef).
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from src.logging import get_logger
from src.pipeline import model
from src.pipeline.persist import (
    persist_candidate,
    persist_observation,
    persist_rejected,
    posting_id,
)
from src.radar.core.gates import run_gates
from src.radar.core.models import JobCandidate, JobObservation
from src.radar.core.scoring import compute_underdog_score, rank_score
from src.radar.core.signals import extract_signals

logger = get_logger("pipeline_normalize")

SUBQ_VERIFY_THRESHOLD = 0.7


async def verify_posting(ctx: Any, obs: JobObservation) -> bool:
    """SubQ real-posting judgment for non-ATS pages (fail-open when offline).

    Deterministic pre-checks first (title + company + substance) so obvious
    junk never spends model budget. Returns True when verified.
    """
    title = (obs.title or "").strip()
    if len(title) < 4 or len(obs.raw_markdown) < 400:
        return False
    try:
        from src.llm.subq import is_available, is_real_posting
    except Exception:
        return False
    if not is_available():
        return False
    company = ""
    try:
        from src.radar.core.gates import _extract_company

        company = _extract_company(obs)
    except Exception:
        pass
    try:
        prob = await is_real_posting(title, company, obs.raw_markdown)
    except Exception:
        return False
    return prob is not None and prob >= SUBQ_VERIFY_THRESHOLD


def _obs_from_row(row: dict[str, Any]) -> JobObservation:
    """Rehydrate an observation; archived markdown becomes gate input."""
    import json

    raw = row.get("raw_json")
    markdown = ""
    if isinstance(raw, str) and raw:
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if isinstance(raw, dict):
        md = raw.get("markdown")
        if isinstance(md, str):
            markdown = md
    extra: dict[str, Any] = {}
    if isinstance(raw, dict) and isinstance(raw.get("company_slug"), str):
        extra["company_slug"] = raw["company_slug"]
    return JobObservation(
        url=row.get("url", ""),
        source=row.get("source", "raw"),
        raw_markdown=markdown,
        title=row.get("title", ""),
        snippet=row.get("snippet", ""),
        extra=extra,
    )


async def normalize_one(ctx: Any, url_hash: str) -> tuple[str, str] | None:
    """Gate one observation row. Returns (canonical_id, company) when accepted."""
    await ctx.known.refresh(ctx.store)
    rows = await ctx.store.fetch_observation_rows([url_hash])
    if not rows:
        return None
    obs = _obs_from_row(rows[0])
    is_verified = bool(rows[0].get("verified"))
    # Thin pages die here — unless already verified by construction (ATS /
    # workday APIs carry title+location but not always full bodies).
    if (not obs.raw_markdown or len(obs.raw_markdown) < 100) and not is_verified:
        return None
    pid = posting_id(obs)
    obs.observed_at = time.time()

    # Anti-fake: ATS rows are verified at fetch; everything else must pass
    # the SubQ real-posting judgment before entering the corpus.
    if not is_verified:
        if not await verify_posting(ctx, obs):
            from src.radar.core.models import RejectionReason

            await persist_rejected(
                ctx.store, obs, pid, [("verify", RejectionReason.VERIFY_FAIL, "unverifiable")]
            )
            return None
        with contextlib.suppress(Exception):
            await ctx.store.set_observation_verified(pid, "subq")

    candidate, rejections = await run_gates(obs, ctx.known.hashes, ctx.known.last_seen)
    if candidate is None:
        await persist_rejected(ctx.store, obs, pid, rejections)
        return None

    # Gates are the only judges now (no per-candidate LLM): passing means
    # accepted into the corpus. Per-user fit is scored downstream (web/Clef).
    from src.radar.core.models import EligibilityState

    candidate.eligibility = EligibilityState.ACCEPTED
    candidate.verdict = "RULE_PASS"
    candidate.extra["raw_markdown"] = obs.raw_markdown
    candidate.extra["version"] = 1
    candidate.extra["posting_id"] = pid
    candidate.canonical_id = pid

    sigs = extract_signals(obs.raw_markdown, obs.title)
    if sigs["salary"]:
        candidate.salary = sigs["salary"]
        candidate.salary_annual_usd = sigs["salary_annual_usd"]
    candidate.sponsors_visa = sigs["sponsors_visa"]
    candidate.is_remote = sigs["is_remote"]
    candidate.underdog_score = compute_underdog_score(candidate)
    candidate.extra["rank_score"] = rank_score(candidate)

    await persist_observation(ctx.store, obs, pid)
    await persist_candidate(ctx.store, candidate)
    await graph_upsert_company(ctx, candidate)
    with contextlib.suppress(Exception):
        await ctx.store.record_pipeline_stage_event("gate_accept", 1)
    return candidate.canonical_id, candidate.normalized_company


async def graph_upsert_company(ctx: Any, candidate: JobCandidate) -> None:
    """Neo4j company intel (global, not per-user). Fail-soft."""
    if ctx.graph is None:
        return
    company = (candidate.normalized_company or "").lower().strip()
    if not company or company in ("unknown", "n/a", ""):
        return
    try:
        from src.graph.entity import company_node as _cn

        node = await ctx.graph.get_node(company)
        if node is None:
            node = _cn(company, source="pipeline")
            await ctx.graph.upsert_node(node)
    except Exception as exc:
        logger.debug(f"Graph company upsert failed for {company}: {exc}")


async def handle_raw(ctx: Any, fields: dict[str, str]) -> None:
    """Consume one raw message: normalize, forward to gated + embed streams."""
    url_hash = (fields.get("url_hash") or "").strip()
    if not url_hash:
        return
    try:
        accepted = await normalize_one(ctx, url_hash)
    except Exception as exc:
        logger.warning(f"Normalize failed for {url_hash}: {exc}")
        return
    if accepted is None:
        return
    canonical_id, company = accepted
    await ctx.bus.publish("ho:s:gated", model.gated_fields(canonical_id))
    await ctx.bus.publish("ho:s:embed", model.embed_fields(url_hash))
    try:
        from src.pipeline.enrich import is_company_fresh

        if (
            company
            and company.strip().lower() not in ("unknown", "n/a", "")
            and await is_company_fresh(ctx, company)
        ):
            await ctx.bus.publish("ho:s:enrich", model.enrich_fields(company, canonical_id))
    except Exception:
        pass
