#!/bin/bash
# Boot a candidate AMI and run smoke-test.sh on it over SSM.
#
#   ./run-smoke-test.sh ami-xxxxxxxxxxxxxxxxx
#
# Launches a t3.small from the AMI with the SSM-only "engram-smoketest"
# instance profile (AmazonSSMManagedInstanceCore and nothing else), waits for
# it to register with SSM, ships smoke-test.sh across, prints the PASS/FAIL
# lines, and terminates the instance whatever the outcome — a failed candidate
# is diagnosed from the test output, not by keeping a broken box around.
#
# Exits non-zero if any check failed, so a release can gate on it.
set -euo pipefail

AMI_ID="${1:?usage: run-smoke-test.sh <ami-id>}"
REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"

IID="$(aws ec2 run-instances --region "$REGION" \
    --image-id "$AMI_ID" --instance-type t3.small \
    --iam-instance-profile Name=engram-smoketest \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=engram-smoketest},{Key=engram:role,Value=smoke-test}]" \
    --query 'Instances[0].InstanceId' --output text)"
echo "==> test instance ${IID} from ${AMI_ID}"
trap 'echo "==> terminating ${IID}"; aws ec2 terminate-instances --region "$REGION" --instance-ids "$IID" >/dev/null || true' EXIT

echo "==> waiting for SSM registration (first boot + agent, up to 6 min)"
DEADLINE=$(( $(date +%s) + 360 ))
until aws ssm describe-instance-information --region "$REGION" \
        --filters "Key=InstanceIds,Values=${IID}" \
        --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null \
        | grep -q Online; do
    [ "$(date +%s)" -gt "$DEADLINE" ] && { echo "ERROR: never registered with SSM"; exit 1; }
    sleep 10
done

# Give first-boot + the container a moment beyond SSM registration; the smoke
# test itself also waits on the service, so this is slack, not the mechanism.
sleep 30

PARAMS="$(mktemp)"
python3 - "$HERE/smoke-test.sh" "$PARAMS" <<'PY'
import json, sys
json.dump({"commands": [open(sys.argv[1]).read()]}, open(sys.argv[2], "w"))
PY
CMD_ID="$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
    --document-name AWS-RunShellScript --parameters "file://${PARAMS}" \
    --query 'Command.CommandId' --output text)"
rm -f "$PARAMS"

echo "==> smoke test running (command ${CMD_ID})"
DEADLINE=$(( $(date +%s) + 600 ))
while :; do
    STATUS="$(aws ssm get-command-invocation --region "$REGION" \
        --command-id "$CMD_ID" --instance-id "$IID" \
        --query 'Status' --output text 2>/dev/null || echo Pending)"
    case "$STATUS" in
        Success|Failed|Cancelled|TimedOut) break ;;
    esac
    [ "$(date +%s)" -gt "$DEADLINE" ] && { echo "ERROR: smoke test never finished"; exit 1; }
    sleep 10
done

aws ssm get-command-invocation --region "$REGION" \
    --command-id "$CMD_ID" --instance-id "$IID" \
    --query 'StandardOutputContent' --output text

if [ "$STATUS" != "Success" ]; then
    echo "==> smoke test status: ${STATUS}"
    aws ssm get-command-invocation --region "$REGION" \
        --command-id "$CMD_ID" --instance-id "$IID" \
        --query 'StandardErrorContent' --output text >&2
    exit 1
fi
echo "==> smoke test passed"
