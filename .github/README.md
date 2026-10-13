> [!IMPORTANT]
> **A note to recruiters:** If you somehow ended up here, hello. HO [Hyperdimensional Orchestrator] is a job-discovery engine: it finds, verifies, and archives real postings from across the internet. If your posting is in here, congratulations your ATS has officially become part of my distributed systems experiment.

</br>

<div align="center">

  <img src="https://img.przknv.cc/t/f_webp/ho.png" width="98%" alt="ho banner">

</div>

</br>

## Introduction

HO (Hyperdimensional Orchestrator) is a job-discovery engine built because existing job platforms are fundamentally static: they search a limited set of sources, rank with fixed rules, and show largely generic results.

HO runs 24/7 as two apps. The **ingest service** discovers postings across the entire internet (ATS APIs, job boards, free JSON firehoses, search engines), verifies each one is a real posting, normalizes and embeds it, and enriches it with founder/funding intel — building one large corpus across every role, level, and function, from junior to staff, engineering to design. The **web app** (in progress) turns that corpus into personalized matching: account, persona onboarding, and a chat agent.

The goal is not a bigger scrape. It is a corpus you can trust: every row is either proven real (structured ATS APIs, decision-model judgments) or explicitly marked unverified — never silently faked, never silently dropped.

## Performance

HO runs as a continuous stream pipeline (Redis Streams between stages), not
batch sweeps. Measured on 2 local processes over 2-minute windows:

| What | Observed |
| --- | --- |
| Observations ingested | **~640 / min** (dedup-filtered net adds) |
| Discovery firehose | **9,000+ URLs / 4 s** bursts + bulk board imports |
| Verified share | ATS-direct JSON, Workday CXS, SubQ judgments; rest tiered unverified |
| Embeddings | Gemini 3072-d, batched, content-hash deduped |
| Founders / funding | parsed from search evidence, cached 7d, graphed |

End-to-end rate is consumer-bound (fetch renders, verification judgments),
never discovery-bound. Backpressure is explicit: capped streams, BLOCK
reads, persistent dedup, DLQ for poison messages.

## Run it

### Quickstart

1. **Environment Setup**:
   ```bash
   cp .env.example .env
   # fill every value: provider keys, then infrastructure secrets
   # (POSTGRES/NEO4J/REDIS passwords, SEARXNG_SECRET, OpenObserve creds)
   ```
2. **Boot everything locally**:
   ```bash
   bun run dev
   ```
   Starts infra (Postgres, Redis, Neo4j, SearXNG, OpenObserve), the web
   frontend, and the ingest pipeline with color-coded logs.

### Commands

| Command | Description |
| :-- | :-- |
| `bun run dev` | **Local Dev** — Infra + web + ingest, colored prefixes, OTEL to OpenObserve. |
| `bun run run [--procs 2] [--max-minutes N]` | **Ingest Pipeline** — Corpus builder (infinite by default). |
| `bun run status [--once]` | **Corpus Status** — Counts, eligibility, stream depths, verification coverage. |
| `bun run export` | **Export Candidates** — Accepted jobs to CSV. |
| `bun run intel` | **Market Intelligence** — Hiring radar, salary stats, company research. |
| `bun run health` | **Health Diagnostics** — DB connections and container status. |
| `bun run check` / `bun run test` | **Gates** — Lint, format, types, full test suites. |

Overnight/production deploys (Dokploy + GCE) are covered in
`docs/DOKPLOY.md` and `docs/GCE_OVERNIGHT.md`. The DB contract the web app
reads lives in `packages/db` (Prisma 8, read-only against the corpus).

---
# System Architecture

Two apps, one corpus. The ingest service builds it; the web app (and its
Prisma contract in `packages/db`) reads it. Everything below is the ingest
half — the part that runs 24/7.

The important architectural properties:

- **Continuous, not batched.** Stages run forever as Redis-Streams consumer
  groups. No sweeps, no phases, no global barriers.
- **Tiered trust.** Rows are `verified` (ATS APIs, decision-model judgments)
  or `unverified` (real-looking, unproven). Unverifiable is not fake — but
  only verified rows are claimed as such.
- **Postgres is the record store; Redis is motion; Neo4j is intel.**
  Streams carry tiny routing payloads; bodies live in Postgres.

## 1. Discovery (11 producer types, always on)

ATS-direct JSON (Greenhouse/Lever/Ashby), Workday CXS bulk import, ATS board
polls, high-volume URL discovery, mass slug poller, GitHub indexes, SearXNG
dorks, TinyFish web search (12k/day), free JSON firehoses (Arbeitnow,
RemoteOK, HN hiring threads, USAJobs), and company discovery. Interval-guarded
per source, persistently deduped (Redis, 7d TTL), backpressured by stream caps.

## 2. Fetch (24 workers/proc)

ATS URLs take the sub-second JSON path (verified by construction). Everything
else renders locally, with TinyFish Fetch as the off-box fallback for JS
shells. Scraped bodies are archived into the observation row; already-
persisted structured rows are never re-rendered. Unfetchable leaf URLs
(auth-walled LinkedIn views, Indeed search pages, JS wrappers) are filtered
at publish so they never burn fetch budget.

## 3. Normalize (16 workers/proc)

Deterministic gates only: URL quality, duplicates, role classification (never
rejects — every role/level/function enters), freshness lanes (stale rows are
archived, not rejected). ATS rows arrive verified; the rest get a SubQ
`systemone` real-posting judgment (cached by content hash, 30/min cap, 402
breaker). Pass or fail, substantive rows enter tiered; thin garbage dies.

## 4. Embed + Enrich

Embeddings (Gemini 3072-d, batched, content-hash deduped) land in pgvector.
Enrichment attaches founders/funding parsed from search evidence (cached 7d
in `company_osint`) onto candidate rows and Neo4j (`FOUNDED_BY`,
`HAS_FUNDING`), so the graph grows relations again.

```mermaid
flowchart LR
    D["11 producers<br/>always on"] --> S1["ho:s:discover"]
    S1 --> F["fetch x24<br/>ATS-direct / render"]
    F --> S2["ho:s:raw"]
    S2 --> N["normalize x16<br/>gates + SubQ verify"]
    N --> S3["ho:s:gated"]
    N --> S4["ho:s:embed"]
    N --> S5["ho:s:enrich"]
    S4 --> E["embed x4<br/>pgvector"]
    S5 --> R["enrich x2<br/>founders/funding"]
    N --> PG[("Postgres<br/>corpus")]
    N --> G["Neo4j<br/>companies"]
    PG --> W["web app<br/>Prisma contract"]
```

Postgres holds every record (observations, candidates, embeddings,
checkpoints). Redis holds motion (streams, dedup, budgets) and is safe to
lose. Neo4j holds derived company intel and rebuilds from the corpus.

## 5. Engineering Principles, Reliability & Roadmap

HO is designed around a few core engineering constraints: PostgreSQL remains the transactional source of truth, pgvector provides semantic retrieval without another vector database, Neo4j handles relationship-heavy intelligence, and Redis Streams carry motion between stages that never block each other. Every write is idempotent, every queue is bounded, every crash redelivers — so killing a container mid-run (deploys do this on every merge) loses nothing.

External systems are treated as unreliable dependencies. Search sources can disappear, ATS schemas can change, HTTP requests can be blocked, browser sessions can fail, model APIs can 429 or run dry. The system therefore uses retries, per-source rate limits and daily budgets, checkpoints, persistent dedup, verdict caching, fallback acquisition paths, and a DLQ for poison messages. An unprocessed URL is preferable to a fabricated job.

```mermaid
flowchart TD
    S["External Services"]
    Q["Queues + Leases"]
    T["Retries + Rate Limits"]
    C["Checkpoints + Deduplication"]
    V["Deterministic Verification"]
    F["Fail Closed"]
    A["External Action"]

    S --> Q
    Q --> T
    T --> C
    C --> V
    V -->|valid| A
    V -->|invalid| F
```

The long-term direction is corpus depth and trust: more sources, more functions and geos, richer company intel, and tighter verification — feeding the web app's matching. The fundamental objective remains the same: a job corpus comprehensive enough and honest enough to recommend from.

## Final Notes

HO is intentionally overengineered for its original purpose. That is part of the point. It started as a single-person job-search automaton and evolved into a multi-user discovery platform: a 24/7 corpus service plus a matching web app.

The system is not designed around the assumption that the first version of a source, gate, query strategy, or verification judgment will be correct. Every layer is treated as replaceable and measurable. Sources can be reweighted, gates can be re-cut, budgets can be retuned, and the corpus keeps score of what each producer actually yields.

The most important component is therefore not any individual model or database. It is the pipeline that never stops and never lies about what it found.

**Discover. Verify. Repeat.**

> [!NOTE]
> HO is an engineering experiment built around a very simple premise: a job is only real if you can prove it.

---

## Credits

Built, designed, debugged, over-engineered, and occasionally questioned at unreasonable hours by [pzk](https://przknv.cc).

The architecture borrows ideas from distributed systems, information retrieval, stream processing, graph analytics, retrieval-augmented generation, browser automation, and event-driven systems.

The project also owes an unreasonable amount to the scientific methodology of one self-proclaimed mad scientist.

> “The world is not deterministic. We merely haven't collected enough observations yet.”

~ **El. Psy. Kongroo.**
