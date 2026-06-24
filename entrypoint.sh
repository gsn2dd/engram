#!/bin/bash
# Engram: Postgres+pgvector holds the brain; the MCP server exposes it so any
# MCP-capable agent (OpenClaw, Claude Desktop, ...) can attach to it as memory.
# First boot applies schema.sql via /docker-entrypoint-initdb.d/.
set -e
docker-entrypoint.sh postgres &
PG_PID=$!
echo "Waiting for Postgres..."
until pg_isready -h localhost -U "${POSTGRES_USER}" >/dev/null 2>&1; do sleep 1; done
echo "Postgres ready. Starting Engram MCP server on :${ENGRAM_MCP_PORT:-8080}/sse"
export DB_NAME="${POSTGRES_DB}" DB_USER="${POSTGRES_USER}" DB_PASS="${POSTGRES_PASSWORD}" DB_HOST=localhost
python3 mcp_server.py &
APP_PID=$!

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

wait -n "$PG_PID" "$APP_PID"
