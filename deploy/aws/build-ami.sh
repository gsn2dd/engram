#!/bin/bash
# Build the Engram AMI.
#
#   ./build-ami.sh
#
# Launches a clean Amazon Linux 2023 instance, hands it provision.sh as
# user-data, waits for it to power itself off (the success signal), then
# snapshots it into an AMI and terminates the builder.
#
# Deliberately no Packer/Image Builder dependency — the AWS CLI is already on
# every box that would run this, and one less toolchain is one less thing to
# keep working a year from now.

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
INSTANCE_TYPE="t3.small"
ENGRAM_IMAGE="ghcr.io/gsn2dd/engram:latest"
KEY_NAME=""
SUBNET_ID=""
SECURITY_GROUP_ID=""
NAME_PREFIX="engram"
BUILD_TIMEOUT=1800          # 30 min; provisioning is a dnf update + docker pull

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    cat <<EOF

All arguments are optional — with none, it picks a default public subnet and
builds without a key pair. On failure the builder's console log is dumped, so
there is nothing to SSH in for.

  --subnet-id SUBNET       default: a default-for-AZ subnet in this region.
                           Needs outbound internet (dnf + ghcr.io pull)
  --key-name NAME          attach a key pair. Only useful if you want to poke
                           around a failed builder by hand
  --region REGION          default: \$AWS_DEFAULT_REGION or eu-west-1
  --instance-type TYPE     default: ${INSTANCE_TYPE}
  --security-group-id SG   default: the VPC's default security group
  --engram-image REF       default: ${ENGRAM_IMAGE}
  --name-prefix PREFIX     default: ${NAME_PREFIX}
EOF
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --key-name)          KEY_NAME="$2"; shift 2 ;;
        --subnet-id)         SUBNET_ID="$2"; shift 2 ;;
        --region)            REGION="$2"; shift 2 ;;
        --instance-type)     INSTANCE_TYPE="$2"; shift 2 ;;
        --security-group-id) SECURITY_GROUP_ID="$2"; shift 2 ;;
        --engram-image)      ENGRAM_IMAGE="$2"; shift 2 ;;
        --name-prefix)       NAME_PREFIX="$2"; shift 2 ;;
        -h|--help)           usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
AMI_NAME="${NAME_PREFIX}-al2023-${STAMP}"

aws() { command aws --region "$REGION" "$@"; }

echo "==> region ${REGION}, building ${AMI_NAME} from ${ENGRAM_IMAGE}"

# No subnet given: take a default-for-AZ one. Keeps the common case to a bare
# `./build-ami.sh` without hardcoding anyone's network into the repo.
if [ -z "$SUBNET_ID" ]; then
    SUBNET_ID="$(aws ec2 describe-subnets \
        --filters "Name=default-for-az,Values=true" \
        --query 'Subnets[0].SubnetId' --output text 2>/dev/null)"
    [ -n "$SUBNET_ID" ] && [ "$SUBNET_ID" != "None" ] || {
        echo "error: no default subnet in ${REGION}; pass --subnet-id" >&2; exit 1; }
    echo "==> using default subnet ${SUBNET_ID}"
fi

# Latest AL2023 from the public SSM parameter, so the build never pins a base
# image that quietly goes end-of-life and fails the Marketplace scan.
BASE_AMI="$(aws ssm get-parameters \
    --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query 'Parameters[0].Value' --output text)"
echo "==> base AMI: ${BASE_AMI}"

# The env-file heredoc in provision.sh is UNQUOTED so the generated secrets
# expand into it — which means any other ${...} in that block (a comment, a
# documentation example) detonates as an unbound variable at CUSTOMER first
# boot, under set -u, where no build-time check ever sees it. That exact bug
# shipped once: a comment reading "${ENGRAM_SSM_PREFIX}/<NAME>" killed first
# boot on every instance of an otherwise-good AMI. Whitelist the intended
# expansions; anything else stops the build here, where it is cheap.
BAD_EXPANSIONS="$(awk '/cat > "\$ENV_FILE" <<EOF/,/^EOF$/' "${HERE}/provision.sh" \
    | grep -o '\${[A-Za-z_][A-Za-z_0-9]*}' \
    | grep -vE '^\$\{(PG_PASS|INGEST_TOKEN|MCP_TOKEN|SSM_PREFIX)\}$' || true)"
if [ -n "$BAD_EXPANSIONS" ]; then
    echo "ERROR: unintended expansion(s) in the engram.env heredoc:" >&2
    echo "$BAD_EXPANSIONS" >&2
    echo "These would fail first boot with 'unbound variable'. Escape or remove them." >&2
    exit 1
fi

USER_DATA="$(mktemp)"
trap 'rm -f "$USER_DATA"' EXIT
{
    echo "#!/bin/bash"
    echo "export ENGRAM_IMAGE='${ENGRAM_IMAGE}'"
    # Stage the helper scripts onto the builder. They are kept as real files in
    # the repo rather than heredocs inside provision.sh so they can be reviewed,
    # diffed and syntax-checked like any other code.
    for helper in engram-fetch-keys.sh engram-welcome.sh engram-help.sh engram-aliases.sh; do
        echo "cat > /tmp/${helper} <<'ENGRAM_HELPER_EOF'"
        cat "${HERE}/${helper}"
        echo "ENGRAM_HELPER_EOF"
        echo "chmod 0755 /tmp/${helper}"
    done
    tail -n +2 "${HERE}/provision.sh"
} > "$USER_DATA"

# EC2 caps user-data at 25,600 bytes and the assembled script outgrew it in
# 0.4.0 (RunInstances fails with InvalidParameterValue). cloud-init accepts
# gzipped user-data transparently, so compress — roughly 3x headroom — and
# check the compressed size too so the eventual re-overflow is a clear message
# here rather than a launch error.
gzip -f "$USER_DATA"
USER_DATA="${USER_DATA}.gz"
SIZE=$(stat -c%s "$USER_DATA")
if [ "$SIZE" -gt 25600 ]; then
    echo "ERROR: user-data is ${SIZE} bytes even gzipped (limit 25600)." >&2
    echo "Move helper content out of user-data (e.g. fetch from the repo) before building." >&2
    exit 1
fi
echo "==> user-data: ${SIZE} bytes gzipped"
trap 'rm -f "$USER_DATA"' EXIT

RUN_ARGS=(
    --image-id "$BASE_AMI"
    --instance-type "$INSTANCE_TYPE"
    --subnet-id "$SUBNET_ID"
    --user-data "fileb://${USER_DATA}"
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled"
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}]'
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${AMI_NAME}-builder},{Key=engram:role,Value=ami-builder}]"
)
[ -n "$SECURITY_GROUP_ID" ] && RUN_ARGS+=(--security-group-ids "$SECURITY_GROUP_ID")
[ -n "$KEY_NAME" ] && RUN_ARGS+=(--key-name "$KEY_NAME")

INSTANCE_ID="$(aws ec2 run-instances "${RUN_ARGS[@]}" \
    --query 'Instances[0].InstanceId' --output text)"
echo "==> builder instance: ${INSTANCE_ID}"

cleanup_builder() {
    echo "==> terminating builder ${INSTANCE_ID}"
    aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" >/dev/null || true
}

# Provisioning ends in `shutdown -h now`. A stopped instance means every step
# succeeded; still-running at timeout means it failed and is waiting to be
# looked at, which is why we do NOT terminate on that path.
echo "==> waiting for provisioning (up to $((BUILD_TIMEOUT / 60)) min)"
DEADLINE=$(( $(date +%s) + BUILD_TIMEOUT ))
while :; do
    STATE="$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' --output text)"
    [ "$STATE" = "stopped" ] && { echo "==> provisioning complete"; break; }
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "!! timed out with instance in state '${STATE}'." >&2
        echo "!! last 60 lines of the builder's console log:" >&2
        aws ec2 get-console-output --instance-id "$INSTANCE_ID" \
            --query Output --output text 2>/dev/null | tail -60 >&2 || \
            echo "!! (console output not available yet — it can lag a few minutes)" >&2
        echo "!! builder ${INSTANCE_ID} left running on purpose. Terminate it with:" >&2
        echo "!!   aws ec2 terminate-instances --region ${REGION} --instance-ids ${INSTANCE_ID}" >&2
        exit 1
    fi
    sleep 20
done

IMAGE_ID="$(aws ec2 create-image \
    --instance-id "$INSTANCE_ID" \
    --name "$AMI_NAME" \
    --description "Engram - persistent memory brain for AI agents (${ENGRAM_IMAGE})" \
    --tag-specifications "ResourceType=image,Tags=[{Key=Name,Value=${AMI_NAME}},{Key=engram:image,Value=${ENGRAM_IMAGE}}]" \
    --query 'ImageId' --output text)"
echo "==> creating AMI ${IMAGE_ID}"

aws ec2 wait image-available --image-ids "$IMAGE_ID"
cleanup_builder

cat <<EOF

==> done

    AMI:    ${IMAGE_ID}
    Name:   ${AMI_NAME}
    Region: ${REGION}

Next:
  1. Launch it via cloudformation/engram.yaml and check the smoke test in
     MARKETPLACE_CHECKLIST.md passes.
  2. Share the AMI with the AWS Marketplace scanning account, then submit.
EOF
