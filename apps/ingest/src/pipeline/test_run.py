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
