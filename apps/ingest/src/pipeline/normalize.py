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
    return JobObservation(
        url=row.get("url", ""),
        source=row.get("source", "raw"),
        raw_markdown=markdown,
        title=row.get("title", ""),
        snippet=row.get("snippet", ""),
        extra={},
    )


async def normalize_one(ctx: Any, url_hash: str) -> str | None:
    """Gate one observation row. Returns canonical_id when accepted."""
    await ctx.known.refresh(ctx.store)
    rows = await ctx.store.fetch_observation_rows([url_hash])
    if not rows:
        return None
    obs = _obs_from_row(rows[0])
    if not obs.raw_markdown or len(obs.raw_markdown) < 100:
        return None
    pid = posting_id(obs)
    obs.observed_at = time.time()

    candidate, rejections = await run_gates(obs, ctx.known.hashes, ctx.known.last_seen)
    if candidate is None:
        await persist_rejected(ctx.store, obs, pid, rejections)
        return None

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
    return candidate.canonical_id


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
        canonical_id = await normalize_one(ctx, url_hash)
    except Exception as exc:
        logger.warning(f"Normalize failed for {url_hash}: {exc}")
        return
    if canonical_id is None:
        return
    await ctx.bus.publish("ho:s:gated", model.gated_fields(canonical_id))
    await ctx.bus.publish("ho:s:embed", model.embed_fields(url_hash))
