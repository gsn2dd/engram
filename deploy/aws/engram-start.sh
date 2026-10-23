#!/bin/bash
# start — the one word a first-time customer types (README.txt in their home).
#
# WHY: the Marketplace buyer may be someone who has never used a terminal --
# the test case is "download PuTTY, log in with these details, type start"
# (David, 2026-10-23). The existing pieces (engram-help, install_claude_code,
# /etc/engram/engram.env) each assume you already know which one you need.
# This walks the steps in order and skips whatever is already done, so the
# same word works on day one and every day after: once set up, `start` just
# opens the assistant.
#
# Never echoes a key: it is read with `read -s` and written straight to the
# root-only env file. A terminal is an over-the-shoulder surface.
set -uo pipefail

ENV_FILE=/etc/engram/engram.env
RUNTIME_ENV=/run/engram/secrets.env
B=$'\033[1m'; N=$'\033[0m'

have() { sudo grep -qE "^$1=.+" "$ENV_FILE" 2>/dev/null || grep -qE "^$1=.+" "$RUNTIME_ENV" 2>/dev/null; }

if [ "$(id -u)" = "0" ]; then
    echo "Please run start as your normal login user, not root."
    exit 1
fi

# ---- 1. Memory key -------------------------------------------------------
if ! { have GEMINI_API_KEY || have OPENAI_API_KEY; }; then
    cat <<EOF

${B}Step 1 of 2 — give your assistant a memory${N}

Its memory needs one free key from Google, used to file and find memories.
  1. On your computer or phone, open:   ${B}https://aistudio.google.com/apikey${N}
  2. Sign in with a Google account and press "Create API key".
  3. Copy the key. Here in PuTTY, right-click pastes it.

Nothing is shown while you paste: that is on purpose. Press Enter when done.
EOF
    read -r -s -p "Paste your Google key: " KEY; echo
    KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
    if [ ${#KEY} -lt 20 ]; then
        echo "That doesn't look like a key (too short). Type start to try again."
        exit 1
    fi
    sudo sed -i '/^GEMINI_API_KEY=/d; /^ENGRAM_EMBED_PROVIDER=/d' "$ENV_FILE"
    printf 'GEMINI_API_KEY=%s\nENGRAM_EMBED_PROVIDER=gemini\n' "$KEY" | sudo tee -a "$ENV_FILE" >/dev/null
    unset KEY
    echo "Saved. Restarting the memory service..."
    sudo systemctl restart engram
    for _ in $(seq 1 30); do
        systemctl is-active --quiet engram && break
        sleep 2
    done
    if systemctl is-active --quiet engram; then
        echo "${B}Memory is ready.${N}"
    else
        echo "The memory service did not come back. Type get_started for help."
        exit 1
    fi
fi

# ---- 2. The assistant ----------------------------------------------------
if ! command -v claude >/dev/null 2>&1; then
    cat <<EOF

${B}Step 2 of 2 — install your assistant (Claude)${N}

This downloads Claude Code from Anthropic onto your server and connects it to
the memory. You will need a Claude account: a Pro or Max plan, or an API key.
Anthropic shows you their terms when you sign in.
EOF
    read -r -p "Install it now? [Y/n] " OK
    case "${OK:-y}" in
        [nN]*) echo "No problem. Type start again when you're ready."; exit 0 ;;
    esac
    install_claude_code || { echo "The install stopped. Type get_started for help."; exit 1; }
    hash -r
    export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
fi

# ---- 3. Talk to it -------------------------------------------------------
cat <<EOF

${B}Opening your assistant.${N} The first time, it asks you to sign in to Claude:
follow the link it shows. Then just talk to it, for example:
   "Hello! I'm <your name>. I'd like help with <what you do>."
Leave with /exit.

EOF
cd "$HOME" && exec claude
