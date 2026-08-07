#!/bin/bash
# Build the Engram AMI.
#
#   ./build-ami.sh --key-name my-key --subnet-id subnet-abc123
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
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    cat <<EOF

Required:
  --key-name NAME          EC2 key pair, so a failed build can be inspected
  --subnet-id SUBNET       Subnet with outbound internet (dnf + ghcr.io pull)

Optional:
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

[ -n "$KEY_NAME" ]  || { echo "error: --key-name is required" >&2; usage; }
[ -n "$SUBNET_ID" ] || { echo "error: --subnet-id is required" >&2; usage; }

HERE="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
AMI_NAME="${NAME_PREFIX}-al2023-${STAMP}"

aws() { command aws --region "$REGION" "$@"; }

echo "==> region ${REGION}, building ${AMI_NAME} from ${ENGRAM_IMAGE}"

# Latest AL2023 from the public SSM parameter, so the build never pins a base
# image that quietly goes end-of-life and fails the Marketplace scan.
BASE_AMI="$(aws ssm get-parameters \
    --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query 'Parameters[0].Value' --output text)"
echo "==> base AMI: ${BASE_AMI}"

USER_DATA="$(mktemp)"
trap 'rm -f "$USER_DATA"' EXIT
{
    echo "#!/bin/bash"
    echo "export ENGRAM_IMAGE='${ENGRAM_IMAGE}'"
    tail -n +2 "${HERE}/provision.sh"
} > "$USER_DATA"

RUN_ARGS=(
    --image-id "$BASE_AMI"
    --instance-type "$INSTANCE_TYPE"
    --key-name "$KEY_NAME"
    --subnet-id "$SUBNET_ID"
    --user-data "file://${USER_DATA}"
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled"
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","Encrypted":true,"DeleteOnTermination":true}}]'
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${AMI_NAME}-builder},{Key=engram:role,Value=ami-builder}]"
)
[ -n "$SECURITY_GROUP_ID" ] && RUN_ARGS+=(--security-group-ids "$SECURITY_GROUP_ID")

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
        echo "!! builder ${INSTANCE_ID} left running on purpose — ssh in and read" >&2
        echo "!!   /var/log/engram-provision.log  (then terminate it yourself)" >&2
        exit 1
    fi
    sleep 20
done

IMAGE_ID="$(aws ec2 create-image \
    --instance-id "$INSTANCE_ID" \
    --name "$AMI_NAME" \
    --description "Engram — persistent memory brain for AI agents (${ENGRAM_IMAGE})" \
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
