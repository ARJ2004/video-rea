#!/bin/bash
# re-run after the field/group fix: clean field -> deities2 -> scenes 3 and 4 (scene4's VO chunks are already on disk)
set -a; . /etc/vrea.env; set +a; export HOME=/root HF_HOME=/mnt/nvme/hf
cd /mnt/nvme/jobs3; PY=/mnt/nvme/ComfyUI/.venv/bin/python; L=/mnt/nvme/logs
rm -f /mnt/nvme/work3/deities/field.png
$PY field.py > $L/field.log 2>&1 &
$PY deities2.py > $L/deity.log 2>&1 &
$PY scene3.py > $L/s3.log 2>&1 &
$PY scene4.py > $L/s4.log 2>&1 &
wait
s5cmd sync /mnt/nvme/ComfyUI/output/srishti/ s3://$BUCKET/work/output/srishti/
s5cmd sync /mnt/nvme/work3/ s3://$BUCKET/work3/
echo "RUN35 DONE"
