"""SubQ systemone decisions: calibrated yes/no judgments, prefill-priced.

subq-snap-preview: $0.05/1M input tokens, output FREE (no tokens generated).
Used for verification judgments on pages no ATS API covers. A 402 response
means credits are gone: the module trips a circuit breaker so the pipeline
degrades to deterministic checks instead of burning failing calls.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from src.logging import get_logger

logger = get_logger("subq")

BASE_URL = os.environ.get("SUBQ_BASE_URL", "https://api.subq.ai/v1")
MODEL = os.environ.get("SUBQ_MODEL", "subq-snap-preview")
TIMEOUT_S = float(os.environ.get("SUBQ_TIMEOUT_S", "20"))

_disabled_until = 0.0
_disabled_logged = False


def api_key() -> str:
    return os.environ.get("SUBQ_API_KEY", "").strip()


def is_available() -> bool:
    """False when no key is configured or the 402 breaker is open."""
    return bool(api_key()) and time.monotonic() >= _disabled_until


def _trip_breaker(minutes: float = 30.0) -> None:
    global _disabled_until, _disabled_logged
    _disabled_until = time.monotonic() + minutes * 60.0
    if not _disabled_logged:
        _disabled_logged = True
        logger.warning(f"SubQ credits exhausted (402); decisions paused {minutes:.0f}min")


async def decide(
    state: str,
    questions: dict[str, Any],
    *,
    timeout: float = TIMEOUT_S,
) -> dict[str, Any]:
    """POST /v1/systemone -> answers dict ({} on any failure, never raises)."""
    if not is_available():
        return {}
    key = api_key()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = await client.post(
                f"{BASE_URL}/systemone",
                json={"model": MODEL, "state": state, "questions": questions},
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 402:
            _trip_breaker()
            return {}
        if resp.status_code != 200:
            logger.debug(f"SubQ systemone {resp.status_code}")
            return {}
        data = resp.json()
        answers = data.get("answers")
        return answers if isinstance(answers, dict) else {}
    except Exception as exc:
        logger.debug(f"SubQ decide failed: {exc}")
        return {}


def noul_probability(answers: dict[str, Any], question: str) -> float | None:
    """Extract the noul probability for one question (None when absent)."""
    try:
        item = answers.get(question) or {}
        if item.get("type") != "noul":
            return None
        value = item.get("noul")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    except TypeError, ValueError:
        return None


async def is_real_posting(title: str, company: str, text: str) -> float | None:
    """Calibrated P(real current job posting) for one page (None = unknown)."""
    if len(title.strip()) < 4 or len(text) < 400:
        return None  # too thin to judge; never spends model budget
    state = f"Job posting page. Title: {title[:120]}. Company: {company[:80]}.\n{text[:3000]}"
    answers = await decide(
        state,
        {
            "real": {
                "type": "noul",
                "instructions": (
                    "Is this a real, currently-open job posting from an employer "
                    "(with a role, requirements, and a way to apply)?"
                ),
            }
        },
    )
    return noul_probability(answers, "real")
