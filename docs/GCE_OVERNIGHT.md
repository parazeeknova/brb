# GCE overnight runbook: ho corpus on a 2c/16GB instance

Target: one always-on box that builds the corpus indefinitely, survives reboots/crashes, keeps secrets secret, and pages you when sick.

## 1. Provision

- Machine: `e2-standard-2` (2 vCPU, 8 GB) minimum; 16 GB preferred for Neo4j + OpenObserve headroom. 100 GB balanced PD (telemetry + pg growth).
- OS: Ubuntu 24.04 LTS. Install Docker Engine + compose plugin only.
- **Firewall (critical): deny all ingress except SSH (or better: GCP Identity-Aware Proxy, no public SSH at all).** Every ho service binds `127.0.0.1` in `docker/docker-compose.yml`, but defense in depth: no public ports, period. Verify: `nmap -Pn <external-ip>` shows nothing but 22 (or nothing with IAP).

## 2. Secrets

```bash
cp .env.example .env
# fill every value (compose refuses to start with any missing):
#   GENERALCOMPUTE_API_KEY, GEMINI_API_KEY, TINY_FISH_API_KEY, SUBQ_API_KEY
#   POSTGRES_PASSWORD, NEO4J_PASSWORD, REDIS_PASSWORD, SEARXNG_SECRET
#   ZO_ROOT_USER_EMAIL, ZO_ROOT_USER_PASSWORD (upper+lower+digit+special)
chmod 600 .env
```

`.env` is gitignored. Never bake it into images. Rotate by editing `.env` and `docker compose up -d --force-recreate <service>` — except Postgres and Neo4j, whose passwords live inside their data volumes after first init:

- Postgres: `ALTER USER postgres PASSWORD '...'` via any SQL client.
- Neo4j: wipe + recreate accepts the new password (`docker compose down neo4j`, `docker volume rm ho_neo4j_data`, `up -d neo4j`) — graph intel rebuilds from the corpus as the pipeline runs.

## 3. Deploy

```bash
docker compose -f docker/docker-compose.yml up -d          # infra
docker compose -f docker/docker-compose.yml up -d pipeline # corpus loop
docker compose -f docker/docker-compose.yml ps
```

`restart: unless-stopped` on everything survives reboots and crashes. The pipeline supervisor (`loop.py`) restarts dead children forever with per-child backoff; the `--max-minutes 0` default never stops on its own. Logs: `docker compose logs -f pipeline` (20 MB x 5 rotation per service) plus structured history in OpenObserve at `http://localhost:5090` (SSH-tunnel it: `ssh -L 5090:localhost:5090 <host>`).

## 4. Backups (do this before the first overnight)

- Nightly pg_dump: `0 3 * * * /opt/ho/scripts/backup_corpus.sh /var/backups/ho` (7-day rotation, custom format).
- Weekly GCE disk snapshot of the data disk (console or `gcloud compute disks snapshot`). This is your disaster recovery, not the dumps.
- Redis streams are transport, not records — safe to lose (unprocessed URLs get rediscovered; dedup sets rebuild).

## 5. Monitoring

- Liveness cron every 5 min (alerts to your mail/webhook): `*/5 * * * * PYTHONPATH=/opt/ho:/opt/ho/apps/ingest /usr/local/bin/uv run --project /opt/ho python /opt/ho/apps/ingest/scripts/tools/overnight_monitor.py --check || <alert>` Fails on: no pipeline procs, DB/Redis unreachable, DLQ > 100, disk > 90%.
- Watch in OpenObserve: stream depths (raw backlog growth = consumers starving), `dlq` stream (poison messages), error-rate by logger.
- Disk: OpenObserve `/data` and pg volume grow unbounded — the monitor's disk check is your tripwire; add GCE disk alerts too.

## 6. Rate limits (what caps spend overnight)

| Surface | Cap | Where |
| --- | --- | --- |
| TinyFish search | 11k/day (free 12k) | Redis counter, `PRODUCER_TINYFISH_INTERVAL_S` |
| TinyFish fetch | 900/day (free 1k) | Redis counter, JS-shell fallback only |
| SubQ decisions | 30/min + 402 breaker (30min pause) | `SUBQ_MAX_RPM`, in-code breaker |
| Gemini embeds | batch 32, 4 workers | API-side quota is your ceiling |
| LLM (GeneralCompute) | local semaphore 4 | intel scripts only, not the hot path |
| Redis memory | 4 GB maxmemory, allkeys-lru | compose; floods degrade to misses |

## 7. Residual risks (accepted, not ignored)

- **Hostile page content.** The crawler fetches attacker-controlled HTML/JS. Containment: everything runs as unprivileged `hosvc` (pipeline) or stock images, no host mounts except the docker socket — which the pipeline container does NOT get. Markdown extraction strips scripts/styles, but treat stored JD text as untrusted input to any future LLM prompt (SubQ decisions today are classification-only, low prompt-injection surface; keep generation prompts constrained when matching ships).
- **Playwright CVEs.** Browsers render hostile pages by design. Mitigation: ATS/workday JSON paths bypass the browser for most volume; Chromium runs sandboxed defaults. Keep base images updated (`docker compose pull` monthly).
- **Credential rotation** needs the pg/neo4j dance in section 2.
- **Single box** = single point of failure. Backups + snapshots are the HA plan until traffic justifies otherwise.
