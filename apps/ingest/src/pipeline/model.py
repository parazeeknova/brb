"""Stream message schemas: tiny routing payloads, Postgres holds the bodies.

discover  {url, source}            -> fetch
raw       {url_hash, url, source}  -> normalize
gated     {canonical_id}           -> (graph/caches; terminal)
embed     {url_hash}               -> embed
"""

from __future__ import annotations


def discover_fields(url: str, source: str) -> dict[str, str]:
    return {"url": url, "source": source}


def raw_fields(url_hash: str, url: str, source: str) -> dict[str, str]:
    return {"url_hash": url_hash, "url": url, "source": source}


def gated_fields(canonical_id: str) -> dict[str, str]:
    return {"canonical_id": canonical_id}


def embed_fields(url_hash: str) -> dict[str, str]:
    return {"url_hash": url_hash}


def enrich_fields(company: str, canonical_id: str) -> dict[str, str]:
    return {"company": company, "canonical_id": canonical_id}


def valid_url(url: str) -> bool:
    """parallels the old sweep's URL sanity gate."""
    return bool(url) and url.startswith("http") and len(url) < 2000
