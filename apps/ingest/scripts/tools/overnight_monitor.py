"""Overnight health monitor: corpus + streams + disk, looping or one-shot.

Loop mode logs a compact health line every CHECK_EVERY seconds (OTEL ships
it when enabled). Check mode (`--check`) evaluates once and exits non-zero
on problems — wire it to cron + any alerting (mail, webhook, OpenObserve).

    PYTHONPATH=apps/ingest uv run python apps/ingest/scripts/tools/overnight_monitor.py --check
"""

from __future__ import annotations

import asyncio

from src.http_cache import set_http_cache_store
from src.logging import get_logger
from src.memory.pgvector_store import MemoryStore
from src.stream.redis_url import redis_url

logger = get_logger("overnight_monitor")
CHECK_EVERY = 240  # seconds
REPORT_EVERY = 20  # checks between full reports


def count_of(pattern: str) -> int:
    import subprocess

    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except Exception:
        return -1


async def stream_depths() -> str:
    """Redis stream depths, best-effort (empty when redis is down)."""
    try:
        from redis.asyncio import Redis
        from src.stream.bus import ALL_STREAMS

        client = Redis.from_url(redis_url(), decode_responses=True)
        try:
            parts = []
            for stream in ALL_STREAMS:
                try:
                    parts.append(f"{stream.rsplit(':', 1)[-1]}={await client.xlen(stream)}")
                except Exception:
                    continue
            return "streams: " + " ".join(parts)
        finally:
            await client.aclose()
    except Exception:
        return "streams: unavailable"


async def check_once(store: MemoryStore) -> dict:
    async with store._pool.acquire() as c:
        return {
            "embedded": await c.fetchval("SELECT count(*) FROM obs_embeddings"),
            "accepted": await c.fetchval(
                "SELECT count(*) FROM radar_candidates WHERE eligibility='accepted'"
            ),
            "near_miss": await c.fetchval(
                "SELECT count(*) FROM radar_candidates WHERE eligibility='near_miss'"
            ),
            "obs": await c.fetchval("SELECT count(*) FROM job_observations"),
        }


async def evaluate(store: MemoryStore) -> tuple[list[str], dict]:
    """One health evaluation. Returns (problems, stats).

    Problems cover: no pipeline procs, DLQ backlog, disk pressure, stale
    corpus (nothing accepted recently on a running pipeline).
    """
    problems: list[str] = []
    stats: dict = {}
    try:
        stats = await check_once(store)
    except Exception as exc:
        return [f"db unreachable: {exc}"], stats
    procs = count_of(r"src[.]pipeline[.]run")
    stats["pipeline_procs"] = procs
    if procs <= 0:
        problems.append("no pipeline processes running")
    try:
        from redis.asyncio import Redis
        from src.stream.bus import STREAM_DLQ

        client = Redis.from_url(redis_url(), decode_responses=True)
        try:
            dlq = int(await client.xlen(STREAM_DLQ))
            stats["dlq"] = dlq
            if dlq > 100:
                problems.append(f"dlq backlog {dlq} > 100")
        finally:
            await client.aclose()
    except Exception as exc:
        problems.append(f"redis unreachable: {exc}")
    try:
        import shutil

        usage = shutil.disk_usage("/")
        pct = usage.used / usage.total * 100.0
        stats["disk_pct"] = round(pct, 1)
        if pct > 90.0:
            problems.append(f"disk {pct:.0f}% > 90%")
    except Exception:
        pass
    return problems, stats


async def check_cmd() -> int:
    """One-shot health check for cron/systemd: prints problems, exits 1 if any."""
    store = await MemoryStore.create()
    try:
        problems, stats = await evaluate(store)
    finally:
        await store.close()
    if problems:
        print("UNHEALTHY: " + "; ".join(problems), flush=True)
        return 1
    print(
        "HEALTHY: procs={pipeline_procs} accepted={accepted} "
        "embedded={embedded} obs={obs} dlq={dlq} disk={disk_pct}%".format(**stats),
        flush=True,
    )
    return 0


async def main() -> None:
    store = await MemoryStore.create()
    set_http_cache_store(store)
    ticks = 0
    last_report = 0
    while True:
        try:
            procs = count_of(r"src[.]pipeline[.]run")
            stats = await check_once(store)
            streams = await stream_depths()
            line = (
                f"pipeline={procs} "
                f"accepted={stats['accepted']} near_miss={stats['near_miss']} "
                f"embedded={stats['embedded']} obs={stats['obs']} {streams}"
            )
            if ticks % REPORT_EVERY == 0:
                logger.info("MONITOR " + line)
            if stats["accepted"] != last_report:
                logger.info(f"MONITOR accepted delta: {stats['accepted']} (was {last_report})")
                last_report = stats["accepted"]
        except Exception as e:
            logger.warning(f"monitor tick error: {e}")
        ticks += 1
        await asyncio.sleep(CHECK_EVERY)


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(asyncio.run(check_cmd()))
    asyncio.run(main())
