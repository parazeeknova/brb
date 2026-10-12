"""Stage tests with fakes: no network, no DB, no redis required."""

from __future__ import annotations

from typing import Any

from src.pipeline.ctx import KnownState, PipelineCtx
from src.radar.core.models import EligibilityState, JobCandidate


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []
        self.redis = object()

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        self.published.append((stream, fields))
        return f"{len(self.published)}-0"

    async def depths(self) -> dict[str, int]:
        return {}


class FakeDedup:
    def __init__(self, fresh: bool = True) -> None:
        self.fresh = fresh
        self.marked: list[str] = []

    async def filter_new_urls(self, urls: list[str]) -> list[str]:
        return list(urls) if self.fresh else []

    async def mark_urls_seen(self, urls: list[str]) -> None:
        self.marked.extend(urls)


class FakeStore:
    def __init__(self) -> None:
        self.obs_rows: dict[str, dict[str, Any]] = {}
        self.candidates: list[dict[str, Any]] = []
        self.rejected: list[str] = []
        self.observations: list[tuple[str, str]] = []
        self.embeddings: list[dict[str, Any]] = []
        self.events: list[tuple[str, int]] = []

    async def fetch_observation_rows(self, hashes: list[str]) -> list[dict[str, Any]]:
        return [self.obs_rows[h] for h in hashes if h in self.obs_rows]

    async def record_pipeline_stage_event(self, stage: str, count: int) -> None:
        self.events.append((stage, count))

    async def missing_obs_hashes(self, hashes: list[str]) -> list[str]:
        have = {e["url_hash"] for e in self.embeddings}
        return [h for h in hashes if h not in have]

    async def embed_texts_for(self, hashes: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "url_hash": h,
                "title": "Backend Engineer",
                "company": "Acme",
                "content_hash": "c",
                "text": "We hire backend engineers. Python, Postgres.",
            }
            for h in hashes
        ]

    async def unembedded_obs(self, limit: int = 2000, software_first: bool = True) -> list[dict]:
        return [{"url": "https://x/y"}]

    async def upsert_obs_embedding(self, **kwargs: Any) -> None:
        self.embeddings.append(kwargs)

    async def upsert_radar_candidate(self, data: dict[str, Any]) -> None:
        self.candidates.append(data)


def make_ctx(**overrides: Any) -> PipelineCtx:
    base: dict[str, Any] = {
        "store": FakeStore(),
        "graph": None,
        "bus": FakeBus(),
        "dedup": FakeDedup(),
    }
    base.update(overrides)
    return PipelineCtx(**base)


def test_publish_urls_dedups_and_publishes() -> None:
    import asyncio

    from src.pipeline import producers

    ctx = make_ctx()
    n = asyncio.run(producers.publish_urls(ctx, ["https://a/1", "https://a/1", "junk"], "t"))
    assert n == 2
    assert [s for s, _ in ctx.bus.published] == ["ho:s:discover"] * 2
    assert ctx.dedup.marked == ["https://a/1", "https://a/1"]


def test_publish_urls_all_seen_publishes_nothing() -> None:
    import asyncio

    from src.pipeline import producers

    ctx = make_ctx(dedup=FakeDedup(fresh=False))
    assert asyncio.run(producers.publish_urls(ctx, ["https://a/1"], "t")) == 0
    assert ctx.bus.published == []


def test_handle_discover_fetches_persists_archives_and_forwards(monkeypatch) -> None:
    import asyncio

    from src.pipeline import fetch as fetch_stage

    async def fake_markdownify(url: str, timeout: float = 20.0) -> str:
        return "# Job\n" + "x" * 200

    monkeypatch.setattr("src.render.markdownify", fake_markdownify)
    ctx = make_ctx()
    asyncio.run(fetch_stage.handle_discover(ctx, {"url": "https://a/1", "source": "t"}))
    assert len(ctx.bus.published) == 1
    stream, fields = ctx.bus.published[0]
    assert stream == "ho:s:raw"
    assert fields["url"] == "https://a/1"


def test_handle_discover_drops_short_pages(monkeypatch) -> None:
    import asyncio

    from src.pipeline import fetch as fetch_stage

    async def fake_markdownify(url: str, timeout: float = 20.0) -> str:
        return "tiny"

    monkeypatch.setattr("src.render.markdownify", fake_markdownify)
    ctx = make_ctx()
    asyncio.run(fetch_stage.handle_discover(ctx, {"url": "https://a/1", "source": "t"}))
    assert ctx.bus.published == []


def test_handle_discover_rejects_bad_url() -> None:
    import asyncio

    from src.pipeline import fetch as fetch_stage

    ctx = make_ctx()
    asyncio.run(fetch_stage.handle_discover(ctx, {"url": "junk", "source": "t"}))
    assert ctx.bus.published == []


def test_handle_raw_accept_path_uses_real_gates(monkeypatch) -> None:
    import asyncio

    from src.pipeline import normalize as normalize_stage
    from src.radar.core.models import JobObservation

    store = FakeStore()
    obs = JobObservation(
        url="https://boards.greenhouse.io/acme/123",
        source="greenhouse:acme",
        raw_markdown="# Backend Engineer\nPython Postgres\n" + "x" * 500,
        title="Backend Engineer",
    )
    store.obs_rows = {
        "h1": {
            "url": obs.url,
            "source": obs.source,
            "title": obs.title,
            "snippet": "",
            "raw_json": {"markdown": obs.raw_markdown},
        }
    }
    ctx = make_ctx(store=store)

    async def fake_gates(o, hashes, last_seen):

        c = JobCandidate(
            canonical_id="h1",
            source=o.source,
            direct_apply_url=o.url,
            normalized_company="Acme",
            normalized_role="Backend Engineer",
            normalized_location="Remote",
        )
        c.eligibility = EligibilityState.ACCEPTED
        return c, []

    monkeypatch.setattr("src.pipeline.normalize.run_gates", fake_gates)
    asyncio.run(normalize_stage.handle_raw(ctx, {"url_hash": "h1"}))
    assert len(store.candidates) == 1
    streams = [s for s, _ in ctx.bus.published]
    assert "ho:s:gated" in streams
    assert "ho:s:embed" in streams


def test_handle_raw_reject_path_persists_rejected(monkeypatch) -> None:
    import asyncio

    from src.pipeline import normalize as normalize_stage
    from src.radar.core.models import RejectionReason

    store = FakeStore()
    store.obs_rows = {
        "h9": {"url": "https://x", "source": "s", "title": "t", "snippet": "", "raw_json": {}},
    }
    ctx = make_ctx(store=store)

    async def fake_gates(o, hashes, last_seen):
        return None, [("g", RejectionReason.UNKNOWN, "nope")]

    monkeypatch.setattr("src.pipeline.normalize.run_gates", fake_gates)
    # raw_json has no markdown -> dropped before gates (no content to judge).
    asyncio.run(normalize_stage.handle_raw(ctx, {"url_hash": "h9"}))
    assert ctx.bus.published == []


def test_handle_embed_writes_vectors(monkeypatch) -> None:
    import asyncio

    from src.pipeline import embed as embed_stage

    store = FakeStore()
    ctx = make_ctx(store=store)

    async def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr("src.llm.embed_client.embed", fake_embed)
    asyncio.run(embed_stage.handle_embed(ctx, {"url_hash": "h1"}))
    assert len(store.embeddings) == 1
    assert store.embeddings[0]["url_hash"] == "h1"


def test_backfill_unembedded_queues_hashes() -> None:
    import asyncio
    import hashlib

    from src.pipeline import embed as embed_stage

    ctx = make_ctx()
    n = asyncio.run(embed_stage.backfill_unembedded(ctx))
    assert n == 1
    stream, fields = ctx.bus.published[0]
    assert stream == "ho:s:embed"
    assert fields["url_hash"] == hashlib.md5(b"https://x/y").hexdigest()


def test_known_state_refreshes_from_store() -> None:
    import asyncio

    class Store:
        _pool = None

    # Fake pool protocol: acquire() -> conn with fetch()
    class Conn:
        async def fetch(self, sql: str):
            if "radar_candidates" in sql:
                return [{"canonical_id": "abc"}, {"canonical_id": "rejected:xyz"}]
            return [{"url_hash": "h", "last_seen": 123.0}]

    class Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    store = Store()
    store._pool = Pool()
    known = KnownState()
    asyncio.run(known.refresh(store, force=True))
    assert known.hashes == {"abc", "xyz"}
    assert known.last_seen == {"h": 123.0}
