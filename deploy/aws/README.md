# Engram on AWS

Everything needed to build, launch and list Engram as an EC2 machine image.

```
provision.sh                  turns a clean AL2023 box into the golden image
build-ami.sh                  drives a builder instance and snapshots the AMI
cloudformation/engram.yaml    launches the AMI with sane, locked-down defaults
MARKETPLACE_CHECKLIST.md      what listing it actually requires
```

## Build

```bash
./build-ami.sh --key-name my-key --subnet-id subnet-0abc123
```

Launches Amazon Linux 2023, provisions it via user-data, waits for it to power
itself off, snapshots it, terminates the builder. Takes 10–15 minutes, most of
it `dnf update`.

If the build fails the instance is **left running on purpose** — SSH in and read
`/var/log/engram-provision.log`, then terminate it yourself. A build that
tidies away its own evidence is a build you can't debug.

## Launch

```bash
aws cloudformation deploy \
  --template-file cloudformation/engram.yaml \
  --stack-name engram \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageId=ami-0abc123 VpcId=vpc-0abc SubnetId=subnet-0abc
```

Then open the tunnel and attach an agent:

```bash
# from the stack outputs
aws ssm start-session --target i-0abc123 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'

claude mcp add --transport sse engram http://localhost:8080/sse
```

## Why it's shaped this way

**Loopback by default.** The MCP server has no authentication. Anything that can
reach port 8080 can read and write the entire brain — every memory, every
project. So the stack opens no inbound ports at all, and access goes through an
SSM port-forward. This is a deliberate constraint, not an oversight: adding auth
to the MCP server is the prerequisite for ever binding it to a real interface.

**Instance-unique credentials.** The published container image ships
`POSTGRES_PASSWORD=pathpass` so `docker compose up` works with no setup. Fine on
a laptop; a shared default credential across every customer of a Marketplace
image is a policy failure. The AMI generates a unique password on first boot.

**The image is baked in.** `docker pull` happens at build time, not first boot,
so a customer's instance starts even if ghcr.io is unreachable.

**Stopped means success.** Provisioning ends by powering the instance off, which
gives the build script an unambiguous completion signal without polling console
output or granting the builder permission to tag itself.

**No Packer, no Image Builder.** The AWS CLI is already present wherever this
would run. One fewer toolchain to keep working a year from now.
