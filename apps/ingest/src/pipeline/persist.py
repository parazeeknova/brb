"""Corpus persistence helpers: observations + candidates into Postgres.

Moved verbatim from the retired sweep orchestrator; the only behavioral
change is markdown archival: scraped page text is merged into
job_observations.raw_json (capped) so the corpus keeps JD bodies instead
of dropping them after gating.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from src.logging import get_logger
from src.memory.pgvector_store import MemoryStore
from src.radar.core.models import JobCandidate, JobObservation

logger = get_logger("pipeline_persist")

MARKDOWN_ARCHIVE_CHARS = 20000


def posting_id(obs: JobObservation) -> str:
    return obs.canonical_url_hash()


async def persist_observation(store: MemoryStore, obs: JobObservation, pid: str) -> None:
    try:
        async with store._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO job_observations (url_hash, url, source, title, snippet,
                    first_seen, last_seen, freshness_lane, direct_posting_verified,
                    verified, verification_method)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (url_hash) DO UPDATE SET last_seen = EXCLUDED.last_seen""",
                pid,
                obs.url,
                obs.source,
                obs.title or "",
                obs.snippet or "",
                obs.observed_at,
                obs.observed_at,
                "review",
                not obs.source.startswith("github_index:"),
                obs.verified,
                obs.verification_method or "",
            )
    except Exception:
        pass


async def save_content(
    store: MemoryStore, url_hash: str, markdown: str, company_slug: str = ""
) -> None:
    """Archive scraped content + ATS slug into raw_json.

    The normalize stage rehydrates from the DB row, so anything it needs
    (page text, verified company slug) must be archived here.
    """
    text = (markdown or "").strip()
    if not text and not company_slug:
        return
    try:
        # Dict, not pre-serialized JSON: asyncpg encodes jsonb params itself;
        # a str would double-encode into a scalar and corrupt the merge.
        payload: dict[str, Any] = {}
        if text:
            payload["markdown"] = text[:MARKDOWN_ARCHIVE_CHARS]
        if company_slug:
            payload["company_slug"] = company_slug
        async with store._pool.acquire() as conn:
            await conn.execute(
                """UPDATE job_observations
                   SET raw_json = COALESCE(raw_json, '{}'::jsonb) || $2::jsonb
                   WHERE url_hash = $1""",
                url_hash,
                payload,
            )
    except Exception:
        pass


async def persist_rejected(
    store: MemoryStore,
    obs: JobObservation,
    pid: str,
    rejections: list[tuple[str, Any, str]],
) -> None:
    try:
        reason = rejections[0][1] if rejections else None
        detail = rejections[0][2] if rejections else ""
        reason_str = reason.value if reason else "unknown"
        async with store._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO radar_candidates (canonical_id, source, direct_apply_url,
                    normalized_company, eligibility, rejection_reason, rejection_detail,
                    freshness_lane, first_seen, last_seen, role_family)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9,'unknown')
                ON CONFLICT (canonical_id) DO NOTHING""",
                f"rejected:{pid}",
                obs.source,
                obs.url,
                obs.title or "unknown",
                "rejected",
                reason_str,
                detail[:200],
                "review",
                obs.observed_at,
            )
    except Exception:
        pass


async def persist_candidate(store: MemoryStore, c: JobCandidate, verified: bool = True) -> None:
    try:
        data: dict[str, Any] = {
            "canonical_id": c.canonical_id,
            "source": c.source,
            "direct_apply_url": c.direct_apply_url,
            "normalized_company": c.normalized_company,
            "normalized_role": c.normalized_role,
            "normalized_location": c.normalized_location,
            "freshness_lane": c.freshness_lane.name.lower(),
            "source_confidence": c.source_confidence,
            "eligibility": c.eligibility.name.lower(),
            "rejection_reason": c.rejection_reason.value if c.rejection_reason else "",
            "role_family": c.role_family.value,
            "salary_amount": c.salary.amount if c.salary else None,
            "salary_currency": c.salary.currency if c.salary else "",
            "salary_period": c.salary.period if c.salary else "",
            "salary_raw": c.salary.raw if c.salary else "",
            "posted_date": c.posted_date or "",
            "first_seen": c.first_seen,
            "last_seen": c.last_seen,
            "matching_skills": c.matching_skills,
            "missing_skills": c.missing_skills,
            "match_percent": c.match_percent,
            "shortlist_probability": c.shortlist_probability,
            "verdict": c.verdict,
            "jd_summary": c.jd_summary,
            "company_description": c.company_description,
            "role_summary": c.role_summary,
            "is_remote": c.is_remote,
            "founders": c.founders,
            "funding_stage": c.funding_stage,
            "funding_info": c.funding_info,
            "founder_socials": c.founder_socials,
            "company_news": c.company_news,
            "osint_signals": c.osint_signals,
            "extra": c.extra,
            "verified": verified,
        }
        await store.upsert_radar_candidate(data)
    except Exception:
        pass


async def record_ats_evidence(
    store: MemoryStore | None, board_url: str, obs: list[JobObservation]
) -> None:
    """Openings seen on an official ATS board -> hiring evidence."""
    if store is None or not obs:
        return
    try:
        from src.graph.entity import make_company_id
        from src.radar.sources.ats_interceptor import parse_ats_slug

        parsed = parse_ats_slug(board_url)
        company = parsed[1] if parsed else ""
        if not company:
            return
        await store.record_evidence(
            make_company_id(company),
            claim="ats_openings",
            source="ats_interceptor",
            company_name=company,
            evidence_type="hiring",
            weight=0.4,
            ref_url=board_url,
        )
    except Exception:
        pass


async def record_ats_no_openings(store: MemoryStore, board_url: str) -> None:
    """An official ATS board that previously had jobs now shows none."""
    try:
        from src.graph.entity import make_company_id
        from src.radar.sources.ats_interceptor import parse_ats_slug

        parsed = parse_ats_slug(board_url)
        company = parsed[1] if parsed else ""
        if not company:
            return
        await store.record_evidence(
            make_company_id(company),
            claim="no_openings",
            source="ats_interceptor",
            company_name=company,
            evidence_type="hiring",
            weight=0.4,
            contradicts=True,
            ref_url=board_url,
        )
    except Exception:
        pass


def now_ts() -> float:
    return time.time()


async def persist_structured(ctx: Any, observations: Sequence[JobObservation | None]) -> int:
    """Persist verified/structured obs directly + publish raw (no re-render).

    Shared by board polls (ATS interceptor/workday) and free JSON APIs.
    Dedups persistently first; infers verified flags from extras.
    """
    items = [o for o in observations if o is not None]
    if not items:
        return 0
    try:
        urls = [o.url for o in items if o.url.startswith("http")]
        fresh_urls = set(await ctx.dedup.filter_new_urls(urls))
        await ctx.dedup.mark_urls_seen(list(fresh_urls))
        items = [o for o in items if o.url in fresh_urls]
    except Exception:
        pass
    published = 0
    for obs in items:
        try:
            if obs.extra.get("verified") is True or obs.extra.get("official_source"):
                obs.verified = True
                obs.verification_method = obs.extra.get("verification_method", "ats_board")
            obs.observed_at = now_ts()
            pid = posting_id(obs)
            await persist_observation(ctx.store, obs, pid)
            await save_content(
                ctx.store, pid, obs.raw_markdown, str(obs.extra.get("company_slug", ""))
            )
            await ctx.bus.publish(
                "ho:s:raw",
                {"url_hash": pid, "url": obs.url, "source": obs.source},
            )
            published += 1
        except Exception:
            continue
    return published
