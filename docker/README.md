# BRB production

The landing page is served at **https://jobs.amemorymachine.cc**. It is currently independent of the ingest corpus.

## Individual Dokploy services

All services live under **BRB → production** and have separate environment settings, logs, resource controls and deploy/restart actions:

| Service | Dokploy type | Image | Access |
| --- | --- | --- | --- |
| BRB Web | Application | `ghcr.io/parazeeknova/brb-web` | HTTPS domain, internal port 3000 |
| Ingest · BRB | Application | `ghcr.io/parazeeknova/brb-ingest` | Private `/healthz` and `/readyz`, port 8080 |
| Postgres · BRB | PostgreSQL | `pgvector/pgvector:pg18` | Private, port 5432 |
| Redis · BRB | Redis | `redis:8-alpine` | Private, authenticated, port 6379 |
| Neo4j · BRB | Application | `neo4j:5-community` | Private, ports 7474 / 7687 |
| SearXNG · BRB | Application | `searxng/searxng:latest` | Private, port 8080 |

Only BRB Web has a domain. Backend services have no published ports and are detached from `dokploy-network`; they share `brb-backend-private`, an attachable overlay network. SearXNG and ingest retain outbound internet access. There is no duplicate OpenObserve instance.

Database and ingest volumes are persistent. The initial combined stack's volume names are retained so splitting the Dokploy entries does not discard data. Do not remove these volumes when replacing a service. The native Postgres mount is `/var/lib/postgresql`, as required by the PostgreSQL 18 image.

Resource limits and conservative ingest concurrency leave capacity for existing ASM workloads. Postgres and Redis use native Dokploy service controls; Neo4j, SearXNG and ingest are separately managed applications.

## Merge to deployment

1. PR CI validates changes before merging into `main`.
2. The `publish` workflow detects affected images, verifies Dokploy API access, and publishes them to GHCR with immutable `sha-<commit>` tags.
3. After required builds succeed, the deploy job updates only BRB Web and/or Ingest and waits for Dokploy deployment completion. Database and search services are not restarted when web code changes.
4. Web deployment verifies the exact commit in the public page's `brb:revision` metadata. Web rolling updates use health checks and rollback on failure.
5. Environment values saved in Dokploy are preserved; the CI API update changes only the image reference.

GitHub Actions serializes production publish/deploy runs. Independent Git webhook autodeploy in Dokploy is disabled so a merge cannot deploy before images finish. A manual `publish` run on `main` with `rebuild_all=true` rebuilds and deploys both application images.

The API client requires HTTPS, does not follow credential-bearing redirects, checks target project ownership and never prints saved environments. Missing credentials, failed deployments and stale public revisions fail CI.

## Configuration

Repository secret: `DOKPLOY_API_TOKEN`.

Repository variables: `DOKPLOY_API_URL`, `DOKPLOY_PROJECT_ID`, `DOKPLOY_WEB_APP_ID`, `DOKPLOY_INGEST_APP_ID`, and `BRB_WEB_URL`.

Database passwords and the SearXNG secret are generated and stored in Dokploy. Ingest uses internal service hostnames on the private network. OpenObserve credentials are stored only in Ingest's environment. OTLP logs go to `https://o11y.asocialmedia.cc/api/default/v1/logs`, stream `brb_ingest`, service name `brb-ingest`.

External provider keys are intentionally empty for now: `GENERALCOMPUTE_API_KEY`, `GEMINI_API_KEY`, `TINY_FISH_API_KEY`, and `SUBQ_API_KEY`. Configure them in **Ingest · BRB → Environment**, then redeploy that application. Infrastructure readiness does not establish that paid verification, embeddings or enrichment work. The landing page is not connected to the corpus yet.

## Operations

Use each service's Dokploy controls and logs independently. Deployment history identifies each application release by commit. To roll back web or ingest, select a previously published `sha-...` Docker image in that application and deploy; leave database volumes in place.
