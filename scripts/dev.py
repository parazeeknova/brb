"""Local dev orchestrator: infra + web + ingest with colored logs.

Replaces scripts/dev.mjs. Loads .env.development, then .env (secrets win);
real environment variables win over both. Preflights docker compose
(starts missing services, waits for TCP health), then spawns the web
frontend and the ingest pipeline side by side with color-coded prefixes.
Ctrl+C stops everything.

Telemetry: children inherit OTLP exporter env pointing at the local
OpenObserve service, so both apps ship logs/traces there with zero code
changes once their SDK bridges land.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import signal
import socket
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.text import Text

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker" / "docker-compose.yml"
DEV_DEFAULTS = ROOT / ".env.development"
DEV_SECRETS = ROOT / ".env"

console = Console()

# service -> (host port or None for host-networked, container name fragment)
TCP_CHECKS: tuple[tuple[int, str], ...] = (
    (8080, "searxng"),
    (5443, "agent-memory-db"),
    (6380, "redis"),
    (7474, "neo4j"),
    (5090, "openobserve"),
)
EXPECTED_SERVICES: tuple[str, ...] = (
    "searxng",
    "torproxy",
    "agent-memory-db",
    "redis",
    "neo4j",
    "openobserve",
)
TAG_STYLES: dict[str, str] = {
    "dev": "bold yellow",
    "infra": "bold green",
    "web": "bold cyan",
    "ingest": "bold magenta",
    "otel": "bold blue",
    "loop": "green",
    "radar-master": "bold yellow",
}

# Cycle for radar-worker-N and any future grandchildren.
WORKER_STYLES: tuple[str, ...] = (
    "bold green",
    "bold blue",
    "bold red",
    "bold white",
    "green",
    "blue",
)

_CHILD_PREFIX = re.compile(r"^\[([A-Za-z0-9_.-]+)\]\s?(.*)$")

HEALTH_TIMEOUT_S = 120.0
POLL_S = 2.0


@dataclass(frozen=True)
class ChildSpec:
    """How to spawn one dev child process."""

    tag: str
    argv: tuple[str, ...]


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=value dotenv file (quotes stripped, # comments skipped)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#") or "=" not in trimmed:
            continue
        key, _, value = trimmed.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def merge_env() -> dict[str, str]:
    """Layer .env.development < .env < real environment (shell wins)."""
    return {**parse_env_file(DEV_DEFAULTS), **parse_env_file(DEV_SECRETS), **os.environ}


def otel_headers(env: dict[str, str]) -> str:
    """OTLP Basic-auth header value derived from OpenObserve root creds."""
    email = env.get("ZO_ROOT_USER_EMAIL", "root@example.com")
    password = env.get("ZO_ROOT_USER_PASSWORD", "Complexpass#123")
    token = base64.b64encode(f"{email}:{password}".encode()).decode()
    return f"Authorization=Basic {token}"


def build_child_env(base: dict[str, str]) -> dict[str, str]:
    """Child env: dev layering + runtime defaults (never overrides explicit)."""
    env = dict(base)
    env.setdefault("NODE_ENV", "development")
    paths = [".", "apps/ingest"]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    # Local OpenObserve (default org `default`); SDKs append /v1/logs etc.
    env.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:5090/api/default")
    env.setdefault("OTEL_EXPORTER_OTLP_HEADERS", otel_headers(env))
    env.setdefault("OTEL_SERVICE_NAME", "brb")
    return env


def tcp_open(port: int, timeout: float = 2.0) -> bool:
    """True when something accepts TCP on 127.0.0.1:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def missing_services(expected: Sequence[str], running: Sequence[str]) -> list[str]:
    """Expected services with no running container."""
    return [s for s in expected if s not in running]


def parse_compose_ps(payload: str) -> list[str]:
    """Service names of running containers from `docker compose ps --format json`.

    Handles real docker (one object per line) and podman-compose (one array
    with podman-style keys) output.
    """
    import json

    text = payload.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        containers = parsed if isinstance(parsed, list) else [parsed]
    except ValueError:  # single object failed -> try JSON-lines
        containers = [json.loads(line) for line in text.splitlines() if line.strip()]
    running: list[str] = []
    for container in containers:
        state = str(container.get("State", container.get("state", ""))).lower()
        if state != "running":
            continue
        service = (
            container.get("Service")
            or container.get("service")
            or container.get("Labels", {}).get("com.docker.compose.service", "")
        )
        if service:
            running.append(service)
    return running


def compose(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `docker compose -f docker/docker-compose.yml ...` in the repo root."""
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def style_for(name: str, fallback_tag: str) -> str:
    """Deterministic color for a log source.

    Known services use TAG_STYLES; radar workers cycle WORKER_STYLES by
    trailing index (worker-1 -> first color); anything else falls back to
    the parent child's tag style.
    """
    if name in TAG_STYLES:
        return TAG_STYLES[name]
    worker = re.fullmatch(r"radar-worker-(\d+)", name)
    if worker:
        return WORKER_STYLES[(int(worker.group(1)) - 1) % len(WORKER_STYLES)]
    return TAG_STYLES.get(fallback_tag, "white")


def split_child_prefix(line: str) -> tuple[str | None, str]:
    """Split loop.py's `[child-name] rest` prefix; (None, line) when absent."""
    match = _CHILD_PREFIX.match(line)
    if not match:
        return None, line
    return match.group(1), match.group(2)


def format_line(tag: str, message: str) -> Text:
    """One line: colored `[source]` chip + plain message (no markup parsing).

    Grandchild lines forwarded by loop.py (`[radar-worker-1] ...`) are
    re-tagged to their real source so every worker has its own color.
    """
    child, rest = split_child_prefix(message)
    if child is not None:
        tag, message = child, rest
    out = Text()
    out.append(f"[{tag}] ", style=style_for(tag, tag))
    out.append(message)
    return out


def log(tag: str, message: str, *, err: bool = False) -> None:
    """Single color-coded line (stderr only on errors)."""
    console.print(format_line(tag, message), highlight=False, soft_wrap=True)


async def preflight(env: dict[str, str]) -> None:
    """Start missing compose services, then wait until all TCP ports answer."""
    result = compose(["ps", "--format", "json"], env)
    running = parse_compose_ps(result.stdout) if result.returncode == 0 else []
    missing = missing_services(EXPECTED_SERVICES, running)
    if missing:
        log("infra", f"starting: {', '.join(missing)}")
        up = compose(["up", "-d", *missing], env)
        if up.returncode != 0:
            raise RuntimeError(f"docker compose up failed: {(up.stderr or '').strip()}")
    else:
        log("infra", "all containers already running, checking health")
    deadline = asyncio.get_running_loop().time() + HEALTH_TIMEOUT_S
    while True:
        result = compose(["ps", "--format", "json"], env)
        running = parse_compose_ps(result.stdout) if result.returncode == 0 else []
        down = missing_services(EXPECTED_SERVICES, running)
        closed = [name for port, name in TCP_CHECKS if not tcp_open(port)]
        if not down and not closed:
            log("infra", "healthy: :8080 :5443 :6380 :7474 :5090")
            return
        if asyncio.get_running_loop().time() > deadline:
            raise RuntimeError(
                f"infra unhealthy after 120s (down: {down or 'none'}; "
                f"ports closed: {closed or 'none'})"
            )
        await asyncio.sleep(POLL_S)


async def stream_child(spec: ChildSpec, env: dict[str, str]) -> int:
    """Spawn one child, stream its stdout+stderr with a colored prefix."""
    proc = await asyncio.create_subprocess_exec(
        *spec.argv,
        cwd=str(ROOT),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode(errors="replace").rstrip()
        if line.strip():
            log(spec.tag, line)
    return await proc.wait()


async def run_dev(no_web: bool, no_ingest: bool, radar_workers: int, max_minutes: int) -> int:
    """Preflight infra, then supervise web + ingest until one exits/Ctrl+C."""
    env = build_child_env(merge_env())
    await preflight(env)
    specs: list[ChildSpec] = []
    if not no_web:
        specs.append(ChildSpec("web", ("bun", "run", "--filter", "brb-web", "dev")))
    if not no_ingest:
        argv: list[str] = ["uv", "run", "python", "apps/ingest/scripts/run_all.py"]
        if radar_workers != 4:
            argv += ["--radar-workers", str(radar_workers)]
        if max_minutes > 0:
            argv += ["--max-minutes", str(max_minutes)]
        specs.append(ChildSpec("ingest", tuple(argv)))
    if not specs:
        log("dev", "nothing to run (--no-web and --no-ingest both given)")
        return 0
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError, RuntimeError:
            signal.signal(sig, lambda *_: stop.set())
    tasks = [asyncio.create_task(stream_child(spec, env)) for spec in specs]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    codes = [task.result() for task in done]
    failed = any(code not in (0, 130, 143) for code in codes)
    if not stop.is_set() and failed:
        log("dev", "child failed, stopping services", err=True)
    return 1 if failed else 0


app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="brb local dev orchestrator: infra + web + ingest.",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_web: bool = typer.Option(False, "--no-web", help="Skip the web frontend."),
    no_ingest: bool = typer.Option(False, "--no-ingest", help="Skip the ingest pipeline."),
    radar_workers: int = typer.Option(4, "--radar-workers", help="Radar worker procs."),
    max_minutes: int = typer.Option(0, "--max-minutes", help="Hard stop after N minutes."),
) -> None:
    """Boot the full local stack (default when no subcommand is given)."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        code = asyncio.run(run_dev(no_web, no_ingest, radar_workers, max_minutes))
    except RuntimeError as exc:
        log("dev", f"fatal: {exc}", err=True)
        raise typer.Exit(1) from exc
    raise typer.Exit(code)


@app.command()
def infra(
    action: str = typer.Argument("up", help="up | down | ps"),
) -> None:
    """Manage the compose stack without starting apps."""
    env = build_child_env(merge_env())
    if action == "up":
        result = compose(["up", "-d"], env)
    elif action == "down":
        result = compose(["down"], env)
    elif action == "ps":
        result = compose(["ps"], env)
    else:
        log("dev", f"unknown infra action: {action}", err=True)
        raise typer.Exit(2)
    if result.stdout.strip():
        console.print(result.stdout.strip())
    if result.returncode != 0:
        log("dev", (result.stderr or "").strip() or "compose failed", err=True)
        raise typer.Exit(result.returncode)


if __name__ == "__main__":
    app()
