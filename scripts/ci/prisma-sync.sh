#!/bin/sh
set -eu
cd /app/packages/db
: "${DATABASE_URL:?DATABASE_URL must be set in the private Dokploy migration app}"
# Apply only committed, reviewed migration packages. Never auto-plan, reset or sign.
bunx prisma migration check
bunx prisma db migrate --show
bunx prisma db migrate
bunx prisma db verify
printf 'BRB_MIGRATIONS_OK revision=%s\n' "${BRB_RELEASE_SHA:-development}"
