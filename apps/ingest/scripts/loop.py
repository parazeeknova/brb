#!/usr/bin/env python3
"""Pipeline supervisor: N identical stream-pipeline processes, forever.

Each child runs ``python -m src.pipeline.run`` (all stages as Redis-Streams
consumer groups, so processes coordinate without any master). No log files:
children stream stdout straight through with a ``[name]`` prefix and the
watchdog tracks in-memory output timestamps instead of file mtimes.

Usage:
    uv run python scripts/loop.py
    uv run python scripts/loop.py --procs 2
    uv run python scripts/loop.py --max-minutes 240
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # apps/ingest (src.*)

from dotenv import load_dotenv
from src.stream.redis_url import redis_url  # noqa: E402

# .env is the source of truth: override any shell-inherited vars so the model
# and budget settings in .env always win.
load_dotenv(override=True)

PROJECT = Path(__file__).resolve().parent.parent  # apps/ingest
REPO = PROJECT.parent.parent  # repo root

# Silence watchdog: a child that is alive but emits nothing for this long is
# treated as STUCK and restarted (BLOCK-parked consumers still log status).
HANG_MINUTES = int(os.environ.get("LOOP_HANG_MINUTES", "6"))


async def _status_dashboard() -> str:
    """One-line corpus + stream status. Best-effort, never crashes."""
    parts: list[str] = []
    try:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            async with store._pool.acquire() as c:
                obs = await c.fetchval("SELECT COUNT(*) FROM job_observations")
                cand = await c.fetchval("SELECT COUNT(*) FROM radar_candidates")
                accepted = await c.fetchval(
                    "SELECT COUNT(*) FROM radar_candidates WHERE eligibility='accepted'"
                )
        finally:
            await store.close()
        parts.append(f"obs={obs} | cand={cand} | accepted={accepted}")
    except Exception:
        parts.append("corpus unavailable")
    try:
        from redis.asyncio import Redis
        from src.stream.bus import ALL_STREAMS

        client = Redis.from_url(redis_url(), decode_responses=True)
        try:
            depths = {s.rsplit(":", 1)[-1]: await client.xlen(s) for s in ALL_STREAMS}
            parts.append("streams: " + " ".join(f"{k}={v}" for k, v in depths.items()))
        finally:
            await client.aclose()
    except Exception:
        pass
    return "[status] " + " | ".join(parts)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Corpus runs never prompt: resume/persona grounding is env-only.
    env.setdefault("HO_NON_INTERACTIVE", "1")
    _paths = [str(PROJECT)]
    if env.get("PYTHONPATH"):
        _paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(_paths)
    return env


class Child:
    def __init__(self, name: str, argv: list[str], env: dict[str, str]) -> None:
        self.name = name
        self.argv = argv
        self.env = env
        self.proc: subprocess.Popen[str] | None = None
        self.restarts = 0
        self.next_retry = 0.0
        self.last_output = time.monotonic()

    async def start(self) -> None:
        # start_new_session: each child is a session leader with its own process
        # group (pgid == pid). A terminal Ctrl+C therefore only reaches loop.py,
        # never the children — loop.py is the single owner of child cleanup.
        self.proc = subprocess.Popen(
            self.argv,
            cwd=str(PROJECT),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        print(f"[loop] started {self.name} (pid {self.proc.pid})", flush=True)

        def _stream_blocking() -> None:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                self.last_output = time.monotonic()
                if line.strip():
                    sys.stdout.write(f"[{self.name}] {line}")
                    sys.stdout.flush()

        thread = threading.Thread(target=_stream_blocking, daemon=True)
        thread.start()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def output_age(self) -> float:
        return time.monotonic() - self.last_output

    def stop(self, sig: int = signal.SIGINT) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
                print(f"[loop] sent interrupt to {self.name}", flush=True)
            except (ProcessLookupError, PermissionError):  # fmt: skip
                pass

    async def wait(self, timeout: float = 45.0) -> None:
        if self.proc is not None:
            try:
                await asyncio.to_thread(self.proc.wait, timeout)
            except Exception:
                with contextlib.suppress(Exception):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                await asyncio.to_thread(self.proc.wait)


async def _spawn_pipelines(children: list[Child], procs: int) -> None:
    env = _base_env()
    for idx in range(1, procs + 1):
        child = Child(
            f"pipeline-{idx}",
            [sys.executable, "-m", "src.pipeline.run"],
            env.copy(),
        )
        await child.start()
        children.append(child)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--procs", type=int, default=2, help="Identical pipeline processes to run")
    parser.add_argument("--max-minutes", type=int, default=0, help="Hard stop after N minutes")
    args = parser.parse_args()

    children: list[Child] = []
    started_at = time.monotonic()
    stop_evt = asyncio.Event()

    _sig_state = {"interrupts": 0}

    def _on_signal(signum: int, frame: Any) -> None:
        _sig_state["interrupts"] += 1
        if _sig_state["interrupts"] > 1:
            print("[loop] second interrupt; force-killing children", flush=True)
            for child in children:
                with contextlib.suppress(Exception):
                    if child.proc is not None and child.proc.poll() is None:
                        os.killpg(child.proc.pid, signal.SIGKILL)
            os._exit(130)
        print("[loop] interrupt received; shutting down...", flush=True)
        loop.call_soon_threadsafe(stop_evt.set)

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _on_signal, signal.SIGINT, None)
        loop.add_signal_handler(signal.SIGTERM, _on_signal, signal.SIGTERM, None)
    except (NotImplementedError, RuntimeError):  # fmt: skip
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        await _spawn_pipelines(children, args.procs)
    except Exception as exc:
        print(f"[loop] failed to start children: {exc}")
        for child in children:
            child.stop()
        return

    try:
        while True:
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=60)
                print("[loop] interrupted; shutting down...", flush=True)
                break
            except TimeoutError:
                pass

            for child in children:
                if child.is_alive():
                    age = child.output_age()
                    if age > HANG_MINUTES * 60:
                        print(
                            f"[loop] {child.name} silent {age:.0f}s; restarting",
                            flush=True,
                        )
                        child.stop()
                        with contextlib.suppress(Exception):
                            await child.wait(timeout=8)
                        child.restarts += 1
                        await child.start()
                        continue
                if not child.is_alive():
                    # No restart cap: overnight runs must self-heal forever.
                    # Per-child backoff (to 5min) so a flapping child neither
                    # hot-spins nor pauses supervision of healthy siblings.
                    now = time.monotonic()
                    if now < child.next_retry:
                        continue
                    child.restarts += 1
                    backoff = min(300.0, 5.0 * (2.0 ** min(child.restarts, 6)))
                    child.next_retry = now + backoff
                    print(
                        f"[loop] restarting {child.name} "
                        f"(attempt {child.restarts}, backoff {backoff:.0f}s)",
                        flush=True,
                    )
                    await child.start()

            print(await _status_dashboard(), flush=True)

            if args.max_minutes and (time.monotonic() - started_at) / 60 >= args.max_minutes:
                print("[loop] --max-minutes reached; finishing", flush=True)
                break
    except KeyboardInterrupt:
        print("[loop] interrupted; shutting down...", flush=True)
    finally:
        for child in children:
            child.stop()
        await asyncio.gather(*(child.wait(timeout=12) for child in children))
        print("[loop] done.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
