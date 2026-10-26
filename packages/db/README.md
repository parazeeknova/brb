# BRB database migrations

Prisma CLI and the PostgreSQL ORM have independent release versions. Both are pinned to published RC releases in this workspace and resolved by `bun.lock`.

`src/prisma/contract.prisma` manages the four shared corpus tables. Its native types, defaults and nullability match ingest's SQL. Operational tables, existing indexes and vector columns remain owned by ingest and are preserved. Move them into the contract explicitly before changing their ownership.

After editing the contract, run from this directory:

```sh
bun run contract:emit
bun run db:plan --name describe_the_change
bun run db:check
bunx prisma migration show <generated-directory-name>
bun run db:migrate
bun run db:verify
```

Use a development database for planning and local application. Commit the contract, emitted artifacts, reviewed migration package, snapshots and `prisma/migrations/app/refs/db.json`. If editing a generated `migration.ts`, execute it to regenerate its operations before committing. Prisma 8 runs the committed operations, not that TypeScript source.

On main, Actions builds immutable GHCR images, deploys the private **BRB Prisma migrations** app in the production environment, and waits for the new container to exit zero. Only then may web and ingest roll out. Schema/config/history/dependency changes trigger this flow; every app rollout also checks migrations so a previous failed schema deployment cannot be skipped by an apps-only merge. CI and the image build verify both migration integrity and a complete route to the current emitted contract.

The migration app receives only `DATABASE_URL`, connects over BRB's private network, has no domain or published port and does not restart after completion. Its entrypoint checks the graph, previews and applies pending migrations, then verifies the resulting schema. It never auto-plans migrations, resets the database or re-signs it. The initial baseline uses checked create operations that safely adopt matching existing tables; later migrations advance the database marker. Failure blocks the dependent rollout.
