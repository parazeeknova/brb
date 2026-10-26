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
async def test_reap_stream_dlqs_hopeless_entry(monkeypatch) -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:test:{uuid.uuid4().hex[:8]}"
    dlq_stream = f"{stream}:dlq"
    monkeypatch.setattr("src.stream.bus.STREAM_DLQ", dlq_stream)
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
        dlq = await client.xrange(dlq_stream, count=20)
        assert any(fields.get("origin_stream") == stream for _eid, fields in dlq), (
            "expected DLQ record"
        )
    finally:
        await client.delete(stream, dlq_stream)
        await client.aclose()


def test_redis_url_password_beats_bare_explicit(monkeypatch) -> None:
    from src.stream import redis_url as mod

    monkeypatch.setenv("REDIS_PASSWORD", "s3cret")
    monkeypatch.setenv("STREAMS_REDIS_URL", "redis://127.0.0.1:6380/0")
    assert mod.redis_url() == "redis://:s3cret@127.0.0.1:6380/0"
    monkeypatch.delenv("REDIS_PASSWORD")
    assert mod.redis_url() == "redis://127.0.0.1:6380/0"


@pytest.mark.asyncio
async def test_stale_pending_work_is_deliverable_to_replacement() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:resume:{uuid.uuid4().hex[:8]}"
    bus = StreamBus(client, block_ms=10, claim_idle_ms=1)
    try:
        await client.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
        await bus.publish(stream, {"url_hash": "saved-progress"})
        original = await bus.read(stream, "old-process")
        time.sleep(0.02)
        assert await bus.reap_stream(stream) == 1
        resumed = await bus.read(stream, "replacement")
        assert len(resumed) == 1
        assert resumed[0][0] != original[0][0]
        assert resumed[0][1]["url_hash"] == "saved-progress"
        await bus.ack(stream, resumed[0][0])
        assert await bus.depth(stream) == 0
    finally:
        await client.delete(stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_graceful_handoff_does_not_wait_for_stale_timeout_or_spend_retry() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:resume:{uuid.uuid4().hex[:8]}"
    bus = StreamBus(client, block_ms=10, claim_idle_ms=300000, max_deliveries=1)
    try:
        await client.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
        await bus.publish(stream, {"url_hash": "unfinished"})
        await bus.read(stream, "old-process")
        assert await bus.release_consumer(stream, "old-process") == 1
        resumed = await bus.read(stream, "replacement")
        assert resumed[0][1]["url_hash"] == "unfinished"
        assert resumed[0][1]["_brb_deliveries"] == "0"
    finally:
        await client.delete(stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_backlog_never_trims_unprocessed_work() -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:resume:{uuid.uuid4().hex[:8]}"
    bus = StreamBus(client, block_ms=10, maxlen=1)
    try:
        await client.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
        await bus.publish(stream, {"url_hash": "first"})
        await bus.publish(stream, {"url_hash": "second"})
        messages = await bus.read(stream, "worker", count=10)
        assert [fields["url_hash"] for _, fields in messages] == ["first", "second"]
    finally:
        await client.delete(stream)
        await client.aclose()


@pytest.mark.asyncio
async def test_requeued_failures_keep_retry_budget_and_deadletter_payload(monkeypatch) -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:resume:{uuid.uuid4().hex[:8]}"
    dlq = f"{stream}:dlq"
    monkeypatch.setattr("src.stream.bus.STREAM_DLQ", dlq)
    bus = StreamBus(client, block_ms=10, claim_idle_ms=1, max_deliveries=2)
    try:
        await client.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
        await bus.publish(stream, {"url_hash": "poison"})
        await bus.read(stream, "first-process")
        time.sleep(0.02)
        assert await bus.reap_stream(stream) == 1
        await bus.read(stream, "replacement")
        time.sleep(0.02)
        assert await bus.reap_stream(stream) == 1
        records = await client.xrange(dlq)
        assert len(records) == 1
        assert records[0][1]["url_hash"] == "poison"
        assert records[0][1]["error"] == "delivered 2x without ack"
        assert await bus.depth(stream) == 0
    finally:
        await client.delete(stream, dlq)
        await client.aclose()


@pytest.mark.asyncio
async def test_startup_compaction_keeps_pending_and_undelivered_work(monkeypatch) -> None:
    client = _redis_or_skip()
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local redis")
    stream = f"ho:resume:{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr("src.stream.bus.ALL_STREAMS", (stream,))
    bus = StreamBus(client, block_ms=10)
    try:
        await bus.ensure_groups()
        ids = [await bus.publish(stream, {"n": str(n)}) for n in range(3)]
        await bus.read(stream, "old-process", count=2)
        # Simulate acknowledged history left behind by the previous version.
        await client.xack(stream, group_for(stream), ids[0])
        await bus.ensure_groups()
        retained = await client.xrange(stream)
        assert [entry_id for entry_id, _ in retained] == ids[1:]
        pending = await client.xpending(stream, group_for(stream))
        assert pending["pending"] == 1
        assert pending["min"] == ids[1]
    finally:
        await client.delete(stream)
        await client.aclose()
