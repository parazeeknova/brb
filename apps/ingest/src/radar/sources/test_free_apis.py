"""Free JSON API producer tests (mocked HTTP, fake ctx)."""

from __future__ import annotations

from typing import Any

from src.radar.sources import free_apis


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []
        self.redis = None

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        self.published.append((stream, fields))
        return "1-0"


class FakeDedup:
    async def filter_new_urls(self, urls: list[str]) -> list[str]:
        return list(urls)

    async def mark_urls_seen(self, urls: list[str]) -> None:
        return None


class FakeStore:
    async def record_pipeline_stage_event(self, stage: str, count: int) -> None:
        return None


class Ctx:
    def __init__(self) -> None:
        from src.pipeline.ctx import PipelineCtx

        self._ctx = PipelineCtx(store=FakeStore(), graph=None, bus=FakeBus(), dedup=FakeDedup())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)


class FakeResp:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    async def get(self, url: str, params: Any = None, headers: Any = None):
        return FakeResp(self.status, self.payload)

    async def post(self, url: str, json: Any = None):
        return FakeResp(self.status, self.payload)


def test_arbeitnow_tick_persists_and_publishes(monkeypatch) -> None:
    import asyncio

    import src.radar.sources.free_apis as fa

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url: str):
            return FakeResp(
                200,
                {
                    "data": [
                        {
                            "slug": "backend-1",
                            "company_name": "Acme",
                            "title": "Backend Engineer",
                            "description": "<p>Build.</p>" + "x" * 300,
                            "url": "https://www.arbeitnow.com/jobs/companies/acme/backend-1",
                            "location": "Berlin",
                        }
                    ]
                },
            )

    monkeypatch.setattr(fa.httpx, "AsyncClient", lambda **k: Client())
    ctx = Ctx()
    assert asyncio.run(fa.arbeitnow_tick(ctx)) == 1
    assert ctx.bus.published and ctx.bus.published[0][0] == "ho:s:raw"


def test_remoteok_skips_legal_notice() -> None:
    obs = free_apis._remoteok_to_obs({"last_updated": 1, "legal": "terms"})
    assert obs is None
    obs = free_apis._remoteok_to_obs(
        {
            "position": "Designer",
            "url": "https://remoteOK.com/remote-jobs/x-designer-1",
            "company": "X",
            "description": "<p>Design.</p>" + "y" * 300,
        }
    )
    assert obs is not None
    assert obs.extra["verified"] is True


def test_hn_comment_parsing() -> None:
    obs = free_apis._hn_comment_to_obs(
        {
            "id": 1,
            "text": "Acme Corp | Senior Engineer | Remote\nWe build things. Apply https://acme.com/jobs/1",
        }
    )
    assert obs is not None
    assert obs.url == "https://acme.com/jobs/1"
    assert "verified" not in obs.extra or obs.extra.get("verified") is not True
    assert free_apis._hn_comment_to_obs({"id": 2, "text": "short"}) is None


def test_usajobs_skipped_without_key(monkeypatch) -> None:
    import asyncio

    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)
    monkeypatch.delenv("USAJOBS_EMAIL", raising=False)
    assert asyncio.run(free_apis.usajobs_tick(Ctx())) == 0


def test_tiering_accepts_unverified_substantive() -> None:
    # covered in pipeline/test_fetch_verify.py; this pins the entry shape
    obs = free_apis._hn_comment_to_obs(
        {"id": 3, "text": "Beta Inc | Data Analyst | NYC\n" + "z" * 500}
    )
    assert obs is not None
    assert obs.extra.get("verified", False) is False
