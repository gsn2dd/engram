#!/bin/bash
# Engram AMI provisioning — turns a clean Amazon Linux 2023 instance into the
# golden image published to AWS Marketplace.
#
# Runs ONCE, at build time, as root (delivered via EC2 user-data by
# build-ami.sh). It must leave the box in a state that passes the AWS
# Marketplace AMI scan:
#
#   - supported, patched OS (AL2023)
#   - no password authentication
#   - no baked-in credentials, keys, or history
#   - no listening service reachable from the internet by default
#
# On success the script powers the instance off. `stopped` is the build
# script's success signal — if provisioning fails the box stays UP so it can be
# inspected. Do not "helpfully" add a shutdown to the failure path.

set -euo pipefail

ENGRAM_IMAGE="${ENGRAM_IMAGE:-ghcr.io/gsn2dd/engram:latest}"
LOG=/var/log/engram-provision.log
exec > >(tee -a "$LOG") 2>&1

echo "=== engram provision starting $(date -u +%FT%TZ) — image ${ENGRAM_IMAGE}"

# ---------------------------------------------------------------- packages ---
dnf -y update
dnf -y install docker jq
systemctl enable docker
systemctl start docker

# Bake the image into the AMI so a customer's first boot has no dependency on
# ghcr.io being reachable. A Marketplace instance that needs egress to start is
# a support ticket waiting to happen.
docker pull "${ENGRAM_IMAGE}"
docker tag "${ENGRAM_IMAGE}" engram:baked

# ------------------------------------------------------------ filesystem ----
install -d -m 0700 /etc/engram
install -d -m 0700 /var/lib/engram/pgdata

# Record which image the AMI was built from — the Marketplace listing has to
# state a version, and support questions start with "which build is this?".
cat > /etc/engram/build-info <<EOF
image=${ENGRAM_IMAGE}
built_at=$(date -u +%FT%TZ)
base=amazon-linux-2023
EOF
chmod 0644 /etc/engram/build-info

# ------------------------------------------------------------- first boot ---
# The published image ships a well-known Postgres password (pathpass) for local
# `docker compose up` convenience. That is fine on a laptop and NOT fine in a
# Marketplace AMI, where a shared default credential across every customer is a
# hard policy failure. Generate a unique one on each customer's first boot.
cat > /usr/local/bin/engram-firstboot.sh <<'FIRSTBOOT'
#!/bin/bash
set -euo pipefail
ENV_FILE=/etc/engram/engram.env

# Idempotent: only the very first boot after launch creates the config.
if [ -f "$ENV_FILE" ]; then
    echo "engram: config already present, nothing to do"
    exit 0
fi

# CloudFormation drops the parameter path here via UserData. Standalone
# launches have no such file, and simply run without SSM.
SSM_PREFIX="$(cat /etc/engram/ssm-prefix 2>/dev/null || true)"

PG_PASS="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
INGEST_TOKEN="$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)"
MCP_TOKEN="$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)"

cat > "$ENV_FILE" <<EOF
# Generated on first boot — unique to this instance. Do not copy between hosts.
POSTGRES_DB=pathmemoria
POSTGRES_USER=pathuser
POSTGRES_PASSWORD=${PG_PASS}

# Ship a clean brain of the customer's own data. The DEMO seed is sample content
# for a laptop try-out and has no business on a paid instance.
ENGRAM_SEED_DEMO=0

# The STARTER brain is different and stays on: it is engram's own documentation
# stored as memories, so the first question a customer asks returns a real
# answer and demonstrates semantic recall at the same time. It waits for an
# embedding key, so it appears once the customer configures one rather than at
# first boot. Remove it any time with:
#   docker exec engram python3 cli/pm.py forget-project engram-guide --yes
ENGRAM_SEED_STARTER=1

# Consolidation interval (seconds) for the decay/strengthen loop.
ENGRAM_CONSOLIDATE_INTERVAL=3600

# The MCP endpoint requires this bearer token — unique to this instance,
# generated here. Attach your agent with:
#     headers: { "Authorization": "Bearer <token>" }
# Read it back with:  sudo grep ENGRAM_MCP_TOKEN /etc/engram/engram.env
# Blank it to run the endpoint open, which is only safe on loopback.
ENGRAM_MCP_TOKEN=${MCP_TOKEN}

# Bind address for the MCP endpoint. Loopback by default even WITH the token:
# a bearer token over plain HTTP on a public interface is a credential in
# cleartext. Reach it over an SSM port-forward or an SSH tunnel, and move off
# loopback only behind TLS (a reverse proxy terminating HTTPS).
ENGRAM_BIND=127.0.0.1

# Ingest endpoint for the Engram Capture browser extension. This token IS the
# credential the extension sends — unique to this instance, generated here.
# Read it back with:  sudo grep ENGRAM_INGEST_TOKEN /etc/engram/engram.env
ENGRAM_INGEST_TOKEN=${INGEST_TOKEN}
ENGRAM_INGEST_PORT=8081

# Unlike the MCP port this endpoint DOES authenticate, so it is the one that
# may reasonably be exposed — but only behind TLS. A bearer token over plain
# HTTP on a public interface is a token in cleartext. Loopback by default;
# reach it through the same SSM port-forward and point the extension at
# http://localhost:8081.
ENGRAM_INGEST_BIND=127.0.0.1

# Where to look for keys in AWS Parameter Store. Set this and engram fetches
# GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / ENGRAM_EMBED_PROVIDER
# from <prefix>/<NAME> at every start, into memory only — the secret
# never touches this disk and never enters an EBS snapshot. Empty = use the keys
# written below instead.
ENGRAM_SSM_PREFIX=${SSM_PREFIX}

# Embedding provider key. Left empty deliberately — the customer supplies one,
# either here or (preferred) via ENGRAM_SSM_PREFIX above. WITHOUT ONE, NOTHING
# CAN BE STORED: embedding is what turns a memory into something recallable.
GEMINI_API_KEY=
OPENAI_API_KEY=

# Optional. Enables subject classification, multi-angle indexing and the
# consolidation pass. Engram stores and recalls without it.
ANTHROPIC_API_KEY=
EOF
chmod 0600 "$ENV_FILE"
echo "engram: generated instance-unique database credentials"
FIRSTBOOT
chmod 0755 /usr/local/bin/engram-firstboot.sh

# Key fetch + login message. Written from the files kept in the repo so they are
# reviewable and diffable rather than buried in a heredoc.
install -m 0755 /tmp/engram-fetch-keys.sh /usr/local/bin/engram-fetch-keys.sh 2>/dev/null || \
    echo "engram: fetch-keys helper not staged; SSM key loading unavailable" >&2
install -m 0755 /tmp/engram-welcome.sh /etc/profile.d/engram-welcome.sh 2>/dev/null || \
    echo "engram: welcome message not staged" >&2
# The full guide is a command, not a banner: printed on demand, so the login
# message can stay short enough that people keep reading it.
install -m 0755 /tmp/engram-help.sh /usr/local/bin/engram-help 2>/dev/null || \
    echo "engram: help command not staged" >&2
install -m 0644 /tmp/engram-aliases.sh /etc/profile.d/engram-aliases.sh 2>/dev/null || \
    echo "engram: aliases not staged" >&2
# Claude Code is installed ON DEMAND by the customer, never baked into the
# image — the script's header explains the licensing reasoning.
install -m 0755 /tmp/engram-claude-code.sh /usr/local/bin/install_claude_code 2>/dev/null || \
    echo "engram: claude-code installer not staged" >&2

# --------------------------------------------------------------- runtime ----
# A wrapper rather than a long ExecStart: the bind address has to be read from
# config at start time, and systemd's variable expansion inside a larger
# argument is a well-known source of silent breakage.
cat > /usr/local/bin/engram-run.sh <<'RUNNER'
#!/bin/bash
set -euo pipefail
# shellcheck disable=SC1091
set -a; . /etc/engram/engram.env; set +a

# Pull keys from Parameter Store into a tmpfs file before the container starts.
# No-ops when no prefix is configured, so a box using keys in engram.env is
# unaffected.
[ -x /usr/local/bin/engram-fetch-keys.sh ] && /usr/local/bin/engram-fetch-keys.sh || true
RUNTIME_ENV=/run/engram/secrets.env
[ -s "$RUNTIME_ENV" ] || RUNTIME_ENV=/dev/null

BIND="${ENGRAM_BIND:-127.0.0.1}"
INGEST_BIND="${ENGRAM_INGEST_BIND:-127.0.0.1}"

exec /usr/bin/docker run --rm --name engram \
    --env-file /etc/engram/engram.env \
    --env-file "$RUNTIME_ENV" \
    -v /var/lib/engram/pgdata:/var/lib/postgresql/data \
    -p "${BIND}:8080:8080" \
    -p "${INGEST_BIND}:8081:8081" \
    --health-cmd 'python3 -c "import socket,sys; s=socket.create_connection((\"127.0.0.1\",8080),2); s.close()" || exit 1' \
    --health-interval 30s \
    engram:baked
RUNNER
chmod 0755 /usr/local/bin/engram-run.sh

cat > /etc/systemd/system/engram-firstboot.service <<'EOF'
[Unit]
Description=Engram first-boot configuration (instance-unique credentials)
After=network-online.target
Wants=network-online.target
Before=engram.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/engram-firstboot.sh

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/engram.service <<'EOF'
[Unit]
Description=Engram — persistent memory brain for AI agents
Requires=docker.service engram-firstboot.service
After=docker.service engram-firstboot.service

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker rm -f engram
ExecStart=/usr/local/bin/engram-run.sh
ExecStop=/usr/bin/docker stop -t 30 engram
Restart=always
RestartSec=10
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable engram-firstboot.service engram.service

# --------------------------------------------------------------- hardening --
# AL2023 already defaults to key-only SSH; state it explicitly so the scan sees
# it and so a future base-image change can't silently regress it.
cat > /etc/ssh/sshd_config.d/60-engram-hardening.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
EOF

# Postgres is reachable only from inside the container network. Nothing should
# publish 5432, but make the intent explicit for anyone reading the image.
echo "# engram: 5432 is deliberately never published outside the container" \
    > /etc/engram/PORTS

# ----------------------------------------------------------------- cleanup ---
# Everything below exists to make the snapshot clean. A Marketplace AMI that
# ships an authorized_keys file or a build log with an account id in it fails
# review.
cloud-init clean --logs || true
rm -rf /var/lib/cloud/instances/* /var/lib/cloud/data/*
rm -f /home/ec2-user/.ssh/authorized_keys /root/.ssh/authorized_keys
rm -f /home/ec2-user/.bash_history /root/.bash_history
rm -f /etc/ssh/ssh_host_*                       # regenerated on first boot
rm -rf /var/log/engram-provision.log
find /var/log -type f -exec truncate -s 0 {} \; || true
dnf clean all

sync
echo "=== engram provision complete — powering off (this is the success signal)"
shutdown -h now
