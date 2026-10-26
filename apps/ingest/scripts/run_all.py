#!/usr/bin/env python3
"""One-command ingest runner: infra + radar corpus builder.

Everything brb offers, from a single invocation:

  1. docker compose up the ingest stack (searxng, neo4j, agent-memory-db) and
     wait for health;
  2. run the end-to-end loop: radar pipeline (master + workers) discovers,
     gates, and LLM-matches jobs into the corpus indefinitely.
     Crashed children are restarted; the run continues until stopped.

Application execution and learning live in the web app now (Steel + Clef).

Embeddings are served by an external provider configured through EMBED_URL /
EMBED_MODEL; there is no local embedding server to start.

Local-only by default: company discovery uses the local adapters (yc, dealroom,
hn, remoteok, ...), not the Azure relic. Set AZURE=1 to re-enable relic discovery.

Page rendering is in-process: static pages are fetched with httpx + markitdown,
and JS-only pages are rendered on demand with a lazily-spawned Playwright
browser (torn down after each use) — no Firecrawl api/playwright-service/queue
services, no resident browser.

Usage:
    uv run python scripts/run_all.py            # full stack, foreground
    uv run python scripts/run_all.py --dry-run  # check infra only, no pipeline
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent  # apps/ingest
REPO = PROJECT.parent.parent  # repo root
COMPOSE = REPO / "docker" / "docker-compose.yml"

DOCKER_SERVICES = [
    "searxng",
    "neo4j",
    "agent-memory-db",
    "redis",
]

# Infra readiness probes (host, port).
HOST_PROBES = {
    "searxng": (8080, 15),
    "neo4j": (7687, 15),
    "agent-memory-db": (5443, 20),
    "redis": (6380, 15),
}


def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        import urllib.request

        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "brb/run_all"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


async def _wait_for(name: str, timeout: float) -> bool:
    print(f"[brb] waiting for {name}...", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if name == "searxng" and _http_ok("http://localhost:8080/"):
            return True
        probe = HOST_PROBES.get(name)
        if probe and _port_open("localhost", probe[0]):
            return True
        await asyncio.sleep(1.0)
    return False


def _docker(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), *args],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT),
        )
        return r.returncode, (r.stdout or "")[-2000:] + (r.stderr or "")[-2000:]
    except Exception as e:
        return -1, str(e)


def _compose_up() -> bool:
    print("[brb] starting docker services...", flush=True)
    code, out = _docker(["up", "-d", *DOCKER_SERVICES])
    if code != 0:
        print(f"[brb] docker compose up failed: {out}", flush=True)
        return False
    return True


async def _ensure_infra() -> bool:
    if not _compose_up():
        return False
    ok = True
    for name in ("agent-memory-db", "neo4j", "searxng", "redis"):
        if not await _wait_for(name, HOST_PROBES.get(name, (0, 15))[1]):
            print(f"[brb] WARNING: {name} not ready", flush=True)
            ok = False
        else:
            print(f"[brb] ✓ {name} ready", flush=True)
    return ok


def _memory_status() -> str:
    """Human-readable memory status: persona present, resume indexed, summary
    freshness vs the current resume source. Returns a status string."""
    import json as _json

    persona = REPO / "data" / "persona.json"
    if not persona.exists():
        return "NO persona.json — run `bun run init-memory` first"
    try:
        data = _json.loads(persona.read_text())
    except Exception:
        return "persona.json unreadable"
    answers = len(data.get("answers", []))
    summary = str(data.get("resume_summary") or "")
    # Freshness probe: if the summary lacks the projects this repo's resume.tex
    # carries, it was built before the latest resume and the matcher grounding
    # is stale. (Only advisory — the resume may legitimately differ.)
    fresh = True
    for marker in ("Asocialmedia", "Verso", "Chorus", "Lumen", "asocialmedia"):
        if marker in summary:
            break
    else:
        if summary and "Singularity" not in summary:
            fresh = False
    parts = [f"persona: {answers} answers"]
    if summary:
        parts.append(f"resume_summary: {len(summary)} chars")
    else:
        parts.append("resume_summary: MISSING")
    if not fresh:
        parts.append("⚠ resume_summary may be STALE (missing latest projects)")
    return "; ".join(parts)


def _persona_missing(persona_path: Path) -> list[str]:
    """Critical persona items that are missing/blank: core answer categories
    and identity contact fields. Empty list = complete."""
    import json as _json

    try:
        data = _json.loads(persona_path.read_text())
    except Exception:
        return ["persona.json unreadable"]
    missing: list[str] = []
    answered = {(a.get("category") or "").strip() for a in data.get("answers", [])}
    core = {
        "current_location",
        "work_model",
        "relocation",
        "nationality",
        "work_authorization",
        "visa_sponsorship",
        "expected_compensation",
        "education",
    }
    for cat in core:
        if cat not in answered:
            missing.append(f"answer: {cat}")
    identity = data.get("identity") or {}
    for field in ("firstName", "lastName", "email", "phone", "linkedin", "github"):
        if not (identity.get(field) or "").strip():
            missing.append(f"identity: {field}")
    return missing


def _ensure_memory() -> None:
    """Advisory persona check: per-user onboarding (web app) owns memory now.

    The single-user persona.json flow is gone. Matching still uses the legacy
    CANDIDATE_PERSONA env/file grounding until the web API serves personas.
    """
    persona = REPO / "data" / "persona.json"
    if not persona.exists():
        print("[brb] no data/persona.json — matching uses CANDIDATE_PERSONA env", flush=True)
        return
    print(f"[brb] memory: {_memory_status()}", flush=True)


async def _check_embeds() -> bool:
    """Ping the embedding provider once before spawning workers.

    Semantic matching/RAG cannot run without vectors; fail fast with a clear
    message instead of letting every worker die on its first embed call.
    """
    sys.path.insert(0, str(PROJECT))
    try:
        from src.llm.embed_client import embed_one
    except Exception as e:
        print(f"[brb] embeddings: client import failed ({e}); aborting", flush=True)
        return False
    try:
        vec = await embed_one("connectivity check")
    except Exception as e:
        print(f"[brb] embeddings: request failed ({e}); aborting", flush=True)
        return False
    if not vec:
        print("[brb] embeddings unreachable — matching is dead without vectors.", flush=True)
        print("[brb] fix: set GEMINI_API_KEY and enable billing for Gemini API", flush=True)
        return False
    model = os.environ.get("EMBED_MODEL", "?")
    print(f"[brb] embeddings: ok ({len(vec)}d via {model})", flush=True)
    return True


async def _run_loop(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    paths = [str(PROJECT)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("OVERNIGHT_LOOP", "true")
    # Force local discovery: the user runs everything locally, no Azure relic.
    # Explicitly override any inherited DISCOVERY_SOURCE (e.g. none from an
    # earlier shell export) so the local adapters always run.
    env["DISCOVERY_SOURCE"] = "all"

    cmd = [
        sys.executable,
        str(PROJECT / "scripts" / "loop.py"),
        "--procs",
        str(args.procs),
    ]
    if args.max_minutes:
        cmd += ["--max-minutes", str(args.max_minutes)]
    print(f"[brb] launching loop: {' '.join(cmd)}", flush=True)
    # start_new_session: loop.py becomes a session leader so a terminal
    # Ctrl+C (foreground process group) never reaches it directly. run_all
    # stays the single owner of loop.py's lifecycle and tears the whole
    # tree down in the finally below. Output streams to the console only;
    # structured history lives in OpenObserve, not log files.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROJECT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )

    async def _tee() -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            sys.stdout.write(chunk.decode(errors="replace"))
            sys.stdout.flush()

    tee_task = asyncio.create_task(_tee())
    try:
        rc = await proc.wait()
    except asyncio.CancelledError:
        rc = 130
        raise
    finally:
        # Whatever exits us (Ctrl+C, crash, normal finish), never strand
        # the pipeline: TERM the loop's whole group, give it time to run
        # its own child cleanup, then KILL whatever is left and reap any
        # surviving pattern processes as a final safety net.
        with contextlib.suppress(Exception):
            if proc.returncode is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except TimeoutError:
                    with contextlib.suppress(Exception):
                        os.killpg(proc.pid, signal.SIGKILL)
                    with contextlib.suppress(Exception):
                        await proc.wait()
        _reap_pipeline_orphans(sig="KILL", grace_s=1.0)
        await tee_task
    return rc


def _handle_sig(signum: int, frame) -> None:  # noqa: ANN001
    import contextlib

    with contextlib.suppress(Exception):
        print(f"\n[brb] signal {signum}; shutting down...", flush=True)
    raise KeyboardInterrupt


def _status_report(watch: bool = False) -> int:
    """`bun run run --status`: a full read-only snapshot of every counter the
    pipeline tracks — DB, graph, RAG, streams, sources, and whether anything
    is currently running. No side effects: does not touch containers."""
    import asyncio
    import os as _os
    from typing import Any

    # Quiet the pipeline loggers (MemoryStore emits INFO on open/close).
    _os.environ["LOG_LEVEL"] = "WARNING"

    async def _pg_section() -> dict[str, Any]:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            async with store._pool.acquire() as c:
                obs = await c.fetchval("SELECT COUNT(*) FROM job_observations")
                cand = await c.fetchval("SELECT COUNT(*) FROM radar_candidates")
                sources = await c.fetchval("SELECT COUNT(*) FROM source_checkpoints")
                sources_active = await c.fetchval(
                    "SELECT COUNT(*) FROM source_checkpoints WHERE active"
                )
                sources_polled = await c.fetchval(
                    "SELECT COUNT(*) FROM source_checkpoints WHERE last_polled IS NOT NULL"
                )
                events = await c.fetchval("SELECT COUNT(*) FROM decision_events")
                rewards = await c.fetchval(
                    "SELECT COUNT(*) FROM decision_events WHERE reward IS NOT NULL"
                )
                verified = await c.fetchval("SELECT COUNT(*) FROM job_observations WHERE verified")
                founders = await c.fetchval(
                    "SELECT COUNT(*) FROM radar_candidates WHERE founders IS NOT NULL "
                    "AND founders::text != '[]'"
                )
                funded = await c.fetchval(
                    "SELECT COUNT(*) FROM radar_candidates WHERE funding_stage IS NOT NULL "
                    "AND funding_stage != ''"
                )
                imp = await c.fetchval("SELECT COUNT(*) FROM impressions")
                outcomes = await c.fetchval("SELECT COUNT(*) FROM unattributed_outcomes")
                frontier = await c.fetchval(
                    "SELECT COUNT(*) FROM job_observations WHERE last_seen > "
                    "(extract(epoch from now()) - 86400)"
                )
                discovered = await c.fetchval(
                    "SELECT COUNT(*) FROM job_observations WHERE source LIKE '%searxng%' "
                    "OR source LIKE '%github%' OR source LIKE '%discovered%'"
                )
                model = await c.fetchrow(
                    "SELECT version, status FROM model_registry "
                    "WHERE status='active' ORDER BY created_at DESC LIMIT 1"
                )
                return {
                    "obs": obs,
                    "cand": cand,
                    "sources": sources,
                    "sources_active": sources_active,
                    "sources_polled": sources_polled,
                    "events": events,
                    "rewards": rewards,
                    "verified": verified,
                    "founders": founders,
                    "funded": funded,
                    "impressions": imp,
                    "outcomes": outcomes,
                    "frontier": frontier,
                    "discovered": discovered,
                    "model": f"{model['version']}({model['status']})"
                    if model
                    else "rule_v1 (heuristic baseline)",
                }
        finally:
            await store.close()

    async def _eligibility_section() -> dict[str, int]:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            async with store._pool.acquire() as c:
                rows = await c.fetch(
                    "SELECT eligibility, COUNT(*) AS n FROM radar_candidates GROUP BY eligibility"
                )
                return {str(r["eligibility"]): r["n"] for r in rows}
        finally:
            await store.close()

    async def _rag_section() -> dict[str, int]:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            resume = await store.chunk_count()
            persona = await store.persona_chunk_count()
            async with store._pool.acquire() as c:
                obs_emb = await c.fetchval("SELECT COUNT(*) FROM obs_embeddings")
                embed_cache = await c.fetchval("SELECT COUNT(*) FROM embed_cache")
                render_cache = await c.fetchval("SELECT COUNT(*) FROM render_cache")
            return {
                "resume_chunks": resume,
                "persona_chunks": persona,
                "obs_embeddings": obs_emb,
                "embed_cache": embed_cache,
                "render_cache": render_cache,
            }
        finally:
            await store.close()

    async def _graph_section() -> str:
        try:
            from src.graph.graph_store import GraphStore

            g = await GraphStore.create()
            try:
                nodes = await g.node_count()
                rels = await g.relationship_count()
            finally:
                await g.close()
            return f"nodes={nodes} rels={rels}"
        except Exception:
            return "graph unavailable"

    async def _top_sources() -> list[tuple[str, int]]:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            async with store._pool.acquire() as c:
                rows = await c.fetch(
                    "SELECT source, COUNT(*) AS n FROM radar_candidates "
                    "GROUP BY source ORDER BY n DESC LIMIT 12"
                )
                return [(str(r["source"]), r["n"]) for r in rows]
        finally:
            await store.close()

    async def _rates_section() -> dict[str, Any]:
        from src.memory.pgvector_store import MemoryStore

        store = await MemoryStore.create()
        try:
            async with store._pool.acquire() as c:
                url_discovery_15m = await c.fetchval(
                    "SELECT COALESCE(SUM(item_count), 0) FROM pipeline_stage_events "
                    "WHERE stage = 'url_discovery' "
                    "AND created_at > (now() - interval '15 minutes')"
                )
                obs_15m = await c.fetchval(
                    "SELECT COUNT(*) FROM job_observations WHERE last_seen > "
                    "(extract(epoch from now()) - 900)"
                )
                cand_15m = await c.fetchval(
                    "SELECT COUNT(*) FROM radar_candidates WHERE updated_at > "
                    "(now() - interval '15 minutes')"
                )
            return {
                "url_discovery_rate": round((url_discovery_15m or 0) / 15.0, 1),
                "url_discovery_total_15m": url_discovery_15m or 0,
                "obs_rate": round((obs_15m or 0) / 15.0, 1),
                "obs_total_15m": obs_15m or 0,
                "cand_rate": round((cand_15m or 0) / 15.0, 1),
                "cand_total_15m": cand_15m or 0,
            }
        finally:
            await store.close()

    async def _streams_section() -> dict[str, int]:
        try:
            from redis.asyncio import Redis
            from src.stream.bus import ALL_STREAMS
            from src.stream.redis_url import redis_url

            client = Redis.from_url(redis_url(), decode_responses=True)
            try:
                return {s.rsplit(":", 1)[-1]: int(await client.xlen(s)) for s in ALL_STREAMS}
            finally:
                await client.aclose()
        except Exception:
            return {}

    async def _collect_all_stats() -> dict[str, Any]:
        rates, pg, elig, rag, graph, top, streams = await asyncio.gather(
            _rates_section(),
            _pg_section(),
            _eligibility_section(),
            _rag_section(),
            _graph_section(),
            _top_sources(),
            _streams_section(),
        )
        running = _pipeline_running()
        return {
            "rates": rates,
            "pg": pg,
            "elig": elig,
            "rag": rag,
            "graph": graph,
            "top": top,
            "streams": streams,
            "running": running,
        }

    def _render(stats: dict[str, Any]) -> Any:
        from rich.console import Group
        from rich.table import Table

        running = stats["running"]
        pid_str = f"RUNNING (PID {running})" if running else "STOPPED"
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        # Header
        t_hdr = Table(box=None, show_header=False, expand=True, padding=(0, 0))
        t_hdr.add_column("title", style="bold italic cyan", justify="left")
        t_hdr.add_column("time", style="dim", justify="right")
        t_hdr.add_row(f"BRB AGENT PIPELINE STATUS  ·  {pid_str}", now_str)

        # 1. Rates Table
        rates = stats["rates"]
        t_rates = Table(
            title="LIVE PROCESS RATES (/min)",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_rates.add_column("Process Pipeline Stage", style="cyan", justify="left")
        t_rates.add_column("Current Rate", style="bold white", justify="right")
        t_rates.add_column("Window Total", style="dim", justify="right")
        t_rates.add_row(
            "URL Discovery (urls/min)",
            f"{rates['url_discovery_rate']} / min",
            f"{rates['url_discovery_total_15m']:,} URLs (15m)",
        )
        t_rates.add_row(
            "Job Intake (obs/min)",
            f"{rates['obs_rate']} / min",
            f"{rates['obs_total_15m']:,} obs (15m)",
        )
        t_rates.add_row(
            "Candidate Gating (cand/min)",
            f"{rates['cand_rate']} / min",
            f"{rates['cand_total_15m']:,} cand (15m)",
        )

        # 2. Postgres DB & Ingestion
        pg = stats["pg"]
        t_ingest = Table(
            title="POSTGRES DB AND DISCOVERY",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_ingest.add_column("Metric", style="cyan", justify="left", no_wrap=True)
        t_ingest.add_column("Count", style="bold white", justify="right")
        t_ingest.add_column("Details / Status", style="dim", justify="right")
        t_ingest.add_row("Raw Observations (obs)", f"{pg.get('obs', 0):,}", "Ingested raw job URLs")
        t_ingest.add_row(
            "Canonical Candidates (cand)", f"{pg.get('cand', 0):,}", "Normalized postings"
        )
        t_ingest.add_row(
            "Active Company Sources",
            f"{pg.get('sources_active', 0):,}",
            f"Polled: {pg.get('sources_polled', 0):,}",
        )
        t_ingest.add_row("24h Queue Frontier", f"{pg.get('frontier', 0):,}", "Observed in last 24h")
        t_ingest.add_row(
            "Dynamic Discovered", f"{pg.get('discovered', 0):,}", "SearXNG / GitHub / YC feeds"
        )
        t_ingest.add_row(
            "Verified Observations",
            f"{pg.get('verified', 0):,}",
            "Proven real postings (ATS API / SubQ)",
        )
        t_ingest.add_row(
            "Candidates w/ Founders / Funding",
            f"{pg.get('founders', 0):,} / {pg.get('funded', 0):,}",
            "Enrichment coverage",
        )
        t_ingest.add_row(
            "Decision Events / Impressions",
            f"{pg.get('events', 0):,} / {pg.get('impressions', 0):,}",
            f"Rewards: {pg.get('rewards', 0):,}",
        )
        t_ingest.add_row(
            "Active Model Ranker", str(pg.get("model", "none")), "Candidate scoring model"
        )

        # 3. Eligibility Breakdown
        elig = stats["elig"]
        total_elig = sum(elig.values()) or 1
        acc = elig.get("accepted", 0)
        nm = elig.get("near_miss", 0)
        rej = elig.get("rejected", 0)
        err = elig.get("error", 0)

        t_elig = Table(
            title="CANDIDATE ELIGIBILITY BREAKDOWN",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_elig.add_column("Eligibility Filter State", style="cyan", justify="left", no_wrap=True)
        t_elig.add_column("Candidate Count", style="bold white", justify="right")
        t_elig.add_column("Share Percent", style="bold", justify="right")
        t_elig.add_row("Accepted (High Fit)", f"{acc:,}", f"{acc / total_elig * 100:.1f}%")
        t_elig.add_row("Near Miss", f"{nm:,}", f"{nm / total_elig * 100:.1f}%")
        t_elig.add_row("Rejected", f"{rej:,}", f"{rej / total_elig * 100:.1f}%")
        if err:
            t_elig.add_row("Error", f"{err:,}", f"{err / total_elig * 100:.1f}%")

        # 4. Stream depths (pipeline motion)
        streams = stats["streams"]
        t_streams = Table(
            title="STREAM DEPTHS (undelivered + unacked)",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_streams.add_column("Stream", style="cyan", justify="left", no_wrap=True)
        t_streams.add_column("Depth", style="bold white", justify="right")
        for name in ("discover", "raw", "gated", "embed", "dlq"):
            t_streams.add_row(name, f"{streams.get(name, 0):,}")

        # 5. RAG Memory & Graph
        rag = stats["rag"]
        graph = stats["graph"]
        t_rag = Table(
            title="RAG VECTOR MEMORY AND GRAPH DATABASE",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_rag.add_column("Subsystem Metric", style="cyan", justify="left", no_wrap=True)
        t_rag.add_column("Count / Details", style="bold white", justify="right")
        t_rag.add_row("Resume Vector Chunks", f"{rag.get('resume_chunks', 0):,}")
        t_rag.add_row("Persona Vector Chunks", f"{rag.get('persona_chunks', 0):,}")
        t_rag.add_row("Embed Cache Entries", f"{rag.get('embed_cache', 0):,}")
        t_rag.add_row("Page Render Cache Entries", f"{rag.get('render_cache', 0):,}")
        t_rag.add_row("Neo4j Graph Database Counts", graph)

        # 6. Top Sources Table
        t_top = Table(
            title="TOP ATS DISCOVERY SOURCES",
            title_style="bold italic cyan",
            title_justify="left",
            box=None,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 2),
        )
        t_top.add_column(
            "Source Platform and Board Slug", style="cyan", justify="left", no_wrap=True
        )
        t_top.add_column("Gated Candidates", style="bold white", justify="right")
        for src, n in stats["top"][:10]:
            t_top.add_row(src, f"{n:,}")

        return Group(t_hdr, t_rates, t_ingest, t_elig, t_streams, t_rag, t_top)

    async def _live_loop() -> int:
        from rich.console import Console
        from rich.live import Live

        console = Console()
        if watch:
            console.print(
                "[bold dim]Entering live status dashboard (Press Ctrl+C to exit)...[/bold dim]\n"
            )
            try:
                with Live(console=console, refresh_per_second=1, screen=False) as live:
                    while True:
                        stats = await _collect_all_stats()
                        live.update(_render(stats))
                        await asyncio.sleep(1.5)
            except (KeyboardInterrupt, asyncio.CancelledError):  # fmt: skip
                console.print("\n[dim]Status monitor exited.[/dim]")
                return 0
        else:
            stats = await _collect_all_stats()
            console.print(_render(stats))
            return 0

    return asyncio.run(_live_loop())


def _reap_pipeline_orphans(sig: str = "KILL", grace_s: float = 1.0) -> None:
    """Kill every leftover pipeline process (loop, radar).

    Reaps processes whose parent is dead (orphans) without touching our own
    process or the terminal foreground group that hosts us. ``sig`` is applied
    after a ``grace_s`` SIGINT pass so graceful handlers get a chance first.
    """
    import subprocess as _sp

    patterns = (
        "scripts/loop.py",
        "src.pipeline.run",
    )
    own_pgid = os.getpgid(os.getpid())

    def _sig(signal_name: str) -> None:
        seen: set[int] = set()
        for pat in patterns:
            with contextlib.suppress(Exception):
                r = _sp.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
                for pid in r.stdout.split():
                    try:
                        pid_i = int(pid)
                        if pid_i in seen or pid_i == os.getpid():
                            continue
                        # Never signal our own terminal group: that contains
                        # the `uv`/`bun` wrapper which would forward the
                        # signal straight back into us.
                        if os.getpgid(pid_i) == own_pgid:
                            continue
                        seen.add(pid_i)
                        os.kill(pid_i, getattr(signal, "SIG" + signal_name))
                    except (ValueError, ProcessLookupError):  # fmt: skip
                        pass

    _sig("INT")
    time.sleep(grace_s)
    _sig(sig)


def _pipeline_running() -> int | None:
    """Return the loop.py pid if the pipeline is running, else None."""
    import subprocess as _sp

    try:
        r = _sp.run(
            ["pgrep", "-f", "scripts/loop.py"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = [int(p) for p in (r.stdout or "").split() if p.isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


async def _system_stats() -> tuple[str, str, str, str, str]:
    """Startup snapshot of DB, graph, RAG, and stream status.

    Returns (pg, graph, rag, events, notice) human-readable status strings.
    """
    import asyncio as _asyncio

    async def _pg() -> str:
        try:
            from src.memory.pgvector_store import MemoryStore

            store = await MemoryStore.create()
            try:
                async with store._pool.acquire() as c:
                    obs = await c.fetchval("SELECT COUNT(*) FROM job_observations")
                    cand = await c.fetchval("SELECT COUNT(*) FROM radar_candidates")
                    acc = await c.fetchval(
                        "SELECT COUNT(*) FROM radar_candidates WHERE eligibility='accepted'"
                    )
                    events = await c.fetchval("SELECT COUNT(*) FROM decision_events")
                    rewards = await c.fetchval(
                        "SELECT COUNT(*) FROM decision_events WHERE reward IS NOT NULL"
                    )
                    model = await c.fetchrow(
                        "SELECT version, status FROM model_registry "
                        "WHERE status='active' ORDER BY created_at DESC LIMIT 1"
                    )
                bits = [f"obs={obs}", f"cand={cand}", f"accepted={acc}"]
                bits.append(f"events={events}")
                bits.append(f"rewards={rewards}")
                if model:
                    bits.append(f"model={model['version']}({model['status']})")
                return " | ".join(bits)
            finally:
                await store.close()
        except Exception:
            return "pg unavailable"

    async def _graph() -> str:
        try:
            from src.graph.graph_store import GraphStore

            g = await GraphStore.create()
            try:
                nodes = await g.node_count()
                rels = await g.relationship_count()
            finally:
                await g.close()
            return f"nodes={nodes} rels={rels}"
        except Exception:
            return "graph unavailable"

    async def _rag() -> str:
        try:
            from src.memory.pgvector_store import MemoryStore

            store = await MemoryStore.create()
            try:
                resume = await store.chunk_count()
                persona = await store.persona_chunk_count()
            finally:
                await store.close()
            return f"resume_chunks={resume} persona_chunks={persona}"
        except Exception:
            return "rag unavailable"

    async def _ml() -> str:
        try:
            from src.memory.pgvector_store import MemoryStore

            store = await MemoryStore.create()
            try:
                async with store._pool.acquire() as c:
                    imp = await c.fetchval("SELECT COUNT(*) FROM impressions")
                    outcomes = await c.fetchval("SELECT COUNT(*) FROM unattributed_outcomes")
            finally:
                await store.close()
            bits = [f"impressions={imp}"]
            if outcomes:
                bits.append(f"outcomes={outcomes}")
            return " | ".join(bits)
        except Exception:
            return "ml unavailable"

    async def _discord() -> str:
        return "removed (web app owns UX)"

    async def _all() -> tuple[str, str, str, str, str]:
        return await _asyncio.gather(_pg(), _graph(), _rag(), _ml(), _discord())

    return await _all()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="Print all pipeline counters and exit")
    ap.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Continuously watch status updates in real-time dashboard",
    )
    ap.add_argument(
        "--once", action="store_true", help="Print status snapshot once and exit (no live watch)"
    )
    ap.add_argument("--dry-run", action="store_true", help="Start infra only, then stop")
    ap.add_argument(
        "--no-infra",
        action="store_true",
        help="Skip compose management (infra is externally managed, e.g. pipeline container)",
    )
    ap.add_argument(
        "--procs",
        type=int,
        default=2,
        help="Identical pipeline processes to run",
    )
    ap.add_argument("--max-minutes", type=int, default=0, help="Hard stop after N minutes")
    args = ap.parse_args()

    # Read-only status: no lock, no takeover, no infra — display dashboard.
    if args.status or args.watch:
        import sys as _sys

        is_watch = args.watch or (_sys.stdout.isatty() and not args.once)
        return _status_report(watch=is_watch)

    # Single-instance lock: bind a loopback port instead of a lock file
    # (no local log files anymore; history lives in OpenObserve).
    import socket as _socket

    _lock_sock = _socket.socket()
    try:
        _lock_sock.bind(("127.0.0.1", 53921))
    except OSError:
        print("[brb] another run owns the pipeline; reaping strays and taking over", flush=True)
    # A previous crashed run may have leaked children: reap orphans so
    # `bun run run` always starts one clean pipeline.
    _reap_pipeline_orphans(sig="KILL", grace_s=2.0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    async def _run() -> int:
        if not args.no_infra:
            if not await _ensure_infra():
                print("[brb] infra failed; aborting", flush=True)
                return 1
            # Autoheal: if containers exist but are Exited, restart them
            _autoheal_containers()
        if not await _check_embeds():
            return 1
        _ensure_memory()
        # Startup snapshot: DB / graph / RAG / events.
        pg, graph, rag, ml, disc = await _system_stats()
        print(f"[brb] db: {pg}", flush=True)
        print(f"[brb] graph: {graph}", flush=True)
        print(f"[brb] rag: {rag}", flush=True)
        print(f"[brb] ml: {ml}", flush=True)
        print(f"[brb] discord: {disc}", flush=True)
        print(
            f"[brb] pipeline config: procs={args.procs}; stops on --max-minutes / Ctrl+C",
            flush=True,
        )
        if args.dry_run:
            print("[brb] dry-run complete; infra is up", flush=True)
            return 0
        return await _run_loop(args)

    import asyncio.base_events

    if not hasattr(asyncio.base_events.BaseEventLoop, "_safe_is_closed"):

        def _safe_is_closed(self: object) -> bool:
            return getattr(self, "_closed", True)

        asyncio.base_events.BaseEventLoop.is_closed = _safe_is_closed

    try:
        rc = asyncio.run(_run())
        return rc
    except KeyboardInterrupt:
        print("[brb] stopped.", flush=True)
        return 0
    finally:
        # Release the loopback-port lock so the next `bun run run` can bind.
        with contextlib.suppress(Exception):
            _lock_sock.close()


def _autoheal_containers() -> None:
    import subprocess as _sp

    for name in (
        "brb-searxng",
        "brb-agent-memory-db",
        "brb-neo4j",
        "brb-redis",
    ):
        try:
            r = _sp.run(
                ["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            status = (r.stdout or "").strip().split()[0] if r.stdout else "missing"
            if status == "Exited":
                print(f"[brb] autoheal: restarting {name} (was Exited)", flush=True)
                _sp.run(["docker", "start", name], capture_output=True, timeout=15)
            elif status == "missing":
                print(f"[brb] autoheal: {name} missing — compose up", flush=True)
                svc = name.removeprefix("brb-")
                _sp.run(
                    ["docker", "compose", "-f", str(COMPOSE), "up", "-d", svc],
                    capture_output=True,
                    timeout=60,
                )
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
