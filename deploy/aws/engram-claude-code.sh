#!/bin/bash
# install_claude_code — put a working, brain-connected Claude Code on this box.
#
# ON DEMAND, NOT BAKED IN — and that is a licensing decision, not a technical
# one. Claude Code is Anthropic's proprietary package; redistributing it inside
# a paid Marketplace image would need rights we do not have. This script ships
# instead: the CUSTOMER fetches the package from npm, on their instance, at
# their own request, accepting Anthropic's terms themselves at install/login —
# the same pattern GPU images use for proprietary drivers. Nothing of
# Anthropic's is inside the AMI.
#
# What it does:
#   1. Installs Node.js (dnf) if missing, then Claude Code from npm.
#   2. Registers this instance's brain as an MCP server, with the
#      instance-unique bearer token, so Claude Code has memory immediately.
#   3. Seeds ~/.claude/CLAUDE.md with the agent prompt that tells the model to
#      actually USE the brain — the most common reason engram "does nothing"
#      is an agent that was never told it has a memory.
#
# Idempotent: safe to re-run; it updates rather than duplicates.
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
    echo "Run this as the login user (ec2-user), not root — Claude Code's"
    echo "config and login belong to the user who will drive it."
    exit 1
fi

echo "== 1/3 Node.js + Claude Code"
if ! command -v node >/dev/null 2>&1; then
    sudo dnf install -y nodejs npm >/dev/null
fi
echo "   node $(node --version)"
# npm prints its own progress; a global install needs root's prefix.
sudo npm install -g @anthropic-ai/claude-code >/dev/null
echo "   claude $(claude --version 2>/dev/null || echo '(installed)')"

echo "== 2/3 connecting Claude Code to this instance's brain"
TOKEN="$(sudo grep '^ENGRAM_MCP_TOKEN=' /etc/engram/engram.env 2>/dev/null | cut -d= -f2- || true)"
if [ -z "$TOKEN" ]; then
    echo "   WARNING: no ENGRAM_MCP_TOKEN in /etc/engram/engram.env —"
    echo "   registering without auth (only valid if you blanked the token)."
    claude mcp remove engram >/dev/null 2>&1 || true
    claude mcp add --transport sse engram http://localhost:8080/sse
else
    claude mcp remove engram >/dev/null 2>&1 || true
    claude mcp add --transport sse engram http://localhost:8080/sse \
        --header "Authorization: Bearer ${TOKEN}"
fi
echo "   registered MCP server 'engram'"

echo "== 3/3 teaching the agent it has a memory"
mkdir -p "$HOME/.claude"
if [ ! -f "$HOME/.claude/CLAUDE.md" ]; then
    # The prompt ships inside the engram container; the AMI has no repo checkout.
    if sudo docker exec engram cat /app/AGENT_PROMPT.md > "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
        echo "   wrote ~/.claude/CLAUDE.md from the engram agent prompt"
    else
        echo "   could not read AGENT_PROMPT.md from the container — is engram running?"
        echo "   (Claude Code still works; paste the prompt from the repo yourself.)"
    fi
else
    echo "   ~/.claude/CLAUDE.md already exists — left untouched"
fi

echo
echo "Done. Sign in and go:   claude"
echo "Try:  'remember that we picked postgres for the pilot because ...'"
echo "then: 'why did we pick postgres?'"
