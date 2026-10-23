#!/bin/bash
# Login banner for the Engram AMI — deliberately SHORT.
#
# A full setup guide printed on every login is noise from the second login
# onwards, and people stop reading banners that are always the same length.
# This prints a status line, the ONE thing to do next if anything is missing,
# and where to get the rest. `engram-help` carries the full guide.
#
# Never prints a secret: it reports whether a key is present, never its value.
# A login banner is the most over-the-shoulder-read surface on a server.

ENV_FILE=/etc/engram/engram.env
RUNTIME_ENV=/run/engram/secrets.env

have() { sudo grep -qE "^$1=.+" "$ENV_FILE" 2>/dev/null || grep -qE "^$1=.+" "$RUNTIME_ENV" 2>/dev/null; }

RUNNING=stopped
systemctl is-active --quiet engram 2>/dev/null && RUNNING=running
EMBED=missing
{ have GEMINI_API_KEY || have OPENAI_API_KEY; } && EMBED=set
COUNT="$(docker exec engram psql -U pathuser -d pathmemoria -At \
         -c 'SELECT count(*) FROM memories' 2>/dev/null)"

printf '\n\033[1mEngram\033[0m — a memory brain your AI agent attaches to\n'
printf '  service %s · embedding key %s · %s memories\n\n' \
    "$RUNNING" "$EMBED" "${COUNT:-?}"

if [ "$EMBED" = "missing" ]; then
    printf '  \033[1mNothing can be stored yet — it needs an embedding key.\033[0m\n'
    printf '  New here? Read README.txt, or just type:\n\n'
    printf '      \033[1mstart\033[0m           step-by-step setup, then your assistant opens\n'
    printf '      \033[1mget_started\033[0m     the full guide (keys, agents, troubleshooting)\n\n'
elif [ "$RUNNING" != "running" ]; then
    printf '  Service is not running:  sudo systemctl status engram\n\n'
    printf '      \033[1mget_started\033[0m     setup and troubleshooting\n\n'
else
    printf '      \033[1mstart\033[0m           open your assistant\n'
    printf '      \033[1mget_started\033[0m     connect an agent, capture conversations, tune it\n\n'
fi
