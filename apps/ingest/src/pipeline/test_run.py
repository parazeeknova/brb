"""Supervisor tests: consume/ack loop and shutdown, all fakes."""

from __future__ import annotations

import asyncio
from typing import Any

from src.pipeline.run import Pipeline


class FakeBus:
    def __init__(self, messages: list[tuple[str, dict[str, str]]]) -> None:
        self._messages = list(messages)
        self.acked: list[str] = []
        self.consumer = "test-consumer"

    async def read(self, stream: str, consumer: str, count: int = 10):
        if not self._messages:
            await asyncio.sleep(0.01)
            return []
        batch, self._messages = self._messages[:count], self._messages[count:]
        return batch

    async def ack(self, stream: str, *ids: str) -> None:
        self.acked.extend(ids)

    async def depths(self) -> dict[str, int]:
        return {"ho:s:raw": len(self._messages)}

    async def reap_stale(self) -> int:
        return 0


class FakeCtx:
    def __init__(self, bus: FakeBus) -> None:
        self.bus = bus
        self.closed: list[str] = []


def test_consume_handles_and_acks_then_parks() -> None:
    async def go() -> None:
        bus = FakeBus([("1-0", {"url_hash": "h1"}), ("2-0", {"url_hash": "h2"})])
        pipe = Pipeline()
        pipe.ctx = FakeCtx(bus)  # type: ignore[assignment]
        seen: list[str] = []

        async def handler(ctx: Any, fields: dict[str, str]) -> None:
            seen.append(fields["url_hash"])
            if len(seen) >= 2:
                pipe.stop.set()

        await pipe._consume("ho:s:raw", handler, count=10)
        assert seen == ["h1", "h2"]
        assert bus.acked == ["1-0", "2-0"]

    asyncio.run(go())


def test_consume_failure_leaves_message_unacked() -> None:
    async def go() -> None:
        bus = FakeBus([("9-0", {"url_hash": "bad"})])
        pipe = Pipeline()
        pipe.ctx = FakeCtx(bus)  # type: ignore[assignment]

        async def handler(ctx: Any, fields: dict[str, str]) -> None:
            pipe.stop.set()
            raise RuntimeError("boom")

        await pipe._consume("ho:s:raw", handler, count=10)
        assert bus.acked == []

    asyncio.run(go())


def test_shutdown_closes_everything() -> None:
    async def go() -> None:
        closed: list[str] = []

        class Store:
            async def close(self) -> None:
                closed.append("store")

        class Graph:
            async def close(self) -> None:
                closed.append("graph")

        class Dedup:
            async def close(self) -> None:
                closed.append("dedup")

        class Redis:
            async def aclose(self) -> None:
                closed.append("redis")

        pipe = Pipeline()
        pipe.ctx = FakeCtx(FakeBus([]))  # type: ignore[assignment]
        pipe.ctx.store = Store()  # type: ignore[attr-defined]
        pipe.ctx.graph = Graph()  # type: ignore[attr-defined]
        pipe.ctx.dedup = Dedup()  # type: ignore[attr-defined]
        pipe._redis = Redis()
        pipe.stop.set()
        await pipe.shutdown()
        assert sorted(closed) == ["dedup", "graph", "redis", "store"]

    asyncio.run(go())


def test_health_server_reports_readiness(monkeypatch) -> None:
    import json
    import socket
    import urllib.request

    from src.pipeline.run import Pipeline, _start_health_server

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setenv("HEALTH_PORT", str(port))

    async def go() -> None:
        pipe = Pipeline()
        _start_health_server(pipe)
        await asyncio.sleep(0.2)

        def get(path: str):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")

        try:
            status, _ = get("/healthz")
            assert status == 200
            try:
                get("/readyz")
                raise AssertionError("readyz should 503 before boot")
            except urllib.error.HTTPError as e:
                assert e.code == 503
            pipe.ready = True
            pipe.ctx = object()
            status, body = get("/readyz")
            assert status == 200
            assert body["status"] == "ready"
        finally:
            pipe.stop.set()

    asyncio.run(go())


def test_shutdown_drains_handler_before_checkpoint_and_close(monkeypatch) -> None:
    async def go() -> None:
        from unittest.mock import AsyncMock

        import src.radar.sources.sources as sources

        events: list[str] = []
        entered = asyncio.Event()
        finish = asyncio.Event()
        bus = FakeBus([("1-0", {"url_hash": "h1"}), ("2-0", {"url_hash": "h2"})])
        bus.release_consumer = AsyncMock(side_effect=lambda *_: events.append("released"))
        pipe = Pipeline()
        ctx = FakeCtx(bus)
        ctx.store = type(
            "Store", (), {"close": AsyncMock(side_effect=lambda: events.append("closed"))}
        )()
        ctx.dedup = type("Dedup", (), {"close": AsyncMock()})()
        ctx.graph = None
        pipe.ctx = ctx
        pipe.ready = True

        async def persist(_store) -> None:
            events.append("checkpoint")

        monkeypatch.setattr(sources, "persist_checkpoints", persist)

        async def handler(_ctx, _fields) -> None:
            entered.set()
            await finish.wait()
            events.append("finished")

        task = asyncio.create_task(pipe._consume("ho:s:raw", handler, 10))
        pipe._tasks.append(task)
        await entered.wait()
        shutdown = asyncio.create_task(pipe.shutdown())
        await asyncio.sleep(0)
        assert not pipe.ready
        assert not shutdown.done()
        finish.set()
        await shutdown
        assert bus.acked == ["1-0"]
        assert events == ["finished", "checkpoint", "released", "closed"]
        await pipe.shutdown()  # A second cleanup cannot requeue twice.
        assert events.count("released") == 1

    asyncio.run(go())


def test_shutdown_timeout_leaves_unfinished_message_for_handoff(monkeypatch) -> None:
    async def go() -> None:
        from unittest.mock import AsyncMock

        import src.radar.sources.sources as sources

        monkeypatch.setenv("SHUTDOWN_DRAIN_SECONDS", "0")
        monkeypatch.setattr(sources, "persist_checkpoints", AsyncMock())
        entered = asyncio.Event()
        bus = FakeBus([("1-0", {"url_hash": "h1"})])
        bus.release_consumer = AsyncMock()
        pipe = Pipeline()
        ctx = FakeCtx(bus)
        ctx.store = type("Store", (), {"close": AsyncMock()})()
        ctx.dedup = type("Dedup", (), {"close": AsyncMock()})()
        ctx.graph = None
        pipe.ctx = ctx

        async def handler(_ctx, _fields) -> None:
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(pipe._consume("ho:s:raw", handler, 10))
        pipe._tasks.append(task)
        await entered.wait()
        await pipe.shutdown()
        assert bus.acked == []
        bus.release_consumer.assert_awaited_once_with("ho:s:raw", "test-consumer:raw:1")
        assert task.done()

    asyncio.run(go())


def test_stop_during_startup_cancels_boot_and_runs_cleanup(monkeypatch) -> None:
    async def go() -> None:
        import src.pipeline.run as run

        events: list[str] = []

        class StartingPipeline(Pipeline):
            def install_signal_handlers(self) -> None:
                events.append("handlers-installed")

            async def start(self) -> None:
                assert events == ["handlers-installed"]
                self.request_stop()  # Simulate SIGTERM while startup is in flight.
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("startup-cancelled")

            async def shutdown(self) -> None:
                events.append("closed")

        monkeypatch.setattr(run, "Pipeline", StartingPipeline)
        monkeypatch.setattr(run, "_start_health_server", lambda _: None)
        assert await asyncio.wait_for(run.amain(), timeout=1) == 0
        assert events == ["handlers-installed", "startup-cancelled", "closed"]

    asyncio.run(go())
