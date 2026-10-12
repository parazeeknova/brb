"""Shared per-process pipeline context: stores, bus, dedup, known-state."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from src.memory.pgvector_store import MemoryStore

KNOWN_TTL_S = 60.0


@dataclass
class KnownState:
    """TTL-cached gate-decision state (replaces per-sweep full-table loads)."""

    hashes: set[str] = field(default_factory=set)
    last_seen: dict[str, float] = field(default_factory=dict)
    refreshed_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def refresh(self, store: MemoryStore, force: bool = False) -> None:
        async with self._lock:
            if not force and time.time() - self.refreshed_at < KNOWN_TTL_S:
                return
            hashes: set[str] = set()
            last_seen: dict[str, float] = {}
            try:
                async with store._pool.acquire() as conn:
                    rows = await conn.fetch("SELECT canonical_id FROM radar_candidates")
                    for r in rows:
                        cid = r["canonical_id"] or ""
                        hashes.add(cid.removeprefix("rejected:"))
                    rows = await conn.fetch("SELECT url_hash, last_seen FROM job_observations")
                    for r in rows:
                        if r["last_seen"]:
                            last_seen[r["url_hash"]] = float(r["last_seen"])
            except Exception:
                pass
            self.hashes = hashes
            self.last_seen = last_seen
            self.refreshed_at = time.time()


@dataclass
class PipelineCtx:
    """Everything stages need; built once per pipeline process."""

    store: Any
    graph: Any | None
    bus: Any
    dedup: Any
    known: KnownState = field(default_factory=KnownState)
