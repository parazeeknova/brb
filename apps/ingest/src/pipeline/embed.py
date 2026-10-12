"""Embed stage: embed stream -> batched vectors -> obs_embeddings.

Replaces scripts/embed/embed_obs.py (offline batch loop) with a continuous
consumer. Batch size 32 matches the old script; the embed API absorbs bursts
and failed items redeliver via the stream PEL until the DLQ takes them.
"""

from __future__ import annotations

import contextlib
import hashlib
from typing import Any

from src.logging import get_logger

logger = get_logger("pipeline_embed")

EMBED_BATCH = 32
BACKFILL_LIMIT = 2000


def content_fingerprint(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def embed_texts(ctx: Any, items: list[dict[str, Any]]) -> int:
    """Embed one batch of {url_hash, title, company, content_hash, text}."""
    from src.llm.embed_client import embed as embed_batch

    texts = [(it.get("text") or "")[:4000] for it in items]
    try:
        vectors = await embed_batch(texts)
    except Exception as exc:
        logger.warning(f"Embed batch failed ({len(texts)} texts): {exc}")
        raise
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embed shape mismatch: {len(vectors)} vectors for {len(texts)} texts")
    written = 0
    for item, vec in zip(items, vectors, strict=False):
        if not vec:
            continue
        try:
            await ctx.store.upsert_obs_embedding(
                url_hash=item["url_hash"],
                title=item.get("title", ""),
                company=item.get("company", ""),
                embedding=list(vec),
                content_hash=item.get("content_hash") or content_fingerprint(item.get("text", "")),
            )
            written += 1
        except Exception:
            continue
    with contextlib.suppress(Exception):
        await ctx.store.record_pipeline_stage_event("embed", written)
    return written


async def handle_embed(ctx: Any, fields: dict[str, str]) -> None:
    """Consume one embed message (items accumulate into batches)."""
    url_hash = (fields.get("url_hash") or "").strip()
    if not url_hash:
        return
    try:
        missing = await ctx.store.missing_obs_hashes([url_hash])
    except Exception:
        missing = [url_hash]
    if not missing:
        return
    items = await ctx.store.embed_texts_for(missing)
    items = [it for it in items if (it.get("text") or "").strip()]
    if not items:
        return
    for start in range(0, len(items), EMBED_BATCH):
        await embed_texts(ctx, items[start : start + EMBED_BATCH])


async def backfill_unembedded(ctx: Any, limit: int = BACKFILL_LIMIT) -> int:
    """Boot backfill: enqueue the stored-but-unembedded backlog once.

    Replaces the embed_obs.py sidecar. Bounded so restarts never flood.
    """
    try:
        rows = await ctx.store.unembedded_obs(limit=limit, software_first=True)
    except Exception as exc:
        logger.warning(f"Embed backfill query failed: {exc}")
        return 0
    queued = 0
    for row in rows:
        url = row.get("url", "")
        if not url:
            continue
        try:
            await ctx.bus.publish("ho:s:embed", {"url_hash": hashlib.md5(url.encode()).hexdigest()})
            queued += 1
        except Exception:
            break
    if queued:
        logger.info(f"Embed backfill: {queued} unembedded observations queued")
    return queued
