"""Tests for TinyFish clients (mocked transport) + SubQ decisions (mocked)."""

from __future__ import annotations

from typing import Any

import pytest

from src.llm import subq
from src.radar.sources import tinyfish_fetch, tinyfish_search


def test_build_queries_covers_spectrum() -> None:
    queries = tinyfish_search.build_queries()
    assert len(queries) == len(tinyfish_search.ROLES) * len(tinyfish_search.LEVELS) * len(
        tinyfish_search.GEOS
    )
    blob = "\n".join(queries)
    for token in ("senior", "junior", "designer", "data scientist", "manager", "remote"):
        assert token in blob


class FakeResp:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, resp: FakeResp) -> None:
        self.resp = resp
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.resp

    async def post(self, url: str, json: Any = None, headers: dict | None = None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.resp


@pytest.mark.asyncio
async def test_search_page_parses_and_sends_key() -> None:
    client = FakeClient(
        FakeResp(
            200,
            {"results": [{"title": "T", "url": "https://jobs.lever.co/a/1", "snippet": "S"}]},
        )
    )
    out = await tinyfish_search.search_page(client, "KEY", "backend jobs", page=2)
    assert out == [{"title": "T", "url": "https://jobs.lever.co/a/1", "snippet": "S"}]
    assert client.calls[0]["headers"] == {"X-API-Key": "KEY"}
    assert client.calls[0]["params"]["page"] == 2


@pytest.mark.asyncio
async def test_search_page_drops_bad_and_non200() -> None:
    client = FakeClient(FakeResp(200, {"results": [{"title": "T", "url": "junk"}]}))
    assert await tinyfish_search.search_page(client, "K", "q") == []
    bad = FakeClient(FakeResp(429, {}))
    assert await tinyfish_search.search_page(bad, "K", "q") == []


@pytest.mark.asyncio
async def test_fetch_pages_batch_shape() -> None:
    client = FakeClient(
        FakeResp(
            200,
            {
                "results": [
                    {"url": "https://a/1", "title": "T", "text": "# Job\n" + "x" * 100},
                    {"url": "https://a/2", "title": "", "text": ""},
                ],
                "errors": [],
            },
        )
    )
    out = await tinyfish_fetch.fetch_pages(client, "K", ["https://a/1", "https://a/2"])
    assert set(out) == {"https://a/1"}
    assert out["https://a/1"]["markdown"].startswith("# Job")


def test_noul_probability_shapes() -> None:
    assert subq.noul_probability({"real": {"type": "noul", "noul": 0.82}}, "real") == 0.82
    assert subq.noul_probability({}, "real") is None
    assert subq.noul_probability({"real": {"type": "choice"}}, "real") is None


@pytest.mark.asyncio
async def test_subq_decide_posts_systemone(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url: str, json: Any = None, headers: dict | None = None):
            seen.update({"url": url, "json": json, "headers": headers})
            return FakeResp(200, {"answers": {"real": {"type": "noul", "noul": 0.9}}, "usage": {}})

    monkeypatch.setattr("src.llm.subq.httpx.AsyncClient", lambda **k: Client())
    monkeypatch.setenv("SUBQ_API_KEY", "test-key")
    subq._disabled_until = 0.0
    answers = await subq.decide("state", {"real": {"type": "noul", "instructions": "?"}})
    assert answers == {"real": {"type": "noul", "noul": 0.9}}
    assert seen["url"].endswith("/v1/systemone")
    assert "Bearer test-key" in seen["headers"]["Authorization"]
    assert subq.noul_probability(answers, "real") == 0.9


@pytest.mark.asyncio
async def test_subq_402_trips_breaker(monkeypatch) -> None:
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url: str, json: Any = None, headers: dict | None = None):
            return FakeResp(402, {"error": "credits"})

    monkeypatch.setattr("src.llm.subq.httpx.AsyncClient", lambda **k: Client())
    monkeypatch.setenv("SUBQ_API_KEY", "test-key")
    subq._disabled_until = 0.0
    try:
        assert await subq.decide("s", {}) == {}
        assert subq.is_available() is False
    finally:
        subq._disabled_until = 0.0


@pytest.mark.asyncio
async def test_is_real_posting_threshold(monkeypatch) -> None:
    async def fake_decide(state: str, questions: dict, timeout: float = 20.0):
        return {"real": {"type": "noul", "noul": 0.95}}

    monkeypatch.setattr("src.llm.subq.decide", fake_decide)
    assert await subq.is_real_posting("Engineer", "Acme", "x" * 500) == 0.95
    # thin pages never spend budget
    assert await subq.is_real_posting("E", "A", "tiny") is None
