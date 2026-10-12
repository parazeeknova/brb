"""Fetch routing + verification tests (fakes, no network)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.pipeline import fetch as fetch_stage
from src.pipeline import normalize as normalize_stage
from src.radar.core.models import EligibilityState, JobCandidate, JobObservation


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []
        self.redis = None

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        self.published.append((stream, fields))
        return "1-0"


class FakeStore:
    def __init__(self) -> None:
        self.verified_updates: list[tuple[str, str]] = []
        self.candidates: list[dict[str, Any]] = []
        self.rejected: list[str] = []

    async def record_pipeline_stage_event(self, stage: str, count: int) -> None:
        return None

    async def set_observation_verified(self, url_hash: str, method: str) -> None:
        self.verified_updates.append((url_hash, method))

    async def upsert_radar_candidate(self, data: dict[str, Any]) -> None:
        self.candidates.append(data)

    async def fetch_observation_rows(self, hashes: list[str]):
        return []


class Ctx:
    def __init__(self, store=None, bus=None) -> None:
        self.store = store or FakeStore()
        self.bus = bus or FakeBus()
        self.graph = None
        self.dedup = None
        from src.pipeline.ctx import KnownState

        self.known = KnownState()


def test_ats_url_routes_direct_and_verified(monkeypatch) -> None:
    async def fake_fetch_ats(url: str, client: Any):
        return JobObservation(
            url=url,
            source="greenhouse:acme",
            raw_markdown="# Eng\n" + "x" * 500,
            title="Engineer",
            extra={"company_slug": "acme", "verified": True, "verification_method": "ats_api"},
        )

    monkeypatch.setattr("src.radar.sources.ats_direct.fetch_ats_job", fake_fetch_ats)
    ctx = Ctx()
    asyncio.run(
        fetch_stage.handle_discover(
            ctx, {"url": "https://boards.greenhouse.io/acme/1", "source": "t"}
        )
    )
    assert len(ctx.bus.published) == 1
    assert ctx.bus.published[0][0] == "ho:s:raw"


def test_short_page_without_fallback_drops() -> None:
    async def go() -> None:
        from unittest.mock import patch

        with patch("src.render.markdownify", return_value="tiny"):
            ctx = Ctx()
            # no TINY_FISH_API_KEY in test env path -> fallback skipped
            import os

            prev = os.environ.pop("TINY_FISH_API_KEY", None)
            try:
                await fetch_stage.handle_discover(
                    ctx, {"url": "https://example.com/j/1", "source": "t"}
                )
                return ctx
            finally:
                if prev is not None:
                    os.environ["TINY_FISH_API_KEY"] = prev

    ctx = asyncio.run(go())
    assert ctx.bus.published == []


def test_normalize_verified_row_skips_subq(monkeypatch) -> None:
    store = FakeStore()

    async def _rows_verified(hashes=None):
        return [
            {
                "url": "https://x",
                "source": "greenhouse:acme",
                "title": "Engineer",
                "snippet": "",
                "raw_json": {"markdown": "# Engineer\n" + "x" * 500},
                "verified": True,
                "verification_method": "ats_api",
            }
        ]

    async def boom(ctx: Any, obs: Any) -> bool:
        raise AssertionError("SubQ must not run for verified rows")

    async def _fetch_rows(hashes):
        return await _rows_verified()

    store.fetch_observation_rows = _fetch_rows  # type: ignore[method-assign]
    monkeypatch.setattr("src.pipeline.normalize.verify_posting", boom)
    monkeypatch.setattr("src.pipeline.normalize.run_gates", _accepting_gates("https://x"))
    ctx = Ctx(store=store)
    asyncio.run(normalize_stage.handle_raw(ctx, {"url_hash": "h"}))
    assert len(store.candidates) == 1
    assert store.verified_updates == []


def _accepting_gates(url: str):
    async def fake_gates(o, hashes, last_seen):
        c = JobCandidate(
            canonical_id="h",
            source=o.source,
            direct_apply_url=url,
            normalized_company="Acme",
            normalized_role="Engineer",
            normalized_location="Remote",
        )
        c.eligibility = EligibilityState.ACCEPTED
        return c, []

    return fake_gates


def test_normalize_unverified_subq_pass_marks_verified(monkeypatch) -> None:
    store = FakeStore()

    async def _rows():
        return [
            {
                "url": "https://x",
                "source": "s",
                "title": "Engineer",
                "snippet": "",
                "raw_json": {"markdown": "# Engineer\n" + "x" * 500},
                "verified": False,
                "verification_method": "",
            }
        ]

    async def _fetch_rows(hashes):
        return await _rows()

    store.fetch_observation_rows = _fetch_rows  # type: ignore[method-assign]

    async def fake_verify(ctx: Any, obs: Any) -> bool:
        return True

    monkeypatch.setattr("src.pipeline.normalize.verify_posting", fake_verify)
    monkeypatch.setattr("src.pipeline.normalize.run_gates", _accepting_gates("https://x"))
    ctx = Ctx(store=store)
    asyncio.run(normalize_stage.handle_raw(ctx, {"url_hash": "h"}))
    assert len(store.verified_updates) == 1
    assert store.verified_updates[0][1] == "subq"
    assert len(store.candidates) == 1


def test_normalize_unverified_subq_fail_rejects(monkeypatch) -> None:
    store = FakeStore()

    async def _rows():
        return [
            {
                "url": "https://x",
                "source": "s",
                "title": "Engineer",
                "snippet": "",
                "raw_json": {"markdown": "# Engineer\n" + "x" * 500},
                "verified": False,
                "verification_method": "",
            }
        ]

    async def _fetch_rows(hashes):
        return await _rows()

    store.fetch_observation_rows = _fetch_rows  # type: ignore[method-assign]

    async def fake_verify(ctx: Any, obs: Any) -> bool:
        return False

    async def fake_reject(store: Any, obs: Any, pid: str, rej: Any) -> None:
        store.rejected.append(pid)

    monkeypatch.setattr("src.pipeline.normalize.verify_posting", fake_verify)
    monkeypatch.setattr("src.pipeline.normalize.persist_rejected", fake_reject)
    ctx = Ctx(store=store)
    asyncio.run(normalize_stage.handle_raw(ctx, {"url_hash": "h"}))
    assert len(store.rejected) == 1
    assert store.candidates == []
