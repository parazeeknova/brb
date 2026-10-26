# syntax=docker/dockerfile:1
FROM oven/bun:1.4.3 AS bun
FROM node:26-bookworm-slim
WORKDIR /app
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
RUN ln -s /usr/local/bin/bun /usr/local/bin/bunx
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/package.json
COPY packages/db/package.json packages/db/package.json
RUN bun install --filter '@brb/db' --frozen-lockfile --ignore-scripts
COPY packages/db packages/db
COPY scripts/ci/prisma-sync.sh scripts/ci/prisma-sync.sh
RUN cd packages/db && bunx prisma contract emit && bunx prisma migration check && bunx prisma db migrate --show --from @empty --to @contract
ARG VITE_RELEASE_SHA=development
ENV BRB_RELEASE_SHA=${VITE_RELEASE_SHA} NODE_ENV=production
RUN chmod +x scripts/ci/prisma-sync.sh && chown -R node:node /app
USER node
ENTRYPOINT ["/app/scripts/ci/prisma-sync.sh"]
