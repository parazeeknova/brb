"""ATS-direct fast fetch: structured job JSON over plain HTTPS, no browser.

Greenhouse boards-api and Lever postings API return the full posting
(title, company, location, description) in <1s. Anything served here is
verified by construction (a live structured posting with a real ID), which
is also the cheapest anti-fake signal in the pipeline: unverifiable pages
must pass the SubQ judgment instead.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.logging import get_logger
from src.radar.core.models import JobObservation

logger = get_logger("ats_direct")

GH_JOB_RX = re.compile(r"^boards\.greenhouse\.io/([^/]+)/jobs/(\d+)")
LEVER_JOB_RX = re.compile(r"^jobs\.lever\.co/([^/]+)/([0-9a-f-]{10,})")


def parse_ats_url(url: str) -> tuple[str, str, str] | None:
    """(platform, company_slug, job_id) for direct-API ATS job URLs."""
    try:
        parts = urlparse(url)
    except Exception:
        return None
    host = (parts.netloc or "").lower()
    if host == "boards.greenhouse.io":
        match = GH_JOB_RX.match(f"{host}{parts.path}")
        if match:
            return ("greenhouse", match.group(1), match.group(2))
        return None
    if host == "jobs.lever.co":
        match = LEVER_JOB_RX.match(f"{host}{parts.path}")
        if match:
            return ("lever", match.group(1), match.group(2))
        return None
    return None


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


async def _fetch_greenhouse(client: Any, slug: str, job_id: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}")
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        logger.debug(f"Greenhouse direct fetch failed: {exc}")
        return None


async def _fetch_lever(client: Any, company: str, job_id: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(f"https://api.lever.co/v0/postings/{company}/{job_id}")
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        logger.debug(f"Lever direct fetch failed: {exc}")
        return None


def _greenhouse_to_obs(url: str, slug: str, data: dict[str, Any]) -> JobObservation | None:
    title = str(data.get("title") or "").strip()
    if not title:
        return None
    location = ""
    offices = data.get("offices") or []
    if offices and isinstance(offices[0], dict):
        location = str(offices[0].get("location") or offices[0].get("name") or "")
    desc = _html_to_text(str(data.get("content") or ""))
    if len(desc) < 100:
        return None
    metadata = data.get("metadata") or []
    dept = ""
    if isinstance(metadata, list):
        for item in metadata:
            if isinstance(item, dict) and str(item.get("name", "")).lower() == "department":
                dept = str(item.get("value") or "")
    obs = JobObservation(
        url=data.get("absolute_url") or url,
        source=f"greenhouse:{slug}",
        raw_markdown=f"# {title}\n\n{location}\n\n{desc}",
        title=title,
        snippet=desc[:300],
        extra={
            "company_slug": slug,
            "department": dept,
            "verified": True,
            "verification_method": "ats_api",
        },
    )
    return obs


def _lever_to_obs(url: str, company: str, data: dict[str, Any]) -> JobObservation | None:
    if isinstance(data, dict) and data.get("ok") is False:
        return None
    title = str(data.get("text") or "").strip()
    if not title:
        return None
    location = ""
    cats = data.get("categories") or {}
    if isinstance(cats, dict):
        location = str(cats.get("location") or "")
    desc = str(data.get("descriptionPlain") or "")
    if len(desc) < 100:
        desc = _html_to_text(str(data.get("description") or ""))
    if len(desc) < 100:
        return None
    obs = JobObservation(
        url=data.get("hostedUrl") or url,
        source=f"lever:{company}",
        raw_markdown=f"# {title}\n\n{location}\n\n{desc}",
        title=title,
        snippet=desc[:300],
        extra={
            "company_slug": company,
            "verified": True,
            "verification_method": "ats_api",
        },
    )
    return obs


async def fetch_ats_job(url: str, client: Any) -> JobObservation | None:
    """Fetch one ATS job URL as a verified observation (None when not ATS/valid)."""
    parsed = parse_ats_url(url)
    if parsed is None:
        return None
    platform, slug, job_id = parsed
    if platform == "greenhouse":
        data = await _fetch_greenhouse(client, slug, job_id)
        if data:
            return _greenhouse_to_obs(url, slug, data)
    elif platform == "lever":
        data = await _fetch_lever(client, slug, job_id)
        if data:
            return _lever_to_obs(url, slug, data)
    return None
