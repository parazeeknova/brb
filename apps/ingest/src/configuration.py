"""Centralized, strongly-typed configuration with env-var overrides.

All magic numbers and scattered constants live here. Every module consumes
this one config object. Environment variables override defaults at startup.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is not None:
        return val.strip().lower() in ("1", "true", "yes", "on")
    return default


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_list(key: str, default: list[str]) -> list[str]:
    """Parse a comma/pipe-separated env var into a list, filtering empties."""
    raw = os.environ.get(key, "")
    if not raw.strip():
        return default
    return [item.strip() for item in re.split(r"[,\|]", raw) if item.strip()]


# Configuration


@dataclass
class HttpConfig:
    """Shared HTTP client settings for all connectors and internal services."""

    default_timeout: float = field(default_factory=lambda: _env_float("HTTP_DEFAULT_TIMEOUT", 30.0))
    connect_timeout: float = field(default_factory=lambda: _env_float("HTTP_CONNECT_TIMEOUT", 10.0))
    max_keepalive: int = field(default_factory=lambda: _env_int("HTTP_MAX_KEEPALIVE", 20))
    max_connections: int = field(default_factory=lambda: _env_int("HTTP_MAX_CONNECTIONS", 100))
    cache_enabled: bool = field(default_factory=lambda: _env_bool("HTTP_CACHE_ENABLED", True))
    cache_max_body_bytes: int = field(
        default_factory=lambda: _env_int("HTTP_CACHE_MAX_BODY_BYTES", 524288)
    )
    cache_ttl_default: int = field(default_factory=lambda: _env_int("HTTP_CACHE_TTL_DEFAULT", 900))


@dataclass
class RetryConfig:
    """Global retry policy."""

    max_retries: int = field(default_factory=lambda: _env_int("RETRY_MAX", 3))
    base_delay: float = field(default_factory=lambda: _env_float("RETRY_BASE_DELAY", 1.0))
    max_delay: float = field(default_factory=lambda: _env_float("RETRY_MAX_DELAY", 30.0))
    jitter: bool = field(default_factory=lambda: _env_bool("RETRY_JITTER", True))


@dataclass
class RateLimitConfig:
    """Per-connector rate limiting (seconds between calls)."""

    yc: float = field(default_factory=lambda: _env_float("RATE_YC", 2.0))
    producthunt: float = field(default_factory=lambda: _env_float("RATE_PRODUCTHUNT", 1.5))
    github: float = field(default_factory=lambda: _env_float("RATE_GITHUB", 3.0))
    hn: float = field(default_factory=lambda: _env_float("RATE_HN", 2.0))
    vc: float = field(default_factory=lambda: _env_float("RATE_VC", 2.0))
    founder_social: float = field(default_factory=lambda: _env_float("RATE_FOUNDER_SOCIAL", 1.5))


@dataclass
class PipelineConfig:
    """Continuous stream-pipeline settings (no sweeps, no batches).

    Each stage runs forever as Redis-Streams consumer groups; parallelism
    comes from consumer counts, backpressure from stream MAXLEN caps and
    BLOCK reads. sweep_interval is kept as the source-lane base tick
    (sources.py lane scheduling), not as a loop sleep.
    """

    fetch_workers: int = field(default_factory=lambda: _env_int("FETCH_WORKERS", 24))
    normalize_workers: int = field(default_factory=lambda: _env_int("NORMALIZE_WORKERS", 16))
    embed_workers: int = field(default_factory=lambda: _env_int("EMBED_WORKERS", 4))
    enrich_workers: int = field(default_factory=lambda: _env_int("ENRICH_WORKERS", 2))
    stream_maxlen: int = field(default_factory=lambda: _env_int("STREAM_MAXLEN", 5000))
    block_ms: int = field(default_factory=lambda: _env_int("STREAM_BLOCK_MS", 5000))
    sweep_interval: float = field(default_factory=lambda: _env_float("SWEEP_INTERVAL", 5.0))


@dataclass
class StreamsConfig:
    """Redis Streams transport for the pipeline (motion, not state).

    Postgres remains the record store; streams carry small routing payloads
    (urls, hashes, ids) between always-on stage consumer groups.
    """

    redis_url: str = field(default_factory=lambda: _default_redis_url())
    claim_idle_ms: int = field(default_factory=lambda: _env_int("STREAM_CLAIM_IDLE_MS", 300000))
    max_deliveries: int = field(default_factory=lambda: _env_int("STREAM_MAX_DELIVERIES", 5))


def _default_redis_url() -> str:
    explicit = _env_str("STREAMS_REDIS_URL", "")
    if explicit:
        return explicit
    from urllib.parse import quote as _quote

    password = _env_str("REDIS_PASSWORD", "")
    auth = f":{_quote(password)}@" if password else ""
    host = _env_str("REDIS_HOST", "127.0.0.1")
    port = _env_str("REDIS_PORT", "6380")
    return f"redis://{auth}{host}:{port}/0"


@dataclass
class Neo4jConfig:
    """Neo4j graph database settings."""

    uri: str = field(default_factory=lambda: _env_str("NEO4J_URI", "bolt://127.0.0.1:7687"))
    username: str = field(default_factory=lambda: _env_str("NEO4J_USERNAME", "neo4j"))
    password: str = field(default_factory=lambda: _env_str("NEO4J_PASSWORD", "password"))
    max_connection_lifetime: int = field(
        default_factory=lambda: _env_int("NEO4J_MAX_CONN_LIFETIME", 3600)
    )


def _default_postgres_dsn() -> str:
    """Full POSTGRES_DSN wins; otherwise build from parts (password from env)."""
    explicit = os.environ.get("POSTGRES_DSN", "").strip()
    if explicit:
        return explicit
    from urllib.parse import quote as _quote

    user = _env_str("POSTGRES_USER", "postgres")
    password = _env_str("POSTGRES_PASSWORD", "")
    host = _env_str("POSTGRES_HOST", "localhost")
    port = _env_str("POSTGRES_PORT", "5443")
    db = _env_str("POSTGRES_DB", "agent_memory")
    auth = f"{user}:{_quote(password)}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{db}"


@dataclass
class PostgresConfig:
    """PostgreSQL / pgvector settings."""

    dsn: str = field(default_factory=_default_postgres_dsn)
    min_pool: int = field(default_factory=lambda: _env_int("POSTGRES_MIN_POOL", 2))
    max_pool: int = field(default_factory=lambda: _env_int("POSTGRES_MAX_POOL", 25))
    vector_dim: int = field(default_factory=lambda: _env_int("VECTOR_DIM", 1024))


@dataclass
class SearXNGCongfig:
    """SearXNG metasearch settings."""

    url: str = field(
        default_factory=lambda: _env_str("SEARXNG_URL", "http://localhost:8080/search")
    )
    timeout: float = field(default_factory=lambda: _env_float("SEARXNG_TIMEOUT", 6.0))
    semaphore: int = field(default_factory=lambda: _env_int("SEARXNG_SEMAPHORE", 5))


@dataclass
class RenderConfig:
    """In-process page-rendering budget + anti-blocking controls.

    The in-process renderer (static httpx + pooled Chromium) is used instead
    of an external scraping service. Env names use the RENDER_* prefix; the
    legacy FIRECRAWL_* names are still honored for backward compatibility.
    """

    url: str = field(default_factory=lambda: _env_str("FIRECRAWL_URL", "http://127.0.0.1:3002"))
    timeout: float = field(default_factory=lambda: _env_float("FIRECRAWL_TIMEOUT", 60.0))
    map_limit: int = field(default_factory=lambda: _env_int("FIRECRAWL_MAP_LIMIT", 500))
    scrape_limit: int = field(default_factory=lambda: _env_int("FIRECRAWL_SCRAPE_LIMIT", 1000))
    scrape_timeout: float = field(
        default_factory=lambda: _env_float("FIRECRAWL_SCRAPE_TIMEOUT", 15.0)
    )
    # Politeness: minimum seconds between requests to the SAME host (jittered).
    host_delay: float = field(default_factory=lambda: _env_float("RENDER_HOST_DELAY", 0.5))
    # SOCKS5 proxy (torproxy on 9050) for JS renders and static fetches when
    # set — rotates egress IP so a site can't block the datacenter IP.
    socks_proxy: str = field(
        default_factory=lambda: _env_str("RENDER_SOCKS_PROXY", "socks5://127.0.0.1:9050")
    )
    # Master switch: route through the proxy by default (masking). Set to
    # false to disable proxying entirely.
    use_proxy: bool = field(default_factory=lambda: _env_bool("RENDER_USE_PROXY", True))
    # Retry a blocked request (429/403/Cloudflare challenge) via the proxy.
    proxy_on_block: bool = field(default_factory=lambda: _env_bool("RENDER_PROXY_ON_BLOCK", True))
    # JS-shell heuristic: a page whose visible text is below this many chars is
    # treated as an un-rendered SPA shell and sent to the browser. Real job
    # pages carry a description body far above this.
    shell_threshold_chars: int = field(
        default_factory=lambda: _env_int("RENDER_SHELL_THRESHOLD_CHARS", 200)
    )
    # Client-side render settle time after domcontentloaded (JS-SPA hydration).
    render_settle_ms: int = field(default_factory=lambda: _env_int("RENDER_SETTLE_MS", 2500))
    proxied_settle_ms: int = field(
        default_factory=lambda: _env_int("RENDER_PROXIED_SETTLE_MS", 3000)
    )
    # In-memory + (optional) Postgres-backed render cache: TTL seconds and the
    # max in-memory entries before stale eviction.
    cache_ttl: int = field(default_factory=lambda: _env_int("RENDER_CACHE_TTL", 600))
    cache_max_entries: int = field(
        default_factory=lambda: _env_int("RENDER_CACHE_MAX_ENTRIES", 4000)
    )
    # Whether to persist the render cache in Postgres (survives restarts and is
    # shared across ingest workers). Falls back to the in-memory dict when the
    # DB is unreachable.
    cache_persist: bool = field(default_factory=lambda: _env_bool("RENDER_CACHE_PERSIST", True))
    # Chromium pool: max concurrent JS renders and idle-close window (ms).
    concurrency: int = field(default_factory=lambda: _env_int("RENDER_CONCURRENCY", 4))
    pool_idle_ms: int = field(default_factory=lambda: _env_int("RENDER_IDLE_MS", 30000))


@dataclass
class EmbedConfig:
    """Embedding provider settings (external API; no local server)."""

    url: str = field(default_factory=lambda: _env_str("EMBED_URL", ""))
    model: str = field(default_factory=lambda: _env_str("EMBED_MODEL", "gemini-embedding-2"))
    timeout: float = field(default_factory=lambda: _env_float("EMBED_TIMEOUT", 30.0))


@dataclass
class LLMConfig:
    """LLM / GeneralCompute settings."""

    api_key: str = field(default_factory=lambda: _env_str("GENERALCOMPUTE_API_KEY", ""))
    model: str = field(default_factory=lambda: _env_str("GENERALCOMPUTE_MODEL", "deepseek-v3.2"))
    # Fallback chain tried in order when the primary model is overloaded,
    # rate-limited, or errors out. Comma/pipe-separated in LLM_FALLBACK_MODELS.
    fallback_models: list[str] = field(
        default_factory=lambda: _env_list("LLM_FALLBACK_MODELS", ["deepseek-v3.1", "minimax-m2.7"])
    )
    context_length: int = field(default_factory=lambda: _env_int("LLM_CONTEXT_LENGTH", 32768))
    token_rate: float = field(default_factory=lambda: _env_float("LLM_TOKEN_RATE", 1.4))
    token_max: int = field(default_factory=lambda: _env_int("LLM_TOKEN_MAX", 30))
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 3))
    retry_delay: float = field(default_factory=lambda: _env_float("LLM_RETRY_DELAY", 2.0))
    # Hard per-attempt timeout: a model that hangs (no error, no response) must
    # not stall the caller forever. When an attempt exceeds this, it counts as
    # a failure and the next fallback model is tried.
    per_call_timeout_s: float = field(
        default_factory=lambda: _env_float("LLM_PER_CALL_TIMEOUT_S", 30.0)
    )
    rate_penalty_secs: float = field(
        default_factory=lambda: _env_float("LLM_RATE_PENALTY_SECS", 60.0)
    )
    max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 4096))


@dataclass
class LinkedinGuestConfig:
    """LinkedIn guest API scraping settings."""

    timeout: float = field(default_factory=lambda: _env_float("LINKEDIN_TIMEOUT", 12.0))
    max_pages: int = field(default_factory=lambda: _env_int("LINKEDIN_MAX_PAGES", 4))
    delay_min: float = field(default_factory=lambda: _env_float("LINKEDIN_DELAY_MIN", 1.5))
    delay_max: float = field(default_factory=lambda: _env_float("LINKEDIN_DELAY_MAX", 3.5))


def _candidate_persona_paths() -> list[str]:
    """Explicit persona file only (CANDIDATE_PERSONA_FILE). There are no
    repo-level persona defaults; per-user onboarding owns this long-term."""
    env_file = os.environ.get("CANDIDATE_PERSONA_FILE")
    return [env_file] if env_file else []


def _load_persona_file() -> str:
    """Render the flat candidate grounding text from an explicit persona file.

    The radar matcher consumes the persona as one text block. Falls back to
    the CANDIDATE_PERSONA env var when no persona file is configured. Empty
    string when neither is set (per-user onboarding owns this long-term).
    """
    for path in _candidate_persona_paths():
        if not os.path.exists(path):
            continue
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):  # fmt: skip
            continue
        blocks: list[str] = []
        identity = data.get("identity") or {}
        for key, value in identity.items():
            if value:
                blocks.append(f"- {key}: {value}")
        for a in data.get("answers") or []:
            q, ans = a.get("question"), a.get("answer")
            if q and ans:
                blocks.append(f"- {q}: {ans}")
        resume = (data.get("resume_summary") or "").strip()
        if resume:
            blocks.append("")
            blocks.append("From Resume:")
            blocks.append(resume)
        if blocks:
            return "\n".join(blocks)
    return _env_str("CANDIDATE_PERSONA", "")


@dataclass
class CandidateConfig:
    """Legacy single-persona grounding (persona text only; matching moved out).

    Salary/location/authorization filters are gone: the corpus keeps every
    role and the web app filters per user.
    """

    persona: str = field(default_factory=_load_persona_file)


@dataclass
class RadarConfig:
    """Job radar v2 pipeline settings."""

    poll_high_freq_seconds: float = field(
        default_factory=lambda: _env_float("RADAR_HIGH_FREQ_POLL", 180.0)
    )
    poll_low_freq_seconds: float = field(
        default_factory=lambda: _env_float("RADAR_LOW_FREQ_POLL", 1800.0)
    )
    urgent_window_hours: int = field(
        default_factory=lambda: _env_int("RADAR_URGENT_WINDOW_HOURS", 48)
    )
    stale_days: int = field(default_factory=lambda: _env_int("RADAR_STALE_DAYS", 30))
    source_min_confidence: float = field(
        default_factory=lambda: _env_float("RADAR_SOURCE_MIN_CONFIDENCE", 0.3)
    )
    # Discovery source for new companies. "azure" = only the Azure relic's
    # company index blobs; "all" = local adapters (dealroom/YC/VC/HN/etc);
    # "none" = disable company discovery entirely.
    discovery_source: str = field(
        default_factory=lambda: _env_str("DISCOVERY_SOURCE", "all").lower()
    )


@dataclass
class ATSCrawlerConfig:
    """ATS-specific crawling parameters."""

    greenhouse_base: str = "https://boards.greenhouse.io"
    lever_base: str = "https://jobs.lever.co"
    ashby_base: str = "https://jobs.ashbyhq.com"
    workable_base: str = "https://apply.workable.com"
    smartrecruiters_base: str = "https://jobs.smartrecruiters.com"
    rippling_base: str = "https://app.rippling.com/careers"
    max_pages_per_board: int = field(default_factory=lambda: _env_int("ATS_MAX_PAGES", 10))
    snapshot_ttl_hours: int = field(default_factory=lambda: _env_int("ATS_SNAPSHOT_TTL_HOURS", 6))


@dataclass
class Config:
    """Root configuration aggregating all subsystems."""

    http: HttpConfig = field(default_factory=HttpConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    streams: StreamsConfig = field(default_factory=StreamsConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    searxng: SearXNGCongfig = field(default_factory=SearXNGCongfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    linkedin_guest: LinkedinGuestConfig = field(default_factory=LinkedinGuestConfig)
    candidate: CandidateConfig = field(default_factory=CandidateConfig)
    radar: RadarConfig = field(default_factory=RadarConfig)
    ats: ATSCrawlerConfig = field(default_factory=ATSCrawlerConfig)

    def validate(self) -> list[str]:
        """Run startup validation. Returns list of problems (empty = all good)."""
        problems: list[str] = []

        if self.http.default_timeout <= 0:
            problems.append("http.default_timeout must be > 0")
        if self.http.max_connections <= 0:
            problems.append("http.max_connections must be > 0")
        if self.retry.max_retries < 0:
            problems.append("retry.max_retries must be >= 0")
        if self.postgres.min_pool > self.postgres.max_pool:
            problems.append("postgres.min_pool must be <= max_pool")

        return problems

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """Return a flat dict suitable for health-check reporting."""
        return {
            "http": {
                "default_timeout": self.http.default_timeout,
                "max_connections": self.http.max_connections,
            },
            "retry": {
                "max_retries": self.retry.max_retries,
                "base_delay": self.retry.base_delay,
            },
            "pipeline": {
                "fetch_workers": self.pipeline.fetch_workers,
                "normalize_workers": self.pipeline.normalize_workers,
                "embed_workers": self.pipeline.embed_workers,
                "enrich_workers": self.pipeline.enrich_workers,
                "stream_maxlen": self.pipeline.stream_maxlen,
            },
            "postgres": {
                "min_pool": self.postgres.min_pool,
                "max_pool": self.postgres.max_pool,
            },
            "llm": {
                "model": self.llm.model,
            },
            "radar": {
                "urgent_window_hours": self.radar.urgent_window_hours,
                "stale_days": self.radar.stale_days,
            },
        }


_config: Config | None = None


def get_config() -> Config:
    """Return the singleton Config, creating it on first call."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Override the singleton (useful for tests)."""
    global _config
    _config = config
