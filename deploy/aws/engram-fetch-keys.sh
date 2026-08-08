#!/bin/bash
# Pull API keys from AWS SSM Parameter Store into the container's environment.
#
# WHY THIS EXISTS: the shipped engram.env has always carried empty key fields and
# a comment recommending Parameter Store — but nothing read from it, so the
# recommendation was decoration and the only real option was hand-editing a file
# on the box. That is a poor first hour for a paid product and it puts the
# customer's secret in a file that lives on the root volume and gets snapshotted
# with it.
#
# Keys are written to a tmpfs file, not to /etc. /run is memory-backed, so the
# secret never reaches disk, never lands in an EBS snapshot, and is gone after a
# reboot — at which point this script simply fetches it again.
#
# Silent no-op when there is no SSM access, no prefix configured, or no
# parameters present: an instance with keys in engram.env must keep working
# exactly as before.

set -uo pipefail

ENV_FILE=/etc/engram/engram.env
RUNTIME_DIR=/run/engram
RUNTIME_ENV="${RUNTIME_DIR}/secrets.env"

# The parameter path is per-instance or per-stack, so one AWS account can run
# several brains without them sharing credentials.
PREFIX="$(grep -E '^ENGRAM_SSM_PREFIX=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"')"
PREFIX="${PREFIX:-${ENGRAM_SSM_PREFIX:-}}"

install -d -m 0700 "$RUNTIME_DIR"
: > "$RUNTIME_ENV"
chmod 0600 "$RUNTIME_ENV"

if [ -z "$PREFIX" ]; then
    echo "engram-fetch-keys: no ENGRAM_SSM_PREFIX set; using keys from engram.env only"
    exit 0
fi
command -v aws >/dev/null 2>&1 || {
    echo "engram-fetch-keys: aws CLI not present; skipping SSM fetch" >&2
    exit 0
}

REGION="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $(
    curl -fsS -m 2 -X PUT http://169.254.169.254/latest/api/token \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)" \
    http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null)"
REGION="${REGION:-${AWS_DEFAULT_REGION:-}}"
[ -n "$REGION" ] && export AWS_DEFAULT_REGION="$REGION"

fetched=0
for NAME in GEMINI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY ENGRAM_EMBED_PROVIDER; do
    VALUE="$(aws ssm get-parameter --name "${PREFIX%/}/${NAME}" --with-decryption \
             --query Parameter.Value --output text 2>/dev/null)" || continue
    [ -z "$VALUE" ] || [ "$VALUE" = "None" ] && continue
    # Written to a file rather than passed as -e arguments: docker run arguments
    # are visible in the process list to every user on the box.
    printf '%s=%s\n' "$NAME" "$VALUE" >> "$RUNTIME_ENV"
    fetched=$((fetched + 1))
done

# Never print the values, only which names were found — this runs into the
# journal, which is readable by more people than the parameter store is.
if [ "$fetched" -gt 0 ]; then
    echo "engram-fetch-keys: loaded $fetched parameter(s) from ${PREFIX%/}/"
else
    echo "engram-fetch-keys: no parameters found under ${PREFIX%/}/"
fi
exit 0
