#!/usr/bin/env bash
# Launch one GPU work session. The instance terminates itself (see gpu_bootstrap.sh), so nothing keeps billing.
#
# usage: BUCKET=my-bucket REGION=us-east-2 ./launch_gpu.sh
# optional: TYPE=g6e.2xlarge MARKET=spot|ondemand IDLE_MIN=20 MAX_HOURS=3 PROFILE=vrea-ec2
set -euo pipefail
: "${BUCKET:?set BUCKET}"
REGION=${REGION:-us-east-2}
TYPE=${TYPE:-g6e.2xlarge}
MARKET=${MARKET:-spot}
IDLE_MIN=${IDLE_MIN:-20}
MAX_HOURS=${MAX_HOURS:-3}
PROFILE=${PROFILE:-vrea-ec2}
here=$(cd "$(dirname "$0")" && pwd)

ami=$(aws ssm get-parameter --region "$REGION" \
  --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id \
  --query Parameter.Value --output text)

ud=$(mktemp)
sed -e "s|__BUCKET__|$BUCKET|" -e "s|__REGION__|$REGION|g" \
    -e "s|__IDLE_MIN__|$IDLE_MIN|" -e "s|__MAX_HOURS__|$MAX_HOURS|" \
    "$here/gpu_bootstrap.sh" > "$ud"

market=()
if [ "$MARKET" = spot ]; then
  market=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
fi

id=$(aws ec2 run-instances --region "$REGION" --image-id "$ami" --instance-type "$TYPE" \
  --iam-instance-profile Name="$PROFILE" \
  ${market[@]+"${market[@]}"} \
  --instance-initiated-shutdown-behavior terminate \
  --metadata-options HttpTokens=required \
  --user-data "file://$ud" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=vrea-gpu},{Key=project,Value=vrea}]' \
                       'ResourceType=volume,Tags=[{Key=project,Value=vrea}]' \
  --query 'Instances[0].InstanceId' --output text)
rm -f "$ud"

cat <<EOF
GPU instance: $id  ($TYPE, $MARKET, auto-terminates after ${IDLE_MIN} idle min or ${MAX_HOURS} h)

Ready in ~10 min (first boot ~25 min while the environment is built and cached). Watch progress:
  aws ssm start-session --region $REGION --target $id
  sudo tail -f /var/log/vrea-bootstrap.log        # wait for "VREA READY"

Open ComfyUI at http://localhost:8188 :
  aws ssm start-session --region $REGION --target $id --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8188"],"localPortNumber":["8188"]}'

End the session now (work syncs to s3://$BUCKET/work/ every 3 min and on shutdown):
  aws ec2 terminate-instances --region $REGION --instance-ids $id
EOF
