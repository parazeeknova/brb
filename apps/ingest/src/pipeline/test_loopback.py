"""Live loopback: real Redis + Postgres, fake discovery/fetch edges.

Injects one discover message, runs fetch -> normalize -> embed handlers for
real, and asserts the corpus rows exist. Skipped without local infra.
Proves end-to-end wiring without a full pipeline boot.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from src.pipeline import embed as embed_stage
from src.pipeline import fetch as fetch_stage
from src.pipeline import normalize as normalize_stage
from src.pipeline.ctx import KnownState, PipelineCtx
from src.stream.bus import StreamBus, group_for


async def _infra() -> tuple[object, object, StreamBus] | None:
    try:
        from redis.asyncio import Redis

        from src.memory.pgvector_store import MemoryStore

        redis = Redis.from_url("redis://127.0.0.1:6380/0", decode_responses=True)
        await redis.ping()
        store = await MemoryStore.create()
        return redis, store, StreamBus(redis, maxlen=100, block_ms=500)
    except Exception:
        return None


@pytest.mark.asyncio
async def _always_true(ctx, obs) -> bool:
    return True


async def test_loopback_one_url_to_embedding(monkeypatch) -> None:
    from pathlib import Path as _Path

    from dotenv import load_dotenv

    _root = _Path(__file__).resolve().parent.parent.parent.parent.parent
    load_dotenv(_root / ".env.development", override=False)
    load_dotenv(_root / ".env", override=False)
    import os

    if not os.environ.get("EMBED_URL") or not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("no embed credentials")
    # get_config() is a process singleton that an earlier test may have built
    # before dotenv loaded: pin the embed endpoint for this test, restore after.
    from src.configuration import get_config

    prev_url = get_config().embed.url
    get_config().embed.url = os.environ["EMBED_URL"]
    infra = await _infra()
    if infra is None:
        get_config().embed.url = prev_url
        pytest.skip("no local redis/postgres")
    redis, store, bus = infra
    seen_hash = ""
    try:
        await bus.ensure_groups()
        # No stream trimming: these are shared production streams and this
        # test uses unique URLs/consumers, so it neither needs nor disturbs
        # existing entries.

        from src.radar.core.dedup_engine import FastDeduplicationEngine

        dedup = FastDeduplicationEngine(enable_redis=False)
        await dedup.initialize()
        monkeypatch.setattr(
            "src.pipeline.normalize.verify_posting", lambda ctx, obs: _always_true(ctx, obs)
        )
        ctx = PipelineCtx(store=store, graph=None, bus=bus, dedup=dedup)
        ctx.known = KnownState()

        async def fake_markdownify(url: str, timeout: float = 20.0) -> str:
            return "# Senior Product Designer\nDesign systems, Figma.\n" + "x" * 500

        monkeypatch.setattr("src.render.markdownify", fake_markdownify)

        # Isolated test streams: never touch production traffic.
        t_discover, t_raw, t_embed = "ho:t:discover", "ho:t:raw", "ho:t:embed"
        for stream in (t_discover, t_raw, t_embed):
            try:
                await redis.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
            except Exception as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
        url = f"https://boards.greenhouse.io/loopbacktest/{uuid.uuid4().hex[:8]}"
        await bus.publish(t_discover, {"url": url, "source": "loopback"})
        msgs = await bus.read(t_discover, "loopback-test", count=5)
        assert len(msgs) == 1
        # Re-route handler output onto the test streams.
        published: list[tuple[str, dict[str, str]]] = []
        orig_publish = bus.publish

        async def capture(stream: str, fields: dict[str, str]):
            remapped = {"ho:s:raw": t_raw, "ho:s:embed": t_embed}.get(stream, stream)
            published.append((remapped, fields))
            return await orig_publish(remapped, fields)

        bus.publish = capture  # type: ignore[method-assign]
        await fetch_stage.handle_discover(ctx, msgs[0][1])
        await bus.ack(t_discover, msgs[0][0])

        raw = await bus.read(t_raw, "loopback-test", count=5)
        assert len(raw) == 1
        url_hash = raw[0][1]["url_hash"]
        seen_hash = url_hash
        await normalize_stage.handle_raw(ctx, raw[0][1])
        await bus.ack(t_raw, raw[0][0])

        emb = await bus.read(t_embed, "loopback-test", count=5)
        assert len(emb) == 1
        assert emb[0][1]["url_hash"] == url_hash
        await embed_stage.handle_embed(ctx, emb[0][1])
        await bus.ack(t_embed, emb[0][0])

        # Corpus rows exist.
        rows = await store.fetch_observation_rows([url_hash])
        assert len(rows) == 1
        assert rows[0]["title"] or rows[0]["url"]
        async with store._pool.acquire() as conn:
            cand = await conn.fetchval(
                "SELECT canonical_id FROM radar_candidates WHERE canonical_id = $1",
                url_hash,
            )
            emb_row = await conn.fetchval(
                "SELECT url_hash FROM obs_embeddings WHERE url_hash = $1", url_hash
            )
        assert cand == url_hash, "accepted candidate row missing"
        assert emb_row == url_hash, "embedding row missing"
    finally:
        get_config().embed.url = prev_url
        try:
            if seen_hash:
                async with store._pool.acquire() as conn:
                    await conn.execute("DELETE FROM obs_embeddings WHERE url_hash = $1", seen_hash)
                    await conn.execute(
                        "DELETE FROM radar_candidates WHERE canonical_id = $1"
                        " OR canonical_id = 'rejected:' || $1",
                        seen_hash,
                    )
            async with store._pool.acquire() as conn:
                await conn.execute("DELETE FROM job_observations WHERE url LIKE '%loopbacktest%'")
        except Exception:
            pass
        try:
            for stream in ("ho:t:discover", "ho:t:raw", "ho:t:embed"):
                with contextlib.suppress(Exception):
                    await redis.delete(stream)
            await store.close()
            await redis.aclose()
        except Exception:
            pass
