#!/usr/bin/env bash
# One-time: launch a small CPU instance (~$0.09/h) that copies all models into S3, then terminates itself.
# Costs about $0.10 in total. No GPU time is spent downloading models.
#
# usage: BUCKET=my-bucket REGION=us-east-2 [PROFILE=vrea-ec2] [HF_TOKEN=...] ./launch_seeder.sh
set -euo pipefail
: "${BUCKET:?set BUCKET}"
REGION=${REGION:-us-east-2}
PROFILE=${PROFILE:-vrea-ec2}
TYPE=${TYPE:-c7i-flex.large}
here=$(cd "$(dirname "$0")" && pwd)

ami=$(aws ssm get-parameter --region "$REGION" \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query Parameter.Value --output text)

ud=$(mktemp)
{
  echo '#!/bin/bash'
  echo "export BUCKET='$BUCKET' AWS_DEFAULT_REGION='$REGION' AWS_REGION='$REGION' HF_TOKEN='${HF_TOKEN:-}'"
  echo "cat > /root/models.manifest <<'MANIFEST'"; cat "$here/models.manifest"; echo "MANIFEST"
  echo "cat > /root/seed.sh <<'SEED'"; cat "$here/seed_models_to_s3.sh"; echo "SEED"
  cat <<'EOF'
cd /root && chmod +x seed.sh
./seed.sh "$BUCKET" models.manifest 3 > seed.log 2>&1; rc=$?
aws s3 cp seed.log "s3://$BUCKET/logs/seed-$(date +%Y%m%d-%H%M%S).log" --only-show-errors
[ $rc -eq 0 ] && echo ok | aws s3 cp - "s3://$BUCKET/_SEEDED" --only-show-errors
shutdown -h now
EOF
} > "$ud"

id=$(aws ec2 run-instances --region "$REGION" --image-id "$ami" --instance-type "$TYPE" \
  --iam-instance-profile Name="$PROFILE" \
  --instance-initiated-shutdown-behavior terminate \
  --metadata-options HttpTokens=required \
  --user-data "file://$ud" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=vrea-seeder},{Key=project,Value=vrea}]' \
  --query 'Instances[0].InstanceId' --output text)
rm -f "$ud"

echo "Seeder launched: $id (terminates itself when done, usually 30-60 min)"
echo "Done when this prints 'ok':  aws s3 cp s3://$BUCKET/_SEEDED - "
echo "Log afterwards:              aws s3 ls s3://$BUCKET/logs/"
