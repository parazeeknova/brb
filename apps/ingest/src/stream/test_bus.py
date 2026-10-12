"""Tests for StreamBus: pure naming + live Redis roundtrip (skipped w/o redis)."""

from __future__ import annotations

import time
import uuid

import pytest

from src.stream.bus import StreamBus, group_for


def test_group_for_namespaces_per_stream() -> None:
    assert group_for("ho:s:discover") == "ho:g:discover"
    assert group_for("ho:s:raw") == "ho:g:raw"


def _redis_or_skip() -> object:
    pytest.importorskip("redis")
    from redis.asyncio import Redis

    from src.stream.redis_url import redis_url

    url = redis_url()
    client = Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
    return client


@pytest.mark.asyncio
async def test_publish_read_ack_roundtrip() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    bus = StreamBus(client, maxlen=100, block_ms=200)
    stream = f"ho:test:{uuid.uuid4().hex[:8]}"
    group = group_for(stream)
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
        entry_id = await bus.publish(stream, {"url": "https://x", "source": "t"})
        assert entry_id
        assert await bus.depth(stream) == 1
        msgs = await bus.read(stream, "c1", count=10)
        assert len(msgs) == 1
        assert msgs[0][1] == {"url": "https://x", "source": "t"}
        await bus.ack(stream, msgs[0][0])
        assert await bus.read(stream, "c1", count=10) == []
    finally:
        await client.delete(stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_ensure_groups_idempotent_and_depths() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    bus = StreamBus(client, maxlen=100, block_ms=200)
    try:
        await bus.ensure_groups()
        await bus.ensure_groups()
        depths = await bus.depths()
        assert set(depths) >= {"ho:s:discover", "ho:s:raw"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_reap_stream_dlqs_hopeless_entry() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:test:{uuid.uuid4().hex[:8]}"
    group = group_for(stream)
    bus = StreamBus(client, maxlen=100, block_ms=200, claim_idle_ms=1, max_deliveries=1)
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
        await bus.publish(stream, {"k": "v"})
        # Deliver once without ack so it sits pending with 1 delivery.
        got = await bus.read(stream, "holder", count=1)
        assert len(got) == 1
        time.sleep(0.05)  # exceed claim_idle_ms=1 so autoclaim picks it up
        reclaimed = await bus.reap_stream(stream)
        assert reclaimed == 1
        # Hopeless entry moved to the DLQ and acked off the stream.
        dlq = await client.xrange("ho:s:dlq", count=20)
        assert any(fields.get("origin_stream") == stream for _eid, fields in dlq), (
            "expected DLQ record"
        )
    finally:
        await client.delete(stream)
        # Clean any DLQ rows this test created.
        for eid, fields in await client.xrange("ho:s:dlq", count=100):
            if fields.get("origin_stream") == stream:
                await client.xdel("ho:s:dlq", eid)
        await client.aclose()


def test_redis_url_password_beats_bare_explicit(monkeypatch) -> None:
    from src.stream import redis_url as mod

    monkeypatch.setenv("REDIS_PASSWORD", "s3cret")
    monkeypatch.setenv("STREAMS_REDIS_URL", "redis://127.0.0.1:6380/0")
    assert mod.redis_url() == "redis://:s3cret@127.0.0.1:6380/0"
    monkeypatch.delenv("REDIS_PASSWORD")
    assert mod.redis_url() == "redis://127.0.0.1:6380/0"
