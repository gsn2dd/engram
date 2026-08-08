#!/bin/bash
# The full guide, on demand. The login banner stays short and points here.
#
# Sections adapt to what the box actually needs, so the first thing you read is
# the thing you have to do — rather than a fixed document you have to search.
# Paged when it does not fit the terminal.

ENV_FILE=/etc/engram/engram.env
RUNTIME_ENV=/run/engram/secrets.env

have() { sudo grep -qE "^$1=.+" "$ENV_FILE" 2>/dev/null || grep -qE "^$1=.+" "$RUNTIME_ENV" 2>/dev/null; }

# Quote the path this instance is actually configured with. A guessed path
# sends the customer somewhere their IAM role cannot read, and the error they
# get back is AccessDenied, which reads like a permissions bug rather than a
# typo in the docs.
PREFIX="$(sudo grep -E '^ENGRAM_SSM_PREFIX=.+' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)"
PREFIX="${PREFIX:-/engram/$(hostname)}"
IID="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $(curl -fsS -m 2 -X PUT \
        http://169.254.169.254/latest/api/token \
        -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)" \
        http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null)"
IID="${IID:-YOUR_INSTANCE_ID}"
EMBED=missing
{ have GEMINI_API_KEY || have OPENAI_API_KEY; } && EMBED=set

render() {
cat <<EOF

  ENGRAM — a memory brain your AI agent attaches to.
  Open source: github.com/gsn2dd/engram

  ── WHAT YOU DO AND DO NOT NEED ────────────────────────────────────────────

  You do NOT need Claude Code, Codex, or any AI subscription to run this.
  Those are agents that ATTACH to engram; engram itself is just the memory.

  What it needs is an EMBEDDING key — the thing that turns text into vectors
  so memories can be found by meaning. Gemini or OpenAI. Without one, nothing
  can be stored at all.

  A Claude Pro/Max subscription is NOT an API key. Claude Code can run on a
  subscription as an agent and still attach to this brain — but engram's own
  internal calls need a real key. Codex needs an OpenAI API key regardless.

    REQUIRED   GEMINI_API_KEY   or   OPENAI_API_KEY     (storage + recall)
    OPTIONAL   ANTHROPIC_API_KEY                        (the extras, below)

  The optional Anthropic key enables subject classification, multi-angle
  indexing and the nightly consolidation pass. Storage and recall work fine
  without it — you just get a plainer brain.

  ── 1. SET THE KEY ─────────────────────────────────────────────────────────
$( [ "$EMBED" = set ] && echo "
  Already set on this instance. Nothing to do here." || echo "
  RECOMMENDED — Parameter Store, so the secret never touches this disk and
  never lands in an EBS snapshot. Run this from a machine with AWS access:

    aws ssm put-parameter --name \"${PREFIX}/GEMINI_API_KEY\" --value \"YOUR_KEY\" --type SecureString --overwrite

  Optionally, the same way:

    aws ssm put-parameter --name \"${PREFIX}/ANTHROPIC_API_KEY\" --value \"YOUR_KEY\" --type SecureString --overwrite
    aws ssm put-parameter --name \"${PREFIX}/ENGRAM_EMBED_PROVIDER\" --value \"gemini\" --type String --overwrite

  Then, on this box:

    sudo systemctl restart engram

  Keys are read at start-up into memory only. This instance's IAM role can
  read exactly ${PREFIX}/* and nothing else.

  QUICKER — straight into the file, if Parameter Store is more ceremony than
  you want. The key then lives on the root volume and in its snapshots:

    sudo nano /etc/engram/engram.env      # set GEMINI_API_KEY=
    sudo systemctl restart engram")

  ── 2. CONNECT AN AGENT ────────────────────────────────────────────────────

  The MCP endpoint requires this instance's bearer token (generated on first
  boot, unique to this machine):

    sudo grep ENGRAM_MCP_TOKEN /etc/engram/engram.env

  Port 8080 is still closed to the network on purpose: the token authenticates
  the caller, but over plain HTTP it would travel in cleartext, so it is only
  as private as the wire. The tunnel keeps the wire private. Do not open the
  port unless you put TLS in front.

  From YOUR machine (not this box):

    aws ssm start-session --target ${IID} \\
      --document-name AWS-StartPortForwardingSession \\
      --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'

  Then attach whichever agent you use, sending the token as a header:

    Claude Code   claude mcp add --transport sse engram http://localhost:8080/sse \\
                    --header "Authorization: Bearer <token>"
    OpenClaw      openclaw mcp set engram \\
                    '{"url":"http://localhost:8080/sse","headers":{"Authorization":"Bearer <token>"}}'
    Anything MCP  http://localhost:8080/sse + an Authorization: Bearer header

  THEN paste the block from AGENT_PROMPT.md into your agent's system prompt.
  Skipping this is the most common reason people think engram "isn't doing
  anything": the tools are present, but a model does not reach for a memory
  it was never told it has.

  ── 3. CAPTURE CONVERSATIONS AUTOMATICALLY (optional) ──────────────────────

  The Engram Capture browser extension records your claude.ai and ChatGPT
  conversations into this brain. Tunnel port 8081 the same way, then point the
  extension at http://localhost:8081 with this instance's token:

    sudo grep ENGRAM_INGEST_TOKEN /etc/engram/engram.env

  ── 4. SEE IT WORK ON REAL-LOOKING DATA ────────────────────────────────────

  Loads the working memory of a fictional company, then proves recall finds the
  right answer to 14 questions that share almost no words with it:

    docker exec engram python3 cli/pm.py demo --verify

  That is also a self-test. If it passes, storage, embedding and semantic
  recall all work on this instance with your key. Then ask your agent things
  like "why do the sensors go quiet when it gets cold" or "a customer nearly
  walked after an outage". Remove it with:

    docker exec engram python3 cli/pm.py forget-project tidewell --yes

  ── 5. ASK THE BRAIN ABOUT ITSELF ──────────────────────────────────────────

  It ships knowing how it works, so recall is also the tutorial:

    docker exec engram python3 cli/pm.py recall "how do I begin"
    docker exec engram python3 cli/pm.py recall "what does it do while I am asleep"
    docker exec engram python3 cli/pm.py recall "I searched and got nothing back"

  Remove those introductory memories once you are up and running:

    docker exec engram python3 cli/pm.py forget-project engram-guide --yes

  ── EVERYDAY ───────────────────────────────────────────────────────────────

    get_started  (or engram-help)            this guide
    journalctl -u engram -f                  logs
    sudo systemctl restart engram            restart after a config change
    docker exec engram python3 cli/pm.py demo --verify   demo + self-test
    docker exec engram python3 cli/pm.py dream           run consolidation by hand

  Issues, questions and what-broke reports: github.com/gsn2dd/engram

EOF
}

if [ -t 1 ] && command -v less >/dev/null 2>&1; then
    render | less -R -F -X
else
    render
fi
