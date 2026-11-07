#!/usr/bin/env bash
# Create (or update) the hosted platform. Idempotent.
#   ./deploy.sh            first run: IAM role, security group (80/443 only), Elastic IP, t4g.small server, bundles
#   ./deploy.sh update     re-upload the bundles and restart the app on the existing server (via SSM)
# Prints the URL. The login password is generated on first run and printed once; only its scrypt hash leaves this machine.
set -euo pipefail
REGION=${REGION:-us-east-1}; BUCKET=${BUCKET:-vrea-686112930191-us-east-1}
ROLE=vrea-platform; SG_NAME=vrea-platform-web; NAME=vrea-platform; TYPE=${TYPE:-t4g.small}
REPO=$(cd "$(dirname "$0")/../.." && pwd); TMP=$(mktemp -d)
ACCT=$(aws sts get-caller-identity --query Account --output text)

bundles() {
  ( cd "$REPO" && tar --exclude='__pycache__' --exclude='*.pyc' -czf "$TMP/server_bundle.tar.gz" platform \
      infra/quicktest/gpu_bootstrap.sh infra/quicktest/model_plan.py infra/quicktest/models.json )
  mkdir -p "$TMP/w" && cp "$REPO"/platform/worker/{worker.py,drift.py} "$REPO"/infra/quicktest/video/{comfy.py,talk.py,reframe.py} \
      "$REPO"/infra/quicktest/models.json "$REPO"/infra/quicktest/voice_v2/{f5_lines.py,voice_score.py} "$REPO"/infra/quicktest/voice_env.sh "$TMP/w/"
  mkdir -p "$TMP/w/pipeline" && cp -r "$REPO/pipeline/vrea" "$TMP/w/pipeline/" && find "$TMP/w" -name __pycache__ -prune -exec rm -rf {} +
  tar -czf "$TMP/worker_bundle.tar.gz" -C "$TMP/w" .
  aws s3 cp "$TMP/server_bundle.tar.gz" "s3://$BUCKET/platform/server_bundle.tar.gz" --quiet
  aws s3 cp "$TMP/worker_bundle.tar.gz" "s3://$BUCKET/platform/worker_bundle.tar.gz" --quiet
  echo "bundles uploaded"
}

instance_id() {
  aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text
}

if [ "${1:-}" = update ]; then
  bundles
  IID=$(instance_id)
  aws ssm send-command --region "$REGION" --instance-ids "$IID" --document-name AWS-RunShellScript \
    --parameters 'commands=["/usr/local/bin/vrea-update"]' --query Command.CommandId --output text
  exit 0
fi

# ---- IAM: least privilege for the server
if ! aws iam get-role --role-name $ROLE >/dev/null 2>&1; then
  aws iam create-role --role-name $ROLE --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name $ROLE --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
fi
cat >"$TMP/policy.json" <<EOF
{"Version":"2012-10-17","Statement":[
 {"Sid":"Bucket","Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::$BUCKET/*"},
 {"Sid":"BucketList","Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::$BUCKET"},
 {"Sid":"LaunchTaggedGpu","Effect":"Allow","Action":"ec2:RunInstances","Resource":["arn:aws:ec2:$REGION:$ACCT:instance/*","arn:aws:ec2:$REGION:$ACCT:volume/*"],
  "Condition":{"StringEquals":{"aws:RequestTag/project":"vrea-platform"}}},
 {"Sid":"LaunchResources","Effect":"Allow","Action":"ec2:RunInstances","Resource":["arn:aws:ec2:$REGION::image/*","arn:aws:ec2:$REGION:$ACCT:subnet/*",
  "arn:aws:ec2:$REGION:$ACCT:security-group/*","arn:aws:ec2:$REGION:$ACCT:network-interface/*"]},
 {"Sid":"TagOnLaunch","Effect":"Allow","Action":"ec2:CreateTags","Resource":"*","Condition":{"StringEquals":{"ec2:CreateAction":"RunInstances"}}},
 {"Sid":"TerminateOwnGpu","Effect":"Allow","Action":"ec2:TerminateInstances","Resource":"arn:aws:ec2:$REGION:$ACCT:instance/*",
  "Condition":{"StringEquals":{"ec2:ResourceTag/project":"vrea-platform"}}},
 {"Sid":"Describe","Effect":"Allow","Action":["ec2:DescribeInstances","ec2:DescribeInstanceStatus","ec2:DescribeSpotPriceHistory"],"Resource":"*"},
 {"Sid":"PassGpuRole","Effect":"Allow","Action":"iam:PassRole","Resource":"arn:aws:iam::$ACCT:role/vrea-ec2"},
 {"Sid":"AmiLookup","Effect":"Allow","Action":"ssm:GetParameter","Resource":"arn:aws:ssm:$REGION::parameter/aws/service/*"}
]}
EOF
aws iam put-role-policy --role-name $ROLE --policy-name vrea-platform --policy-document "file://$TMP/policy.json"
aws iam get-instance-profile --instance-profile-name $ROLE >/dev/null 2>&1 || {
  aws iam create-instance-profile --instance-profile-name $ROLE >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name $ROLE --role-name $ROLE; sleep 10; }

# ---- security group: web only
VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC" --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = None ]; then
  SG=$(aws ec2 create-security-group --region "$REGION" --group-name $SG_NAME --description "vrea platform: HTTP/HTTPS only" --vpc-id "$VPC" --query GroupId --output text)
  for p in 80 443; do
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG" --ip-permissions \
      "IpProtocol=tcp,FromPort=$p,ToPort=$p,IpRanges=[{CidrIp=0.0.0.0/0}],Ipv6Ranges=[{CidrIpv6=::/0}]" >/dev/null
  done
fi

# ---- fixed public address
ALLOC=$(aws ec2 describe-addresses --region "$REGION" --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)
if [ "$ALLOC" = None ]; then
  ALLOC=$(aws ec2 allocate-address --region "$REGION" --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
fi
IP=$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)
DOMAIN="${IP//./-}.sslip.io"

bundles
IID=$(instance_id)
if [ "$IID" = None ]; then
  PW=$(python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(20)))")
  HASH=$(python3 -c "import hashlib,secrets,sys; s=secrets.token_hex(16); print(s+'\$'+hashlib.scrypt(sys.argv[1].encode(),salt=bytes.fromhex(s),n=2**14,r=8,p=1).hex())" "$PW")
  sed -e "s|__BUCKET__|$BUCKET|g" -e "s|__REGION__|$REGION|g" -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__PW_HASH__|$HASH|" \
    "$REPO/platform/deploy/server_setup.sh" > "$TMP/ud.sh"
  AMI=$(aws ssm get-parameter --region "$REGION" --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
  IID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$TYPE" --iam-instance-profile Name=$ROLE \
    --security-group-ids "$SG" --metadata-options HttpTokens=required --user-data "file://$TMP/ud.sh" \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=project,Value=vrea-server}]" \
                         "ResourceType=volume,Tags=[{Key=project,Value=vrea-server}]" \
    --query 'Instances[0].InstanceId' --output text)
  aws ec2 wait instance-running --region "$REGION" --instance-ids "$IID"
  aws ec2 associate-address --region "$REGION" --instance-id "$IID" --allocation-id "$ALLOC" >/dev/null
  echo "PASSWORD=$PW"
fi
echo "INSTANCE=$IID"
echo "URL=https://$DOMAIN"
