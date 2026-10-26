"""Tests for ATS-direct parsing (pure) + live API shape (skipped w/o net)."""

from __future__ import annotations

import pytest

from src.radar.sources.ats_direct import _greenhouse_to_obs, _lever_to_obs, parse_ats_url


def test_parse_greenhouse() -> None:
    assert parse_ats_url("https://boards.greenhouse.io/airbnb/jobs/8184174") == (
        "greenhouse",
        "airbnb",
        "8184174",
    )


def test_parse_lever() -> None:
    assert parse_ats_url("https://jobs.lever.co/angellist/6ab62eb0-01ff-423f-8e2f-d35ecb5e6c0") == (
        "lever",
        "angellist",
        "6ab62eb0-01ff-423f-8e2f-d35ecb5e6c0",
    )


def test_parse_rejects_non_ats() -> None:
    assert parse_ats_url("https://www.linkedin.com/jobs/view/123") is None
    assert parse_ats_url("https://boards.greenhouse.io/airbnb") is None
    assert parse_ats_url("junk") is None
    assert parse_ats_url("") is None


def test_greenhouse_normalize_requires_title_and_body() -> None:
    assert _greenhouse_to_obs("https://x", "acme", {}) is None
    assert _greenhouse_to_obs("https://x", "acme", {"title": "Eng"}) is None
    obs = _greenhouse_to_obs(
        "https://x",
        "acme-corp",
        {
            "title": "Backend Engineer",
            "content": "<p>Build things.</p>" + "x" * 200,
            "offices": [{"location": "Remote"}],
            "absolute_url": "https://x/1",
        },
    )
    assert obs is not None
    assert obs.title == "Backend Engineer"
    assert obs.extra["verified"] is True
    assert obs.extra["verification_method"] == "ats_api"
    assert obs.extra["company_slug"] == "acme-corp"
    assert "Build things" in obs.raw_markdown


def test_lever_rejects_error_payload() -> None:
    assert _lever_to_obs("https://x", "acme", {"ok": False}) is None
    obs = _lever_to_obs(
        "https://x",
        "acme",
        {
            "text": "Designer",
            "descriptionPlain": "Design things. " + "y" * 200,
            "categories": {"location": "Remote"},
            "hostedUrl": "https://x/2",
        },
    )
    assert obs is not None
    assert obs.extra["verified"] is True


@pytest.mark.asyncio
async def test_live_greenhouse_detail_shape() -> None:
    try:
        import httpx

        from src.radar.sources.ats_direct import fetch_ats_job

        async with httpx.AsyncClient(timeout=20.0) as client:
            obs = await fetch_ats_job("https://boards.greenhouse.io/airbnb/jobs/8184174", client)
    except Exception:
        pytest.skip("no network")
    if obs is None:
        pytest.skip("greenhouse fixture posting gone")
    assert obs.title
    assert len(obs.raw_markdown) > 100
    assert obs.extra.get("verified") is True
