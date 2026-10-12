#!/usr/bin/env python3
"""Ingest-only loop: radar pipeline supervisor (master + worker processes).

Runs the corpus builder end-to-end from a single invocation: the radar
pipeline (master + workers) discovers, gates, and LLM-matches jobs into
``radar_candidates`` indefinitely. No autofill, no outcome listeners, no
training hooks — application execution and learning live in the web app now
(Steel + Clef).

The loop is self-managing: crashed children are restarted (up to 5 times
each) and a hang-watchdog restarts children that produce no log output for
``LOOP_HANG_MINUTES``. The run stops after ``--max-minutes`` or on Ctrl+C.

Usage:
    uv run python scripts/loop.py
    uv run python scripts/loop.py --radar-workers 4
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

# .env is the source of truth: override any shell-inherited vars so the model
# and budget settings in .env always win.
load_dotenv(override=True)

PROJECT = Path(__file__).resolve().parent.parent  # apps/ingest
REPO = PROJECT.parent.parent  # repo root
LOG_DIR = REPO / "logs"

# Same LLM throttle overrides run.py forces so workers blast through the corpus.
RADAR_ENV_OVERRIDES = {
    # Stay under the provider's real cap (GeneralCompute: 100 RPM / 200K TPM).
    # These are setdefaults so a user's .env can raise them.
    "LLM_QUEUE_RPM": "90",
    "LLM_QUEUE_MAX_IN_FLIGHT": "10",
    "LLM_QUEUE_TPM": "180000",
    "LLM_BUDGET_RADAR_RPM": "60",
    "LLM_BUDGET_RADAR_TPM": "120000",
}

# Hang-watchdog: a child (e.g. the radar-master) that is still alive but has
# produced no log output for this many minutes is treated as STUCK and is
# restarted automatically.
HANG_MINUTES = int(os.environ.get("LOOP_HANG_MINUTES", "6"))


def _last_log_age(log_path: Path) -> float:
    """Age in seconds of the last structured line written to a child's log."""
    try:
        if not log_path.exists():
            return 0.0
        last = ""
        with open(log_path, errors="replace") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last:
            import json as _json
            from datetime import UTC, datetime

            ts = _json.loads(last).get("timestamp")
            if ts:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return (datetime.now(UTC) - dt).total_seconds()
        return time.time() - log_path.stat().st_mtime
    except Exception:
        try:
            return time.time() - log_path.stat().st_mtime
        except OSError:
            return 0.0


async def _status_dashboard() -> str:
    """One-line live corpus status from the DB. Best-effort, never crashes."""
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
                sources = await c.fetchval("SELECT COUNT(*) FROM source_checkpoints")
        finally:
            await store.close()
    except Exception:
        return "[status] corpus state unavailable"
    return f"[status] obs={obs} | cand={cand} | accepted={accepted} | sources={sources}"


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OVERNIGHT_LOOP", "true")
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
        self._stream_thread: Any | None = None
        self.log_path = LOG_DIR / f"{name}.log"

    async def start(self) -> None:
        LOG_DIR.mkdir(exist_ok=True)
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
            mode = "wb" if self.restarts == 0 else "ab"
            with (
                open(LOG_DIR / f"{self.name}.log", mode) as log_file,
                open(LOG_DIR / "loop.log", "ab") as loop_log,
            ):
                for line in self.proc.stdout:
                    sys.stdout.write(f"[{self.name}] {line}")
                    sys.stdout.flush()
                    log_file.write(line.encode())
                    log_file.flush()
                    loop_log.write(line.encode())
                    loop_log.flush()

        thread = threading.Thread(target=_stream_blocking, daemon=True)
        thread.start()
        self._stream_thread = thread

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

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


async def _spawn_radar(children: list[Child], workers: int) -> None:
    env = _base_env()
    env.update(RADAR_ENV_OVERRIDES)
    master = Child(
        "radar-master",
        [sys.executable, "-m", "src.radar.engine.orchestrator"],
        env,
    )
    await master.start()
    children.append(master)
    for idx in range(1, workers + 1):
        w_env = env.copy()
        w_env["HO_WORKER_ONLY"] = "1"
        child = Child(
            f"radar-worker-{idx}",
            [sys.executable, "-m", "src.radar.engine.orchestrator"],
            w_env,
        )
        await child.start()
        children.append(child)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-radar", action="store_true", help="Do not start the radar pipeline")
    parser.add_argument(
        "--radar-workers",
        type=int,
        default=4,
        help="Radar worker procs (in addition to the master)",
    )
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
        if not args.no_radar:
            await _spawn_radar(children, args.radar_workers)
        if not children:
            print("[loop] nothing to run (--no-radar given)")
            return
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
                    age = _last_log_age(child.log_path)
                    if age > HANG_MINUTES * 60:
                        print(
                            f"[loop] {child.name} hung (no output {age:.0f}s); restarting",
                            flush=True,
                        )
                        child.stop()
                        with contextlib.suppress(Exception):
                            await child.wait(timeout=8)
                        if child.restarts >= 5:
                            print(f"[loop] {child.name} hung and exceeded restarts", flush=True)
                            continue
                        child.restarts += 1
                        await child.start()
                        continue
                if not child.is_alive():
                    # Exit code 42 = the radar finished its bounded batch.
                    if (
                        child.name == "radar-master"
                        and child.proc is not None
                        and child.proc.returncode == 42
                    ):
                        print("[loop] radar-master reached its target batch; finishing", flush=True)
                        child.stop()
                        return
                    if child.restarts >= 5:
                        print(f"[loop] {child.name} crashed and exceeded restarts", flush=True)
                        continue
                    child.restarts += 1
                    print(f"[loop] restarting {child.name} (attempt {child.restarts})", flush=True)
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
