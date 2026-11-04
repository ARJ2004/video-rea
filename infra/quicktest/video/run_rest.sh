#!/bin/bash
# After keyframes: pick on-model variants -> I2V shots -> split audio -> talking heads -> score -> assemble -> sync
set -x
set -e   # stop at the first failing stage
set -a; . /etc/vrea.env; set +a; export HOME=/root HF_HOME=/mnt/nvme/hf
cd /mnt/nvme/jobs3; PY=/mnt/nvme/ComfyUI/.venv/bin/python
echo "== coverage";  $PY make_clips.py coverage

echo "== shots";     $PY make_clips.py shots
echo "== talk";      $PY make_clips.py talk
echo "== videos";    $PY consistency.py videos
echo "== assemble";  $PY assemble.py assemble
cp /mnt/nvme/work3/state.json /mnt/nvme/work3/consistency.json /mnt/nvme/ComfyUI/output/srishti/ 2>/dev/null
s5cmd sync /mnt/nvme/ComfyUI/output/srishti/ s3://$BUCKET/work/output/srishti/
echo "ALL DONE"
