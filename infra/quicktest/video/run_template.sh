#!/bin/bash
# Template for a GPU session that runs several streams in parallel WITHOUT making the GPU thrash between models.
# Launch the box with only the model families the session needs, in the order they will be used, e.g.:
#   MODELS=fam:image,edit,video TYPE=g6e.2xlarge MARKET=ondemand BUCKET=... REGION=us-east-1 ./launch_gpu.sh
# then copy the job bundle to /mnt/nvme/jobs3 and run this file there.
set -a; . /etc/vrea.env; set +a; export HOME=/root HF_HOME=/mnt/nvme/hf
cd /mnt/nvme/jobs3; PY=/mnt/nvme/ComfyUI/.venv/bin/python; L=/mnt/nvme/logs; mkdir -p $L

# 1) the GPU dispatcher owns the ComfyUI queue: runs jobs of the already-loaded model family first and only schedules a
#    family once its weights have landed (staged copy). Every stream below just calls comfy.run() as before.
$PY gpu_dispatch.py serve > $L/dispatch.log 2>&1 &
DISPATCH=$!
until [ -f /mnt/nvme/gpuq/dispatcher.pid ]; do sleep 1; done

# 2) streams: start everything at once; each blocks only on its own inputs. CPU-side work (voices, ffmpeg assembly,
#    scoring) overlaps with GPU jobs. Replace these with the session's real streams.
PIDS=()
# $PY deities2.py > $L/deity.log 2>&1 & PIDS+=($!)
# $PY scene3.py   > $L/s3.log    2>&1 & PIDS+=($!)
# $PY scene4.py   > $L/s4.log    2>&1 & PIDS+=($!)
# (bash voice_env.sh restore && f5/bin/python jobs3/vo_chunks.py) > $L/voice.log 2>&1 & PIDS+=($!)
[ ${#PIDS[@]} -gt 0 ] && wait "${PIDS[@]}"

# 3) stop the dispatcher, summarise how well the session used the GPU, sync everything
kill $DISPATCH
$PY util_report.py $L > $L/util_summary.json 2>&1 || true
s5cmd sync /mnt/nvme/ComfyUI/output/ s3://$BUCKET/work/output/
echo "RUN DONE"
