"""Overnight health monitor: checks the radar pipeline + Azure ingest every N
seconds and logs a compact health line. Does NOT fix anything; it's the eyes
for the night shift. Run detached::

    setsid nohup env PYTHONPATH=$PWD \\
        uv run python3 scripts/overnight_monitor.py > logs/monitor.out 2>&1 &
"""

from __future__ import annotations

import asyncio

from src.http_cache import set_http_cache_store
from src.logging import get_logger
from src.memory.pgvector_store import MemoryStore

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

        client = Redis.from_url("redis://127.0.0.1:6380/0", decode_responses=True)
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
    asyncio.run(main())
