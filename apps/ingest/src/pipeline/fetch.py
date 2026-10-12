"""Fetch stage: discover stream -> page text -> observation rows -> raw stream.

One consumer per worker; BLOCK reads park idle workers (no sleeps).
Persistent Redis dedup runs BEFORE fetching so seen URLs never re-render.
Scraped markdown is archived into the observation row so the corpus keeps
JD bodies (the sweep dropped them after gating).
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from src.configuration import get_config
from src.logging import get_logger
from src.pipeline import model
from src.pipeline.persist import persist_observation, posting_id, save_markdown
from src.radar.core.models import JobObservation

logger = get_logger("pipeline_fetch")


async def fetch_one(ctx: Any, url: str, source: str) -> str | None:
    """Fetch + persist one URL. Returns url_hash, or None when dropped."""
    cfg = get_config().render
    obs = JobObservation(url=url, source=source, title="", snippet="")
    pid = posting_id(obs)
    try:
        from src.render import markdownify

        md = await markdownify(url, timeout=cfg.scrape_timeout)
    except Exception as exc:
        logger.debug(f"Fetch failed for {url}: {exc}")
        return None
    if not md or len(md) < 100:
        return None
    obs.raw_markdown = md
    obs.observed_at = time.time()
    await persist_observation(ctx.store, obs, pid)
    await save_markdown(ctx.store, pid, md)
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
