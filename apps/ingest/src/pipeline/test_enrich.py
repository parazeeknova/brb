"""Enrichment tests: deterministic founder/funding parsing (fixtures only)."""

from __future__ import annotations

from src.pipeline import enrich


def test_parse_founders_simple() -> None:
    snippets = ["Acme was founded by Jane Doe and John Smith in 2020."]
    assert enrich.parse_founders(snippets) == ["Jane Doe", "John Smith"]


def test_parse_founders_cofounder() -> None:
    snippets = ["Co-founder Alice Johnson leads product at Beta Corp."]
    assert enrich.parse_founders(snippets) == ["Alice Johnson"]


def test_parse_founders_ignores_noise() -> None:
    assert enrich.parse_founders(["We are hiring engineers. Apply now!"]) == []
    assert enrich.parse_founders(["Founded by the team in a garage"]) == []


def test_parse_funding_amount_and_stage() -> None:
    snippets = ["Acme raised $45M Series B led by Sequoia."]
    funding = enrich.parse_funding(snippets)
    assert funding["amount"] == "$45M"
    assert funding["stage"] == "Series B"


def test_parse_funding_seed() -> None:
    assert enrich.parse_funding(["Seed funding round announced"])["stage"] == "Seed"
    assert enrich.parse_funding(["We raised a pre-seed round"])["stage"] == "Pre-seed"


def test_parse_funding_empty() -> None:
    assert enrich.parse_funding(["Nothing about money here."]) == {}


def test_slug() -> None:
    assert enrich._slug("Acme Corp!") == "acme-corp"


def test_is_company_fresh_uses_redis_flag() -> None:
    import asyncio

    class FakeRedis:
        def __init__(self, seen: bool) -> None:
            self.seen = seen

        async def get(self, key: str):
            return "1" if self.seen else None

    class FakeBus:
        def __init__(self, seen: bool) -> None:
            self.redis = FakeRedis(seen)

    class Ctx:
        def __init__(self, seen: bool) -> None:
            self.bus = FakeBus(seen)

    assert asyncio.run(enrich.is_company_fresh(Ctx(False), "Acme")) is True
    assert asyncio.run(enrich.is_company_fresh(Ctx(True), "Acme")) is False


def test_handle_enrich_skips_blank_and_unknown() -> None:
    import asyncio

    class Ctx:
        pass

    assert asyncio.run(enrich.handle_enrich(Ctx(), {"company": "", "canonical_id": "c"})) is None
    assert (
        asyncio.run(enrich.handle_enrich(Ctx(), {"company": "Unknown", "canonical_id": "c"}))
        is None
    )
