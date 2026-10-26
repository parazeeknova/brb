#!/usr/bin/env bash
# Corpus backup: pg_dump (custom format) + rotation. Run nightly via cron.
# Usage: ./scripts/backup_corpus.sh [backup_dir]
# Requires: docker, brb-agent-memory-db running, POSTGRES_PASSWORD in env/.env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${1:-$ROOT/backups}"
KEEP=7

if [[ -f "$ROOT/../.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/../.env"
  set +a
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD is not set (env or .env)" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/agent_memory-$STAMP.dump.gz"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" brb-agent-memory-db \
  pg_dump -U postgres -d agent_memory -Fc | gzip > "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Rotation: keep newest $KEEP dumps.
ls -t "$BACKUP_DIR"/agent_memory-*.dump.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "restore: gunzip -c $OUT | docker exec -i -e PGPASSWORD=\$POSTGRES_PASSWORD brb-agent-memory-db pg_restore -U postgres -d agent_memory --clean"
