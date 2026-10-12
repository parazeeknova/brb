"""Tests for workday parsing + structured passthrough (mocked HTTP)."""

from __future__ import annotations

from typing import Any

import pytest

from src.radar.sources import workday


def test_parse_workday_url() -> None:
    assert workday.parse_workday_url("https://micron.wd1.myworkdayjobs.com/External/search") == (
        "micron.wd1.myworkdayjobs.com",
        "External",
        "search",
    )
    assert workday.parse_workday_url("https://company.myworkdayjobs.com/en-US/careers") == (
        "company.myworkdayjobs.com",
        "en-US",
        "careers",
    )
    assert workday.parse_workday_url("https://boards.greenhouse.io/acme/1") is None
    assert workday.parse_workday_url("junk") is None


def test_posting_to_obs_verified() -> None:
    obs = workday.posting_to_obs(
        "micron.wd1.myworkdayjobs.com",
        "External",
        "External",
        {
            "title": "Process Engineer",
            "externalPath": "/job/Taichung/Process-Engineer_JR105575-1",
            "locationsText": "Taichung, Taiwan",
        },
    )
    assert obs is not None
    assert obs.title == "Process Engineer"
    assert (
        obs.url == "https://micron.wd1.myworkdayjobs.com/job/Taichung/Process-Engineer_JR105575-1"
    )
    assert obs.extra["verified"] is True
    assert obs.extra["verification_method"] == "workday_api"
    assert obs.extra["req_id"] == "JR105575"


def test_posting_to_obs_rejects_thin() -> None:
    assert workday.posting_to_obs("h", "t", "b", {"title": "", "externalPath": "/x"}) is None
    assert workday.posting_to_obs("h", "t", "b", {"title": "T"}) is None


@pytest.mark.asyncio
async def test_search_board_paginates_and_caps() -> None:
    pages = [
        {
            "total": 250,
            "jobPostings": [{"title": f"E{i}", "externalPath": f"/j/{i}"} for i in range(100)],
        },
        {
            "total": 250,
            "jobPostings": [{"title": f"E{i}", "externalPath": f"/j/{i}"} for i in range(100, 200)],
        },
    ]
    calls: list[dict[str, Any]] = []

    class FakeResp:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self) -> None:
            self.n = 0

        async def post(self, url: str, json: Any = None):
            calls.append(json)
            offset = (json or {}).get("offset", 0)
            if offset >= 200:
                resp = FakeResp({"total": 250, "jobPostings": []})
            else:
                resp = FakeResp(pages[min(self.n, len(pages) - 1)])
            self.n += 1
            return resp

    out = await workday.search_board(FakeClient(), "h", "t", "b", limit=100)
    assert len(out) == 200
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 100


@pytest.mark.asyncio
async def test_live_micron_search_shape() -> None:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            out = await workday.search_board(
                client, "micron.wd1.myworkdayjobs.com", "micron", "External", limit=3
            )
    except Exception:
        pytest.skip("no network")
    if not out:
        pytest.skip("workday empty")
    assert out[0].get("title")
    assert out[0].get("externalPath")
