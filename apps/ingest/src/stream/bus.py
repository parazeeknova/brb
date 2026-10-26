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
            await self.compact_completed(stream)

    async def compact_completed(self, stream: str) -> None:
        """Remove old acknowledged history below every group's safe cursor."""
        if stream in (STREAM_GATED, STREAM_DLQ):
            return
        groups = await self.redis.xinfo_groups(stream)
        floors = []
        for group in groups:
            pending = await self.redis.xpending(stream, group["name"])
            floor = pending.get("min")
            if not floor:
                ms, seq = group["last-delivered-id"].split("-")
                floor = f"{ms}-{int(seq) + 1}"
            floors.append(tuple(map(int, floor.split("-"))))
        if floors:
            ms, seq = min(floors)
            await self.redis.xtrim(stream, minid=f"{ms}-{seq}", approximate=False)

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        """Append work without trimming unfinished messages.

        Only gated notifications (whose records already live in Postgres) have
        bounded history. Discovery pauses at the configured backlog threshold;
        completed work is removed by ack instead of evicting queued work.
        """
        if stream == STREAM_GATED:
            entry_id = await self.redis.xadd(stream, fields, maxlen=self.maxlen, approximate=True)
        else:
            entry_id = await self.redis.xadd(stream, fields)
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
            # Each work stream has one consumer group. Delete only completed
            # messages, never pending or not-yet-delivered work.
            await self.redis.xdel(stream, *entry_ids)

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
            # Reclaiming the oldest pending entry can expose acknowledged
            # history from older builds. Remove it before measuring backlog.
            await self.compact_completed(stream)
        return reclaimed

    async def _requeue(self, stream: str, entry_id: str, fields: dict, deliveries: int) -> None:
        payload = {str(k): str(v) for k, v in fields.items()}
        if deliveries >= self.max_deliveries:
            await self.publish(
                STREAM_DLQ,
                {
                    **payload,
                    "origin_stream": stream,
                    "origin_id": entry_id,
                    "error": f"delivered {deliveries}x without ack",
                },
            )
        else:
            payload["_brb_deliveries"] = str(deliveries)
            await self.publish(stream, payload)
        # Publish first: interruption here can duplicate work, but cannot erase
        # it. Handlers use idempotent database writes for at-least-once delivery.
        await self.ack(stream, entry_id)

    async def reap_stream(self, stream: str) -> int:
        """Requeue stale pending work for normal > readers, or retain it in DLQ."""
        reclaimed = 0
        group = group_for(stream)
        pending = await self.redis.xpending_range(stream, group, "-", "+", 100)
        for entry in pending:
            entry_id = str(entry["message_id"])
            claimed = await self.redis.xclaim(
                stream, group, self._consumer, self.claim_idle_ms, [entry_id]
            )
            if not claimed:
                continue
            _, fields = claimed[0]
            deliveries = int(entry["times_delivered"]) + int(fields.get("_brb_deliveries", "0"))
            await self._requeue(stream, entry_id, fields, deliveries)
            reclaimed += 1
        return reclaimed

    async def release_consumer(self, stream: str, consumer: str) -> int:
        """Hand off one stopped consumer's unacknowledged messages immediately."""
        released = 0
        group = group_for(stream)
        while pending := await self.redis.xpending_range(
            stream, group, "-", "+", 100, consumername=consumer
        ):
            for entry in pending:
                entry_id = str(entry["message_id"])
                claimed = await self.redis.xclaim(stream, group, self._consumer, 0, [entry_id])
                if claimed:
                    _, fields = claimed[0]
                    # Deployments are not processing failures, so do not spend
                    # a retry just because an active handler was interrupted.
                    await self._requeue(
                        stream, entry_id, fields, int(fields.get("_brb_deliveries", "0"))
                    )
                    released += 1
        return released
