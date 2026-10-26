"""Discover producers: every source adapter publishes URLs, continuously.

Each tick is interval-gated (state in Redis so N processes don't stampede
the same source) and publishes only persistently-new URLs. No barriers:
a slow source delays only its own tick.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import time
from typing import Any

from src.configuration import get_config
from src.logging import get_logger
from src.radar.core.models import JobObservation
from src.radar.sources.board_registry import REGISTERED_BOARDS

logger = get_logger("pipeline_producers")

HV_INTERVAL_S = float(os.environ.get("PRODUCER_HV_INTERVAL_S", "30"))
MASS_INTERVAL_S = float(os.environ.get("PRODUCER_MASS_INTERVAL_S", "120"))
INDEX_INTERVAL_S = float(os.environ.get("PRODUCER_INDEX_INTERVAL_S", "60"))
DORK_INTERVAL_S = float(os.environ.get("PRODUCER_DORK_INTERVAL_S", "60"))
BOARD_BATCH = int(os.environ.get("PRODUCER_BOARD_BATCH", "40"))
BOARD_SEM = int(os.environ.get("PRODUCER_BOARD_SEM", "24"))

_PLACEHOLDER_COMPANY_RX = re.compile(
    r"(?i)^(unknown|n/?a|tbd|to be (determined|announced)|confidential|"
    r"stealth|various|multiple|none|null|-+|\?+)$"
)
_HEADLINE_START_RX = re.compile(
    r"(?i)^(breaking|announces?|launches?|raises?|hiring|looking|seeking|wants?|joins?|partners?)\b"
)


def is_plausible_company_name(company: str) -> bool:
    """Heuristic: reject placeholders and headline-like discovery artifacts."""
    name = (company or "").strip()
    if not name or _PLACEHOLDER_COMPANY_RX.search(name):
        return False
    if len(name) > 45:
        return False
    if len(name.split()) >= 6:
        return False
    return not bool(_HEADLINE_START_RX.match(name))


def _hash_board_url(board_url: str) -> str:
    return hashlib.sha256(board_url.encode()).hexdigest()[:8]


_UNFETCHABLE_RX = [
    # Auth-walled or listing pages: never verifiable as postings, always burn
    # fetch budget. (Aggregator *boards* are still polled; these are dead-end
    # leaf URLs.)
    re.compile(r"^https?://(www\.)?linkedin\.com/jobs/", re.IGNORECASE),
    re.compile(r"^https?://(www\.)?indeed\.com/q-", re.IGNORECASE),
    re.compile(r"^https?://zapply\.jobs/", re.IGNORECASE),
]


def _is_unfetchable(url: str) -> bool:
    return any(rx.match(url) for rx in _UNFETCHABLE_RX)


async def due(redis: Any, key: str, interval_s: float) -> bool:
    """Cross-process interval guard: True at most once per interval."""
    now = time.time()
    try:
        last = await redis.get(f"ho:last:{key}")
        if last is not None and now - float(last) < interval_s:
            return False
        await redis.set(f"ho:last:{key}", now, ex=int(interval_s * 2) + 60)
        return True
    except Exception:
        return True


async def publish_urls(ctx: Any, urls: list[str], source: str) -> int:
    """Dedup persistently, publish survivors to the discover stream."""
    from src.pipeline.model import discover_fields, valid_url

    clean = [u.strip() for u in urls if u and valid_url(u.strip())]
    if not clean:
        return 0
    clean = [u for u in clean if not _is_unfetchable(u)]
    if not clean:
        return 0
    try:
        fresh = await ctx.dedup.filter_new_urls(clean)
    except Exception:
        fresh = clean
    if not fresh:
        return 0
    published_urls = []
    for url in fresh:
        try:
            await ctx.bus.publish("ho:s:discover", discover_fields(url, source))
            published_urls.append(url)
        except Exception:
            break
    if published_urls:
        with contextlib.suppress(Exception):
            await ctx.dedup.mark_urls_seen(published_urls)
    return len(published_urls)


async def high_volume_tick(ctx: Any) -> int:
    """4s-boxed parallel discovery (github + ATS mass + searxng + YC)."""
    if not await due(ctx.bus.redis, "hv", HV_INTERVAL_S):
        return 0
    try:
        from src.radar.sources.high_volume_discovery import HighVolumeDiscoveryEngine

        hv_urls = await HighVolumeDiscoveryEngine().discover_urls_parallel(duration_seconds=4.0)
    except Exception as exc:
        logger.warning(f"High-volume discovery failed: {exc}")
        return 0
    with contextlib.suppress(Exception):
        await ctx.store.record_pipeline_stage_event("url_discovery", len(hv_urls))
    return await publish_urls(ctx, hv_urls, "high_volume")


async def mass_poller_tick(ctx: Any) -> int:
    if not await due(ctx.bus.redis, "mass", MASS_INTERVAL_S):
        return 0
    try:
        from src.radar.sources.ats_mass_poller import poll_all_mass_slugs

        obs = await poll_all_mass_slugs()
    except Exception as exc:
        logger.debug(f"Mass ATS poller: {exc}")
        return 0
    return await publish_urls(ctx, [o.url for o in obs], "mass_poller")


async def github_tick(ctx: Any) -> int:
    if not await due(ctx.bus.redis, "github", INDEX_INTERVAL_S):
        return 0
    try:
        from src.radar.sources.github_poller import poll_all_github_indexes_etag

        obs = await poll_all_github_indexes_etag()
    except Exception as exc:
        logger.warning(f"GitHub index poller failed: {exc}")
        return 0
    return await publish_urls(ctx, [o.url for o in obs], "github_index")


async def dork_tick(ctx: Any, dork_engine: Any) -> int:
    """SearXNG dorks in a 20s box (internally serial per query)."""
    if not await due(ctx.bus.redis, "dork", DORK_INTERVAL_S):
        return 0
    try:
        timeout = float(os.environ.get("SEARXNG_DORK_TIMEOUT", "20"))
        obs = await asyncio.wait_for(dork_engine.execute_dorks(store=ctx.store), timeout=timeout)
    except TimeoutError:
        logger.warning("SearXNG dorking timed out; skipping")
        return 0
    except Exception as exc:
        logger.warning(f"SearXNG dorking: {exc}")
        return 0
    return await publish_urls(ctx, [o.url for o in obs], "searxng_dork")


async def poll_board(board: dict[str, str], store: Any) -> list[JobObservation]:
    """Poll one board: direct ATS API first, browser re-map when stale."""
    from src.radar.sources.sources import (
        diff_snapshots,
        get_checkpoint,
        record_failure,
        record_success,
        should_poll,
    )

    source_id = board["id"]
    board_url = board["url"]
    source_type = board.get("source_type", "discovery_index")
    is_official = source_type == "official_ats"
    if not should_poll(source_id):
        return []
    if not board_url or not board_url.startswith("http"):
        return []

    logger.info(f"Polling board: {source_id}")

    # Workday CXS search: hundreds of structured postings, zero renders.
    if "myworkdayjobs.com" in (board_url or "").lower():
        try:
            import httpx

            from src.radar.sources.workday import poll_workday_board

            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                return await poll_workday_board(board_url, client)
        except Exception as exc:
            logger.warning(f"Workday poll failed for {board_url}: {exc}")
            record_failure(source_id)
            return []

    try:
        from src.radar.sources.ats_interceptor import intercept_ats_board, parse_ats_slug

        ats_obs = await intercept_ats_board(board_url, source_id)
        if ats_obs is not None:
            state = diff_snapshots(source_id, [obs.url for obs in ats_obs])
            new_urls = set(state.new_urls)
            new_obs = [obs for obs in ats_obs if obs.url in new_urls]
            record_success(source_id, len(new_obs), len(new_obs))
            from src.pipeline.persist import record_ats_evidence

            await record_ats_evidence(store, board_url, ats_obs)
            return new_obs
        if is_official and parse_ats_slug(board_url):
            record_failure(source_id)
            logger.info(f"ATS API unavailable; deferring browser fallback: {source_id}")
            return []
    except Exception as e:
        logger.debug(f"ATS interceptor fallback for {board_url}: {e}")

    ats_cfg = get_config().ats
    cp = get_checkpoint(source_id)
    if cp.last_snapshot_hash and cp.last_polled:
        snapshot_age_hours = (time.time() - cp.last_polled) / 3600.0
        if snapshot_age_hours < ats_cfg.snapshot_ttl_hours:
            return []

    direct_urls: list[str] = []
    try:
        from src.render import extract_links

        fc_cfg = get_config().render
        direct_urls = await asyncio.wait_for(
            extract_links(board_url, job_only=True, limit=fc_cfg.map_limit),
            timeout=120.0,
        )
    except Exception as exc:
        logger.warning(f"Board map failed for {board_url}: {exc}")
        record_failure(source_id)
        return []

    if not direct_urls:
        if store is not None and is_official and get_checkpoint(source_id).last_snapshot_count > 0:
            from src.pipeline.persist import record_ats_no_openings

            await record_ats_no_openings(store, board_url)
        record_success(source_id, 0, 0)
        return []

    had_prior = bool(get_checkpoint(source_id).last_snapshot_hash)
    state = diff_snapshots(source_id, direct_urls)
    new_urls = state.new_urls
    logger.info(f"Board {source_id}: {len(direct_urls)} URLs mapped, {len(new_urls)} new")

    observations: list[JobObservation] = []
    for url in new_urls:
        observations.append(
            JobObservation(
                url=url,
                source=source_id,
                title="",
                snippet="",
                extra={
                    "is_snapshot_delta": had_prior,
                    "official_source": is_official,
                    "source_type": source_type,
                },
                source_freshness_evidence=None,
            )
        )
    record_success(source_id, len(new_urls), len(new_urls))
    return observations


async def board_poll_tick(ctx: Any) -> int:
    """Poll a bounded batch of due boards (lane scheduling decides due)."""
    from src.radar.sources.sources import load_active_sources, select_sources_for_sweep

    active = await load_active_sources(ctx.store)
    for board_id, url, source_type in REGISTERED_BOARDS:
        if not any(s["id"] == board_id for s in active):
            active.append({"id": board_id, "url": url, "source_type": source_type})
    ranked = select_sources_for_sweep(active)
    cap = int(os.environ.get("BOARD_POLL_BATCH", str(BOARD_BATCH)))
    batch = ranked[:cap]
    if not batch:
        return 0
    sem = asyncio.Semaphore(BOARD_SEM)

    async def _one(board: dict[str, str]) -> list[JobObservation]:
        async with sem:
            try:
                return await poll_board(board, ctx.store)
            except Exception as exc:
                logger.warning(f"Board poll failed: {exc}")
                return []

    results = await asyncio.gather(*(_one(b) for b in batch))
    observations: list[JobObservation] = []
    for obs_list in results:
        observations.extend(obs_list)
    # Structured passthrough: interceptor/workday obs already carry verified
    # content — persist them directly so fetch never re-renders them.
    from src.pipeline.persist import persist_structured

    published = await persist_structured(ctx, observations)
    # Persist lane/checkpoint state so restarts keep poll frequencies (120s).
    if await due(ctx.bus.redis, "checkpoints", 120.0):
        try:
            from src.radar.sources.sources import persist_checkpoints

            await persist_checkpoints(ctx.store)
        except Exception:
            pass
    return published


async def company_discovery_tick(ctx: Any) -> int:
    """Discover new company sources on the low-frequency lane (default 30min)."""
    interval = get_config().radar.poll_low_freq_seconds
    if not await due(ctx.bus.redis, "company", interval):
        return 0
    try:
        discovered = await asyncio.wait_for(_discover_new_companies(), timeout=300)
        added = await _persist_discovered_sources(ctx.store, discovered)
        try:
            from src.radar.sources.sources import persist_checkpoints

            await persist_checkpoints(ctx.store)
        except Exception:
            pass
        return len(added)
    except Exception:
        logger.warning("Company discovery failed", exc_info=True)
        return 0


async def _discover_new_companies() -> list[dict[str, Any]]:
    from src.radar.sources.common_crawl import discover_from_common_crawl
    from src.radar.sources.discovery import (
        _extract_domain as _discovery_domain,
    )
    from src.radar.sources.discovery import (
        _resolve_company_domain,
        detect_ats_for_company,
        discover_from_azure,
        discover_from_betalist,
        discover_from_dealroom,
        discover_from_hackernews,
        discover_from_remoteok,
        discover_from_vc_portfolios,
        discover_from_weworkremotely,
        discover_from_yc,
    )
    from src.radar.sources.sources import get_all_checkpoints

    cfg = get_config()
    discovery_source = cfg.radar.discovery_source if cfg else "all"
    results: list[dict[str, Any]] = []
    if discovery_source == "none":
        return results
    if discovery_source == "azure":
        try:
            azure_companies = await discover_from_azure(limit=6000)
            for c in azure_companies:
                c.setdefault("discovered_from", "azure")
            results.extend(azure_companies)
        except Exception as e:
            logger.warning("Azure discovery failed", exception=str(e))
        if not results:
            return results
        known_slugs: set[str] = set()
        for sid in get_all_checkpoints():
            if sid.startswith("discovered:"):
                parts = sid.split(":", 2)
                if len(parts) >= 2:
                    known_slugs.add(parts[1])
        fresh = [
            c
            for c in azure_companies
            if c.get("name", "").lower().replace(" ", "-")[:40] not in known_slugs
        ]
        batch_cap = int(os.environ.get("AZURE_DISCOVERY_BATCH", "300"))
        return fresh[:batch_cap]

    adapters = [
        ("common_crawl", discover_from_common_crawl, 1500),
        ("dealroom", discover_from_dealroom, 50),
        ("yc", discover_from_yc, 30),
        ("vc", discover_from_vc_portfolios, 40),
        ("hn", discover_from_hackernews, 30),
        ("remoteok", discover_from_remoteok, 30),
        ("weworkremotely", discover_from_weworkremotely, 30),
        ("betalist", discover_from_betalist, 30),
    ]
    from src.radar.sources.crawler import run_search_discovery

    try:
        search_results = await run_search_discovery(max_total_results=150)
        for c in search_results:
            c["discovered_from"] = c.get("source", "search")
        results.extend(search_results)
    except Exception as e:
        logger.warning("Search crawler failed", exception=str(e))
    for adp_name, func, limit in adapters:
        try:
            companies = await func(limit)
            for c in companies:
                c["discovered_from"] = adp_name
            results.extend(companies)
        except Exception as e:
            logger.warning(f"Discovery adapter {adp_name} failed", exception=str(e))

    seen_domains: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in results:
        domain = _discovery_domain(c.get("website", ""))
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            deduped.append(c)
        elif not domain and c["name"] not in {d["name"] for d in deduped}:
            deduped.append(c)

    prior_slugs: set[str] = set()
    for sid in get_all_checkpoints():
        if sid.startswith("discovered:"):
            parts = sid.split(":", 2)
            if len(parts) >= 2:
                prior_slugs.add(parts[1])

    from src.radar.sources.discovery import is_aggregator_domain

    sem = asyncio.Semaphore(10)

    async def _probe_company(c: dict[str, Any]) -> None:
        async with sem:
            name_slug = c.get("name", "").lower().replace(" ", "-")[:40]
            if name_slug in prior_slugs:
                return
            website = c.get("website", "")
            if (
                (not website or not website.startswith("http"))
                and c.get("name")
                and (domain := await _resolve_company_domain(c["name"]))
            ):
                website = f"https://{domain}"
                c["website"] = website
            if not website or not website.startswith("http"):
                return
            if is_aggregator_domain(
                website.replace("https://", "").replace("http://", "").split("/")[0]
            ):
                return
            ats_url = await detect_ats_for_company(website)
            if ats_url:
                c["ats_url"] = ats_url

    await asyncio.gather(*(_probe_company(c) for c in deduped))
    logger.info(f"Discovery: {len(deduped)} companies probed")
    return deduped


async def _persist_discovered_sources(
    store: Any,
    discovered: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from src.radar.sources.sources import _SOURCE_CHECKPOINTS, get_checkpoint, register_source

    added: list[dict[str, Any]] = []
    for c in discovered:
        name = c.get("name", "").strip()
        if not is_plausible_company_name(name):
            continue
        website = c.get("website", "")
        board_url = c.get("ats_url", website) or website
        name_slug = c.get("name", "").lower().replace(" ", "-")[:40]
        source_id = f"discovered:{name_slug}:{_hash_board_url(board_url)}"
        try:
            already = source_id in _SOURCE_CHECKPOINTS
            register_source(source_id, "ats_board", initial_quality=0.5)
            cp = get_checkpoint(source_id)
            cp.board_url = c.get("ats_url", website)
            cp.company_name = c.get("name", "")
            cp.discovery_origin = c.get("source", "")
            cp.active = True
            if not already:
                added.append({"name": name, "url": board_url or website, "source_id": source_id})
        except Exception:
            continue
    # Detect ATS endpoints for newly added companies best-effort.
    try:
        from src.radar.sources.discovery import detect_ats_for_company as _detect

        for c in added:
            try:
                ats = await _detect(c["url"])
                if ats:
                    c["ats_url"] = ats
            except Exception:
                continue
    except Exception:
        pass
    return added
