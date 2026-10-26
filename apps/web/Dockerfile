# syntax=docker/dockerfile:1

FROM oven/bun:latest AS builder
WORKDIR /app

COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
RUN bun install --frozen-lockfile --ignore-scripts

COPY apps/web ./apps/web
ARG VITE_RELEASE_SHA=development
ENV VITE_RELEASE_SHA=${VITE_RELEASE_SHA}
RUN bun run --filter 'brb-web' build

FROM node:25-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0

RUN apk add --no-cache curl \
  && addgroup --system --gid 1001 brb \
  && adduser --system --uid 1001 --ingroup brb brbweb

COPY --from=builder --chown=brbweb:brb /app/apps/web/.output ./
USER brbweb

EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:3000/ || exit 1
CMD ["node", "server/index.mjs"]
