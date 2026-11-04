#!/bin/bash
# Ep2 voices with the locked Tara/Dadi references (IndicF5, 4 takes/line) + ASR/voice-consistency ranking.
set -a; . /etc/vrea.env; set +a; export HOME=/root HF_HOME=/mnt/nvme/hf PYTHONPATH=/mnt/nvme/jobs3/pipeline
export HF_TOKEN=$(aws ssm get-parameter --region us-east-1 --name /vrea/hf_token --with-decryption --query Parameter.Value --output text 2>/dev/null)
cd /mnt/nvme; until [ -x f5/bin/python ] && [ -x asr/bin/python ] && grep -q "restored voice envs\|uploaded" /mnt/nvme/logs/voice.log 2>/dev/null; do sleep 10; done
R=/mnt/nvme/ComfyUI/output/voice_v2/refs/refs.json; O=/mnt/nvme/ComfyUI/output/ep2/voices
f5/bin/python jobs3/ep2/f5_lines.py jobs3/ep2/storyboard.json $R $O && asr/bin/python jobs3/ep2/voice_score.py $O --ref-json $R
echo "EP2 VOICES DONE"
