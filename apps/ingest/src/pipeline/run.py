"""Pipeline entrypoint: ``python -m src.pipeline.run`` — all stages, forever.

One process runs every stage as asyncio tasks over Redis-Streams consumer
groups; scale by running more processes (loop.py spawns P copies, groups
coordinate). No sweeps, no phases, no sleeps on hot paths: consumers park
in BLOCK reads, producers park on interval guards (+1s idle tick).
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import contextlib

from src.configuration import get_config
from src.logging import get_logger
from src.pipeline.ctx import PipelineCtx
from src.stream.bus import (
    STREAM_DISCOVER,
    STREAM_EMBED,
    STREAM_RAW,
    StreamBus,
)

logger = get_logger("pipeline_run")

Handler = Callable[[PipelineCtx, dict[str, str]], Awaitable[None]]


class Pipeline:
    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.ctx: PipelineCtx | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._redis: Any = None
        self._consumer_seq = 0
        self._dork_engine: Any = None

    # -- boot ----------------------------------------------------------

    async def start(self) -> None:
        from redis.asyncio import Redis

        from src.http_cache import set_http_cache_store
        from src.memory.pgvector_store import MemoryStore
        from src.radar.core.dedup_engine import FastDeduplicationEngine
        from src.radar.sources.dorking import DorkingEngine

        cfg = get_config()
        self._redis = Redis.from_url(
            cfg.streams.redis_url, decode_responses=True, socket_timeout=5.0
        )
        await self._redis.ping()
        bus = StreamBus(
            self._redis,
            maxlen=cfg.pipeline.stream_maxlen,
            block_ms=cfg.pipeline.block_ms,
            claim_idle_ms=cfg.streams.claim_idle_ms,
            max_deliveries=cfg.streams.max_deliveries,
        )
        await bus.ensure_groups()

        store = await MemoryStore.create()
        set_http_cache_store(store)

        graph = None
        try:
            from src.graph.graph_store import GraphStore

            graph = await GraphStore.create()
        except Exception as exc:
            logger.warning(f"Graph unavailable, continuing without Neo4j intel: {exc}")

        dedup = FastDeduplicationEngine()
        await dedup.initialize()

        try:
            from src.radar.sources.sources import load_checkpoints

            await load_checkpoints(store)
        except Exception:
            pass

        self.ctx = PipelineCtx(store=store, graph=graph, bus=bus, dedup=dedup)
        self._dork_engine = DorkingEngine()

        reclaimed = await bus.reap_stale()
        if reclaimed:
            logger.info(f"Reclaimed {reclaimed} stale stream entries on boot")
        await self._backfill_embed()
        await self._backfill_ungated()

        n_fetch = cfg.pipeline.fetch_workers
        n_norm = cfg.pipeline.normalize_workers
        n_embed = cfg.pipeline.embed_workers
        from src.pipeline import embed as embed_stage
        from src.pipeline import fetch as fetch_stage
        from src.pipeline import normalize as normalize_stage

        self._tasks.append(asyncio.create_task(self._producer_loop(), name="producers"))
        for i in range(n_fetch):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(STREAM_DISCOVER, fetch_stage.handle_discover, count=5),
                    name=f"fetch-{i}",
                )
            )
        for i in range(n_norm):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(STREAM_RAW, normalize_stage.handle_raw, count=10),
                    name=f"normalize-{i}",
                )
            )
        for i in range(n_embed):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(STREAM_EMBED, embed_stage.handle_embed, count=32),
                    name=f"embed-{i}",
                )
            )
        self._tasks.append(asyncio.create_task(self._graph_metrics_loop(), name="graph-metrics"))
        self._tasks.append(asyncio.create_task(self._status_loop(), name="status"))
        self._tasks.append(asyncio.create_task(self._reap_loop(), name="reap"))
        logger.info(
            f"Pipeline up: fetch x{n_fetch}, normalize x{n_norm}, embed x{n_embed}, producers on"
        )

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError, RuntimeError:
                signal.signal(sig, lambda *_: self.stop.set())
        await self.stop.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        self.stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        ctx = self.ctx
        if ctx is not None:
            with contextlib.suppress(Exception):
                await ctx.dedup.close()
            with contextlib.suppress(Exception):
                await ctx.store.close()
            if ctx.graph is not None:
                with contextlib.suppress(Exception):
                    await ctx.graph.close()
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
        try:
            from src.http_client import close_all as _close_http_clients

            await _close_http_clients()
        except Exception:
            pass

    # -- backfills -----------------------------------------------------

    async def _backfill_embed(self) -> None:
        assert self.ctx is not None
        try:
            from src.pipeline import embed as embed_stage

            await embed_stage.backfill_unembedded(self.ctx)
        except Exception as exc:
            logger.warning(f"Embed backfill failed: {exc}")

    async def _backfill_ungated(self, limit: int = 2000) -> None:
        """Boot drain: stored-but-undecided observations re-enter at raw."""
        assert self.ctx is not None
        try:
            hashes = await self.ctx.store.ungated_hashes(limit=limit)
        except Exception as exc:
            logger.warning(f"Ungated backfill query failed: {exc}")
            return
        queued = 0
        for h in hashes:
            try:
                await self.ctx.bus.publish(STREAM_RAW, {"url_hash": h})
                queued += 1
            except Exception:
                break
        if queued:
            logger.info(f"Ungated backfill: {queued} observations re-queued")

    # -- loops ---------------------------------------------------------

    async def _producer_loop(self) -> None:
        assert self.ctx is not None
        from src.pipeline import producers

        while not self.stop.is_set():
            total = 0
            try:
                total += await producers.high_volume_tick(self.ctx)
                total += await producers.mass_poller_tick(self.ctx)
                total += await producers.github_tick(self.ctx)
                total += await producers.dork_tick(self.ctx, self._dork_engine)
                total += await producers.board_poll_tick(self.ctx)
                total += await producers.company_discovery_tick(self.ctx)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Producer tick failed: {exc}")
            if total == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), timeout=1.0)

    def _next_consumer(self, stream: str) -> str:
        self._consumer_seq += 1
        assert self.ctx is not None
        return f"{self.ctx.bus.consumer}:{stream.rsplit(':', 1)[-1]}:{self._consumer_seq}"

    async def _consume(self, stream: str, handler: Handler, count: int) -> None:
        assert self.ctx is not None
        consumer = self._next_consumer(stream)
        bus = self.ctx.bus
        while not self.stop.is_set():
            try:
                msgs = await bus.read(stream, consumer, count=count)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Stream read failed ({stream}): {exc}")
                await asyncio.sleep(1.0)
                continue
            for entry_id, fields in msgs:
                if self.stop.is_set():
                    return
                try:
                    await handler(self.ctx, fields)
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    logger.warning(f"Message failed ({stream} {entry_id}): {exc}")
                    continue
                with contextlib.suppress(Exception):
                    await bus.ack(stream, entry_id)

    async def _graph_metrics_loop(self) -> None:
        assert self.ctx is not None
        while not self.stop.is_set():
            try:
                if self.ctx.graph is not None:
                    scores = await self.ctx.graph.update_all_graph_metrics()
                    logger.info(f"Graph metrics: {scores}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(f"Graph metrics update failed: {exc}")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=3600.0)

    async def _status_loop(self) -> None:
        assert self.ctx is not None
        while not self.stop.is_set():
            try:
                depths = await self.ctx.bus.depths()
                logger.info(
                    "Streams: " + " ".join(f"{s.rsplit(':', 1)[-1]}={d}" for s, d in depths.items())
                )
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=60.0)

    async def _reap_loop(self) -> None:
        assert self.ctx is not None
        while not self.stop.is_set():
            try:
                reclaimed = await self.ctx.bus.reap_stale()
                if reclaimed:
                    logger.info(f"Reclaimed {reclaimed} stale stream entries")
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=60.0)


async def amain() -> int:
    pipeline = Pipeline()
    await pipeline.start()
    await pipeline.run_forever()
    return 0


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    cfg = get_config()
    problems = cfg.validate()
    for p in problems:
        print(f"[pipeline] config problem: {p}")
    asyncio.run(amain())


if __name__ == "__main__":
    main()
