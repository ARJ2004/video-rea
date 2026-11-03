#!/bin/bash
# Scenes 3 and 4 in parallel on one GPU box. Streams:
#   voice : restore voice envs from S3 -> re-voice 1.4-L1 as phrases (IndicF5, Dadi's locked reference)
#   deity : Tridev sheets -> group frame -> close frames   (both scenes wait for this)
#   s3/s4 : start immediately; each blocks only on what it needs; ComfyUI queues the GPU work
set -a; . /etc/vrea.env; set +a; export HOME=/root HF_HOME=/mnt/nvme/hf
export HF_TOKEN=$(aws ssm get-parameter --region us-east-1 --name /vrea/hf_token --with-decryption --query Parameter.Value --output text 2>/dev/null)
cd /mnt/nvme/jobs3; PY=/mnt/nvme/ComfyUI/.venv/bin/python; L=/mnt/nvme/logs; mkdir -p $L
( bash voice_env.sh restore && cd /mnt/nvme && f5/bin/python jobs3/vo_chunks.py ) > $L/voice.log 2>&1 &
$PY deities.py > $L/deity.log 2>&1 &
$PY scene3.py > $L/s3.log 2>&1 &
$PY scene4.py > $L/s4.log 2>&1 &
wait
s5cmd sync /mnt/nvme/ComfyUI/output/srishti/ s3://$BUCKET/work/output/srishti/
echo "RUN34 DONE"
