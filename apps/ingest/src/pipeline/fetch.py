"""Fetch stage: discover stream -> verified page text -> raw stream.

Route order (fastest + most trustworthy first):
1. ATS-direct JSON APIs (greenhouse/lever): sub-second, structured,
   verified by construction. No browser, no render budget burned.
2. Static fetch is inside markdownify (httpx + markitdown first).
3. TinyFish Fetch API for JS-shell leftovers (off-box render, capped).
4. Local markdownify/browser as the last resort.

Only verified observations enter the raw stream. Anything that cannot be
proven a real posting is dropped here — search snippets are leads, and
leads are not jobs.
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any

from src.configuration import get_config
from src.logging import get_logger
from src.pipeline import model
from src.pipeline.persist import persist_observation, posting_id, save_content
from src.radar.core.models import JobObservation

logger = get_logger("pipeline_fetch")

MIN_MARKDOWN_CHARS = 400


def _tinyfish_key() -> str:
    return os.environ.get("TINY_FISH_API_KEY", "").strip()


async def _tinyfish_fallback(ctx: Any, url: str) -> tuple[str, str] | None:
    """Off-box render for JS shells. Returns (title, markdown) or None."""
    key = _tinyfish_key()
    if not key:
        return None
    try:
        from src.radar.sources.tinyfish_fetch import _spend, fetch_pages

        allowed = await _spend(ctx.bus.redis, 1)
        if allowed < 1:
            return None
        import httpx

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            pages = await fetch_pages(client, key, [url])
    except Exception as exc:
        logger.debug(f"TinyFish fetch failed for {url}: {exc}")
        return None
    page = pages.get(url)
    if not page or len(page.get("markdown", "")) < MIN_MARKDOWN_CHARS:
        return None
    return page.get("title", ""), page["markdown"]


async def fetch_one(ctx: Any, url: str, source: str) -> str | None:
    """Fetch + verify + persist one URL. Returns url_hash, else None."""
    cfg = get_config().render
    import httpx

    # 1. ATS-direct: structured JSON, verified by construction.
    try:
        from src.radar.sources.ats_direct import fetch_ats_job

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
            ats_obs = await fetch_ats_job(url, client)
        if ats_obs is not None:
            ats_obs.observed_at = time.time()
            ats_obs.verified = True
            ats_obs.verification_method = "ats_api"
            pid = posting_id(ats_obs)
            await persist_observation(ctx.store, ats_obs, pid)
            await save_content(
                ctx.store, pid, ats_obs.raw_markdown, ats_obs.extra.get("company_slug", "")
            )
            await ctx.store.record_pipeline_stage_event("fetch_ats", 1)
            return pid
    except Exception as exc:
        logger.debug(f"ATS-direct failed for {url}: {exc}")

    # 2-4. Render chain: local static+browser first, TinyFish off-box on shells.
    obs = JobObservation(url=url, source=source, title="", snippet="")
    pid = posting_id(obs)
    md = ""
    try:
        from src.render import markdownify

        md = await markdownify(url, timeout=cfg.scrape_timeout)
    except Exception as exc:
        logger.debug(f"Render failed for {url}: {exc}")
    title = ""
    if not md or len(md) < MIN_MARKDOWN_CHARS:
        fetched = await _tinyfish_fallback(ctx, url)
        if fetched is not None:
            title, md = fetched
    if not md or len(md) < MIN_MARKDOWN_CHARS:
        return None
    obs.raw_markdown = md
    if title:
        obs.title = title
    obs.observed_at = time.time()
    await persist_observation(ctx.store, obs, pid)
    await save_content(ctx.store, pid, md)
    with contextlib.suppress(Exception):
        await ctx.store.record_pipeline_stage_event("fetch", 1)
    return pid


async def handle_discover(ctx: Any, fields: dict[str, str]) -> None:
    """Consume one discover message: fetch, persist, forward to raw stream."""
    url = (fields.get("url") or "").strip()
    source = fields.get("source", "discover")
    if not model.valid_url(url):
        return
    pid = await fetch_one(ctx, url, source)
    if pid is None:
        return
    await ctx.bus.publish("ho:s:raw", model.raw_fields(pid, url, source))
