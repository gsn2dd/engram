#!/bin/bash
# engram-security-watch — is this server missing security updates?  (2026-10-23)
#
# WHY: Amazon Linux 2023 pins every instance to the release it was built from.
# Nothing ever told anyone that "dnf upgrade" had silently stopped bringing
# fixes: the server the AMI was developed on sat on its May release for five
# months, 529 security advisories behind, and only found out when a critical
# PHP remote-code-execution fix was announced and someone went to apply it.
# An agent server that keeps its owner's memory must keep itself patched, and
# must SAY so -- in the login banner and to the agent at the start of every chat.
#
# Runs as root from engram-security-watch.timer (daily + shortly after boot).
# Writes a one-line verdict anyone can read, plus details:
#   /var/lib/engram/security-status.txt    one line, read by the banner and the agent
#   /var/lib/engram/security-status.json   counts, releases, critical packages
# Read-only on the system: it never installs anything (`update_server` does).
set -uo pipefail

OUT=/var/lib/engram
mkdir -p "$OUT"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"

INSTALLED="$(rpm -q --qf '%{VERSION}' system-release 2>/dev/null)"
LATEST="$(dnf check-release-update 2>&1 | grep -oE 'Version 2023\.[0-9.]+' | awk '{print $2}' | sort -V | tail -1)"
[ -z "$LATEST" ] && LATEST="$INSTALLED"

# Advisories that apply to installed packages, judged against the NEWEST release
# (judging against the pinned one is exactly what hid the gap).
ADV="$(dnf -q --releasever=latest updateinfo list --security 2>/dev/null)"
count() { printf '%s\n' "$ADV" | awk -v s="$1" '$2==s' | wc -l; }
CRIT=$(count "Critical/Sec.")
IMP=$(count "Important/Sec.")
OTHER=$(( $(printf '%s\n' "$ADV" | grep -c 'Sec\.') - CRIT - IMP ))
CRIT_PKGS="$(printf '%s\n' "$ADV" | awk '$2=="Critical/Sec."{print $3}' \
             | sed -E 's/-[0-9][^-]*-[^-]*$//' | sort -u | head -10 | paste -sd, -)"

REBOOT=no
needs-restarting -r >/dev/null 2>&1 || REBOOT=yes

if [ "$CRIT" -eq 0 ] && [ "$IMP" -eq 0 ] && [ "$REBOOT" = no ]; then
    LINE="SERVER SECURITY: up to date (checked $NOW)."
else
    LINE="SERVER SECURITY: ${CRIT} critical and ${IMP} important security updates are waiting"
    [ "$CRIT" -gt 0 ] && LINE="$LINE (critical: ${CRIT_PKGS})"
    LINE="$LINE. Installed release ${INSTALLED}, newest ${LATEST}."
    [ "$REBOOT" = yes ] && LINE="$LINE A reboot is needed to finish earlier updates."
    LINE="$LINE Fix: type update_server (checked $NOW)."
fi

printf '%s\n' "$LINE" > "$OUT/security-status.txt.new" && mv "$OUT/security-status.txt.new" "$OUT/security-status.txt"
cat > "$OUT/security-status.json.new" <<EOF
{"checked": "$NOW", "installed_release": "$INSTALLED", "latest_release": "$LATEST",
 "critical": $CRIT, "important": $IMP, "other": $OTHER, "reboot_needed": "$REBOOT",
 "critical_packages": "$CRIT_PKGS"}
EOF
mv "$OUT/security-status.json.new" "$OUT/security-status.json"
chmod 0644 "$OUT/security-status.txt" "$OUT/security-status.json"
echo "$LINE"
