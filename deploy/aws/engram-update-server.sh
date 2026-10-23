#!/bin/bash
# update_server — install the waiting security updates, with the owner's OK.  (2026-10-23)
#
# Moves the server to the NEWEST Amazon Linux release (`--releasever=latest`):
# a plain `dnf upgrade` stays on the release the server was built from and
# quietly stops getting fixes, which is the whole reason this command exists.
# Asks first, says how long it takes, and offers the reboot only if one is
# needed. Your memories live in /var/lib/engram and are not touched.
set -uo pipefail
B=$'\033[1m'; N=$'\033[0m'

sudo /usr/local/bin/engram-security-watch >/dev/null 2>&1
echo
cat /var/lib/engram/security-status.txt 2>/dev/null
echo
if grep -q "up to date" /var/lib/engram/security-status.txt 2>/dev/null; then
    echo "Nothing to do."
    exit 0
fi
cat <<EOF
This installs all waiting updates from Amazon. It usually takes 5-15 minutes.
Your assistant and its memory keep running during the install; a reboot (about
2 minutes, you will be disconnected) may be needed at the end.
${B}Tip:${N} for a safety net, take a snapshot of this server's disk in the AWS
console first (EC2 > Volumes > Actions > Create snapshot).
EOF
read -r -p "Install the updates now? [y/N] " OK
case "$OK" in [yY]*) ;; *) echo "OK, nothing changed."; exit 0 ;; esac

sudo dnf upgrade -y --releasever=latest || { echo "The update stopped with an error (shown above). Nothing was rebooted."; exit 1; }
sudo /usr/local/bin/engram-security-watch
if ! sudo needs-restarting -r >/dev/null 2>&1; then
    read -r -p "A reboot is needed to finish. Reboot now? [y/N] " RB
    case "$RB" in [yY]*) echo "Rebooting. Log in again in about 2 minutes."; sudo systemctl reboot ;; *) echo "Remember to reboot soon: sudo reboot" ;; esac
fi
