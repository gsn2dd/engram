#!/bin/bash
# Smoke test — runs ON a freshly launched Engram instance.
#
#   python3 -c "import json;json.dump({'commands':[open('smoke-test.sh').read()]},
#                                     open('/tmp/p.json','w'))"
#   aws ssm send-command --instance-ids i-xxxx \
#       --document-name AWS-RunShellScript --parameters file:///tmp/p.json
#
# The JSON file is not fussiness: `--parameters commands="$(cat smoke-test.sh)"`
# cannot carry a multi-line script containing quotes and commas — the CLI's
# shorthand parser chokes on it.
#
# Or just paste it into a Session Manager shell.
#
# Checks the things that would embarrass us in a Marketplace review or a
# customer's first hour. Prints PASS/FAIL per check and exits non-zero if any
# failed, so it can gate a release.

PASS=0
FAIL=0

ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
check() { if [ "$1" = "0" ]; then ok "$2"; else bad "$2"; fi; }

echo "=== Engram instance smoke test — $(date -u +%FT%TZ)"
echo
echo "-- service"

systemctl is-active --quiet engram-firstboot.service
check $? "engram-firstboot.service completed"

systemctl is-active --quiet engram.service
check $? "engram.service is active"

# "active" is not "healthy". A crash-looping unit is active for a second or two
# after each restart, which is long enough for the port and database checks
# below to pass and report a working instance. That happened: the first real
# test run reported 13 passes against a container restarting every 10 seconds.
restarts="$(systemctl show engram.service -p NRestarts --value 2>/dev/null)"
if [ "${restarts:-0}" -le 2 ]; then
    ok "engram.service is stable (${restarts:-0} restarts)"
else
    bad "engram.service has restarted ${restarts} times — it is crash-looping"
    echo "  ---   journalctl -u engram.service -n 40"
fi

# Independent of systemd's view: has one container actually stayed up?
uptime_s="$(docker inspect engram --format '{{.State.StartedAt}}' 2>/dev/null)"
if [ -n "$uptime_s" ]; then
    started=$(date -d "$uptime_s" +%s 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - started ))
    [ "$age" -ge 60 ] && ok "container has been up ${age}s" \
                      || bad "container is only ${age}s old — restarting?"
else
    bad "no running engram container"
fi

# Give the container a moment on a cold instance before probing ports.
for _ in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q ':8080' && break
    sleep 2
done

echo
echo "-- credentials (the checks that matter most)"

if [ -f /etc/engram/engram.env ]; then
    ok "/etc/engram/engram.env exists"
    perms="$(stat -c '%a' /etc/engram/engram.env)"
    [ "$perms" = "600" ] && ok "env file is mode 600" || bad "env file is mode ${perms}, expected 600"

    if grep -q '^POSTGRES_PASSWORD=pathpass$' /etc/engram/engram.env; then
        bad "DATABASE PASSWORD IS THE SHIPPED DEFAULT 'pathpass' — hard blocker"
    else
        ok "database password is not the shipped default"
    fi

    pw="$(grep '^POSTGRES_PASSWORD=' /etc/engram/engram.env | cut -d= -f2-)"
    [ "${#pw}" -ge 24 ] && ok "database password is ${#pw} chars" \
                        || bad "database password is only ${#pw} chars"

    tok="$(grep '^ENGRAM_INGEST_TOKEN=' /etc/engram/engram.env | cut -d= -f2-)"
    [ "${#tok}" -ge 24 ] && ok "ingest token is ${#tok} chars" \
                         || bad "ingest token is only ${#tok} chars"

    # Print a fingerprint, never the secret. Two instances must differ here —
    # a shared credential across every customer is the failure this whole
    # first-boot mechanism exists to prevent.
    echo "  ---   password fingerprint: $(printf '%s' "$pw" | sha256sum | cut -c1-16)"
    echo "  ---   token    fingerprint: $(printf '%s' "$tok" | sha256sum | cut -c1-16)"
    echo "  ---   (launch a second instance; these two lines MUST differ)"
else
    bad "/etc/engram/engram.env is missing — first boot did not run"
fi

echo
echo "-- network exposure"

if ss -ltn 2>/dev/null | grep -q '0.0.0.0:5432\|\[::\]:5432'; then
    bad "Postgres 5432 is published beyond the container — must never be"
else
    ok "Postgres 5432 is not publicly bound"
fi

for port in 8080 8081; do
    line="$(ss -ltn 2>/dev/null | grep ":${port}" | head -1)"
    if [ -z "$line" ]; then
        bad "nothing listening on ${port}"
    elif echo "$line" | grep -q '127.0.0.1'; then
        ok "${port} bound to loopback only"
    else
        bad "${port} is bound beyond loopback: ${line}"
    fi
done

echo
echo "-- ingest endpoint"

code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/health 2>/dev/null)"
[ "$code" = "200" ] && ok "health returns 200" || bad "health returned '${code}'"

code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8081/ \
        -H 'Content-Type: application/json' -d '{"prompt":"x","answer":"y"}' 2>/dev/null)"
[ "$code" = "401" ] && ok "rejects a post with no token" || bad "no-token post returned '${code}', expected 401"

if [ -n "${tok:-}" ]; then
    code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8081/ \
            -H "Authorization: Bearer ${tok}" -H 'Content-Type: application/json' \
            -d '{}' 2>/dev/null)"
    [ "$code" = "200" ] && ok "accepts the instance token" || bad "token post returned '${code}', expected 200"
fi

echo
echo "-- MCP endpoint auth"

# The MCP endpoint must demand this instance's generated bearer token. An open
# endpoint here means first-boot did not write ENGRAM_MCP_TOKEN or the server
# ignored it — either way the brain is one port-forward away from anyone.
mtok="$(sudo grep '^ENGRAM_MCP_TOKEN=' /etc/engram/engram.env 2>/dev/null | cut -d= -f2-)"
if [ -z "$mtok" ]; then
    bad "no ENGRAM_MCP_TOKEN in engram.env"
else
    [ "${#mtok}" -ge 24 ] && ok "MCP token is ${#mtok} chars" \
                          || bad "MCP token is only ${#mtok} chars"
    echo "  ---   MCP token fingerprint: $(printf '%s' "$mtok" | sha256sum | cut -c1-16)"

    code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/sse 2>/dev/null)"
    [ "$code" = "401" ] && ok "MCP rejects an unauthenticated request" \
                        || bad "unauthenticated /sse returned '${code}', expected 401"

    code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer definitely-not-the-token-0000" \
            http://127.0.0.1:8080/sse 2>/dev/null)"
    [ "$code" = "401" ] && ok "MCP rejects a wrong token" \
                        || bad "wrong-token /sse returned '${code}', expected 401"

    # A correct token opens an SSE stream that never ends; curl's timeout is
    # the read mechanism, not a failure. --max-time 3 + the status line is
    # enough to prove the gate passed it through.
    code="$(curl -sS -m 3 -o /dev/null -w '%{http_code}' -N \
            -H "Authorization: Bearer ${mtok}" \
            http://127.0.0.1:8080/sse 2>/dev/null)"
    [ "$code" = "200" ] && ok "MCP accepts the instance token" \
                        || bad "instance-token /sse returned '${code}', expected 200"
fi

echo
echo "-- brain state"

empty="$(docker exec engram psql -U pathuser -d pathmemoria -At \
         -c 'SELECT count(*) FROM memories;' 2>/dev/null)"
if [ -z "$empty" ]; then
    bad "could not query the brain"
elif [ "$empty" = "0" ]; then
    ok "brain starts empty (demo seed is off)"
else
    bad "brain has ${empty} rows on a fresh instance — demo seed left on?"
fi

echo
echo "-- image hygiene"

[ -s /home/ec2-user/.ssh/authorized_keys ] 2>/dev/null \
    && echo "  ---   authorized_keys present (expected if you launched with a key pair)" \
    || ok "no stale authorized_keys baked into the image"

grep -qs '^PasswordAuthentication no' /etc/ssh/sshd_config.d/60-engram-hardening.conf
check $? "password authentication is disabled"

echo
echo "=== ${PASS} passed, ${FAIL} failed"
echo
echo "Not covered here — do these by hand:"
echo "  * reboot, re-run: brain survives and first-boot does NOT regenerate config"
echo "  * launch a second instance and compare the fingerprints above"
echo "  * port-scan from another host in the VPC and see nothing"

[ "$FAIL" -eq 0 ]
