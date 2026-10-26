"""StreamBus: typed Redis-Streams transport between pipeline stages.

Motion, not state: streams carry small routing payloads (urls, hashes, ids)
between always-on consumer groups. Postgres remains the record store.
Backpressure comes from MAXLEN caps on publish plus BLOCK reads on consume;
crash recovery comes from pending-entry autoclaim plus a DLQ after
max_deliveries attempts.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from typing import Any

from src.logging import get_logger

logger = get_logger("stream_bus")

STREAM_DISCOVER = "ho:s:discover"
STREAM_RAW = "ho:s:raw"
STREAM_GATED = "ho:s:gated"
STREAM_EMBED = "ho:s:embed"
STREAM_ENRICH = "ho:s:enrich"
STREAM_DLQ = "ho:s:dlq"

ALL_STREAMS: tuple[str, ...] = (
    STREAM_DISCOVER,
    STREAM_RAW,
    STREAM_GATED,
    STREAM_EMBED,
    STREAM_ENRICH,
    STREAM_DLQ,
)


def group_for(stream: str) -> str:
    """One consumer group per stream: ho:g:<last-segment>."""
    return f"ho:g:{stream.rsplit(':', 1)[-1]}"


@dataclass
class StreamBus:
    """Thin typed wrapper over redis.asyncio stream commands."""

    redis: Any
    maxlen: int = 5000
    block_ms: int = 5000
    claim_idle_ms: int = 300000
    max_deliveries: int = 5
    _consumer: str = field(init=False)

    def __post_init__(self) -> None:
        self._consumer = f"{socket.gethostname()}:{os.getpid()}"

    @property
    def consumer(self) -> str:
        return self._consumer

    async def ensure_groups(self) -> None:
        """Create one group per stream (MKSTREAM so empty streams are fine)."""
        for stream in ALL_STREAMS:
            try:
                await self.redis.xgroup_create(stream, group_for(stream), id="0", mkstream=True)
            except Exception as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        """Append one message, trimming the stream to maxlen (backpressure)."""
        entry_id = await self.redis.xadd(stream, fields, maxlen=self.maxlen, approximate=True)
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    async def read(
        self, stream: str, consumer: str, count: int = 10
    ) -> list[tuple[str, dict[str, str]]]:
        """BLOCK-read the next batch for this consumer; [] when idle."""
        raw = await self.redis.xreadgroup(
            group_for(stream), consumer, {stream: ">"}, count=count, block=self.block_ms
        )
        out: list[tuple[str, dict[str, str]]] = []
        for _stream, messages in raw or []:
            for entry_id, fields in messages:
                eid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                out.append((eid, {str(k): str(v) for k, v in fields.items()}))
        return out

    async def ack(self, stream: str, *entry_ids: str) -> None:
        """Acknowledge processed messages."""
        if entry_ids:
            await self.redis.xack(stream, group_for(stream), *entry_ids)

    async def depth(self, stream: str) -> int:
        """Pending (undelivered + unacked) message count."""
        try:
            return int(await self.redis.xlen(stream))
        except Exception:
            return 0

    async def depths(self) -> dict[str, int]:
        """Depth of every pipeline stream (status dashboards)."""
        return {stream: await self.depth(stream) for stream in ALL_STREAMS}

    async def reap_stale(self) -> int:
        """Autoclaim idle pending entries back to this consumer; DLQ the hopeless.

        Returns the number of entries reclaimed. Entries delivered more than
        max_deliveries times move to the DLQ instead of looping forever.
        """
        reclaimed = 0
        for stream in (STREAM_DISCOVER, STREAM_RAW, STREAM_GATED, STREAM_EMBED, STREAM_ENRICH):
            reclaimed += await self.reap_stream(stream)
        return reclaimed

    async def reap_stream(self, stream: str) -> int:
        """Reap one stream's stale pending entries (see reap_stale)."""
        reclaimed = 0
        group = group_for(stream)
        try:
            pending = await self.redis.xpending_range(stream, group, "-", "+", 100)
        except Exception:
            return 0
        for entry in pending:
            if isinstance(entry, dict):
                entry_id = entry.get("message_id", "")
                deliveries = int(entry.get("times_delivered", 0))
            else:  # redis-py <4 tuple form: (id, consumer, idle, deliveries)
                entry_id, _, _, deliveries = entry
                deliveries = int(deliveries)
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            try:
                if deliveries >= self.max_deliveries:
                    claimed = await self.redis.xautoclaim(
                        stream, group, self._consumer, self.claim_idle_ms, entry_id, count=1
                    )
                    _next, messages = claimed[0], claimed[1]
                    fields = dict(messages[0][1]) if messages else {}
                    await self.publish(
                        STREAM_DLQ,
                        {
                            "origin_stream": stream,
                            "origin_id": str(entry_id),
                            "error": f"delivered {deliveries}x without ack",
                            **{str(k): str(v) for k, v in fields.items()},
                        },
                    )
                    await self.redis.xack(stream, group, entry_id)
                else:
                    await self.redis.xautoclaim(
                        stream, group, self._consumer, self.claim_idle_ms, entry_id, count=1
                    )
                reclaimed += 1
            except Exception:
                continue
        return reclaimed
