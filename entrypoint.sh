#!/bin/bash
# Engram: Postgres+pgvector holds the brain; the MCP server exposes it so any
# MCP-capable agent (OpenClaw, Claude Desktop, ...) can attach to it as memory.
# schema.sql is applied on EVERY start, not only at initdb.
set -e
docker-entrypoint.sh postgres &
PG_PID=$!
echo "Waiting for Postgres..."
until pg_isready -h localhost -U "${POSTGRES_USER}" >/dev/null 2>&1; do sleep 1; done

# Apply the schema on every start. /docker-entrypoint-initdb.d only runs when
# PGDATA is EMPTY, so on the AMI — where the data directory is a persistent bind
# mount — pulling a newer image and restarting never migrated anything. The
# container came up against an old schema and every write failed on a missing
# column, while schema.sql's own comments promised that re-running it upgrades an
# existing brain. Nothing was running it. Safe to repeat: every statement is
# guarded with IF NOT EXISTS or a duplicate-object catch.
echo "Applying schema (idempotent)..."
if ! psql -v ON_ERROR_STOP=1 -h localhost -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -q -f /app/schema.sql; then
    echo "FATAL: schema could not be applied; refusing to start against an" >&2
    echo "       unmigrated database rather than failing every write later." >&2
    exit 1
fi
echo "Postgres ready. Starting Engram MCP server on :${ENGRAM_MCP_PORT:-8080}/sse"
export DB_NAME="${POSTGRES_DB}" DB_USER="${POSTGRES_USER}" DB_PASS="${POSTGRES_PASSWORD}" DB_HOST=localhost
python3 mcp_server.py &
APP_PID=$!

# Ingest endpoint for the Engram Capture browser extension. Starts ONLY when a
# token is set — an unauthenticated ingest surface must never appear by default.
# This is the endpoint a customer's extension points at; without it the
# extension has nothing to talk to but a private, hand-built AWS pipeline.
if [ -n "${ENGRAM_INGEST_TOKEN:-}" ]; then
  echo "Starting Engram ingest endpoint on :${ENGRAM_INGEST_PORT:-8081}"
  python3 ingest_server.py &
  INGEST_PID=$!
else
  echo "ENGRAM_INGEST_TOKEN unset — browser-capture ingest endpoint disabled"
  INGEST_PID=""
fi

# Starter brain: engram's own documentation, stored as memories. On by default,
# because an empty brain is both a poor first impression and a slightly broken
# one — recall returns nothing and every threshold in the engine was fitted to a
# corpus that does not exist yet. Scoped to the `engram-guide` project so it can
# be removed wholesale with `pm forget-project engram-guide --yes`.
# Skips itself silently when no embedding key is configured, which is the normal
# state on a first boot of the published image.
# Retried on the consolidation loop, not just at boot: the published image ships
# with no embedding key, so the first attempt always skips. Without a retry the
# starter brain would only ever appear if the customer happened to restart the
# container after adding a key — and the documentation would be describing
# something that never happens. seed_starter is idempotent and returns
# immediately once seeded, so the retry costs nothing.
if [ "${ENGRAM_SEED_STARTER:-1}" != "0" ]; then
  (
    sleep 4
    python3 seed_starter.py 2>&1 | sed 's/^/[starter] /'
    while true; do
      sleep "${ENGRAM_SEED_RETRY_INTERVAL:-600}"
      python3 seed_starter.py >/dev/null 2>&1 && break
    done
  ) &
fi

# Optionally seed a small demo brain on first boot, so "try it" isn't an empty
# box. Idempotent + uses your keys. Set ENGRAM_SEED_DEMO=0 for a clean brain.
if [ "${ENGRAM_SEED_DEMO:-0}" = "1" ] || [ "${ENGRAM_SEED_DEMO:-0}" = "true" ]; then
  ( sleep 3; python3 seed_demo.py 2>&1 | sed 's/^/[demo] /' ) &
fi

# Self-organising loop: periodically compact raw co-recall edges into the path
# graph (which spreading-activation reads) and decay/prune unused nodes + edges.
# This is what makes recall strengthen with use and fade with neglect over time.
# Interval is configurable; default 1h.
(
  while true; do
    sleep "${ENGRAM_CONSOLIDATE_INTERVAL:-3600}"
    python3 cli/pm.py consolidate >/dev/null 2>&1 || true
  done
) &

# Exit if any of the long-lived services dies, so Docker's restart policy sees
# the failure instead of the container limping on with a dead component.
wait -n "$PG_PID" "$APP_PID" ${INGEST_PID:+"$INGEST_PID"}
