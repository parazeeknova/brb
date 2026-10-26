"""Workday CXS direct fetch: structured postings without a browser.

Every myworkdayjobs customer exposes POST /wday/cxs/{tenant}/{board}/jobs
(title, location, req ID, relative URL). That's a verified observation by
construction — no render, no JS shell, sub-second per hundred rows.
Full descriptions need the detail page (unreliable across tenants), so rows
carry title/location/company and normalize gates on that content.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.logging import get_logger
from src.radar.core.models import JobObservation

logger = get_logger("workday")

WORKDAY_HOST_RX = re.compile(r"^(?:[\w-]+\.)*myworkdayjobs\.com$", re.IGNORECASE)
PAGE_LIMIT = 100
BOARD_CAP = 500


def parse_workday_url(url: str) -> tuple[str, str, str] | None:
    """(host, tenant, board) for Workday career-site URLs."""
    try:
        parts = urlparse(url)
    except Exception:
        return None
    host = (parts.netloc or "").lower()
    if not WORKDAY_HOST_RX.match(host):
        return None
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) < 2:
        return None
    return (host, segs[0], segs[1])


def job_url(host: str, external_path: str) -> str:
    path = external_path if external_path.startswith("/") else f"/{external_path}"
    return f"https://{host}{path}"


def _req_id(external_path: str) -> str:
    match = re.search(r"([A-Z]{1,3}\d{4,})", external_path)
    return match.group(1) if match else ""


def posting_to_obs(
    host: str, tenant: str, board: str, posting: dict[str, Any]
) -> JobObservation | None:
    """One CXS search hit -> verified observation (title/location/URL only)."""
    title = str(posting.get("title") or "").strip()
    path = str(posting.get("externalPath") or "")
    if not title or not path:
        return None
    url = job_url(host, path)
    company = board.replace("-", " ").title()
    obs = JobObservation(
        url=url,
        source=f"workday:{board}",
        raw_markdown="",
        title=title,
        snippet=str(posting.get("locationsText") or ""),
        extra={
            "company_slug": company.lower().replace(" ", "-"),
            "tenant": tenant,
            "req_id": _req_id(path),
            "time_type": str(posting.get("timeType") or ""),
            "posted_on": str(posting.get("postedOn") or ""),
            "verified": True,
            "verification_method": "workday_api",
        },
    )
    return obs


async def search_board(
    client: Any, host: str, tenant: str, board: str, limit: int = PAGE_LIMIT
) -> list[dict[str, Any]]:
    """Paginated CXS search -> raw posting dicts (bounded)."""
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < BOARD_CAP:
        try:
            resp = await client.post(
                f"https://{host}/wday/cxs/{tenant}/{board}/jobs",
                json={"searchText": "", "appliedFacets": {}, "limit": limit, "offset": offset},
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            postings = data.get("jobPostings") or []
            if not postings:
                break
            out.extend(postings)
            total = int(data.get("total") or 0)
            offset += len(postings)
            if offset >= total or len(postings) < limit:
                break
        except Exception as exc:
            logger.debug(f"Workday search failed for {board}: {exc}")
            break
    return out[:BOARD_CAP]


async def poll_workday_board(board_url: str, client: Any) -> list[JobObservation]:
    """Whole board via CXS search: hundreds of verified obs, zero renders."""
    parsed = parse_workday_url(board_url)
    if parsed is None:
        return []
    host, tenant, board = parsed
    try:
        postings = await search_board(client, host, tenant, board)
    except Exception as exc:
        logger.warning(f"Workday board poll failed for {board_url}: {exc}")
        return []
    obs: list[JobObservation] = []
    for posting in postings:
        try:
            item = posting_to_obs(host, tenant, board, posting)
        except Exception:
            continue
        if item is not None:
            obs.append(item)
    logger.info(f"Workday board {board}: {len(obs)} verified postings")
    return obs
