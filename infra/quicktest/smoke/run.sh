#!/bin/bash
# Runs on the GPU box as root after "VREA READY". Outputs land in ComfyUI/output (synced to S3 by the watchdog).
set -x
set -a; . /etc/vrea.env; set +a; export HOME=/root
J=$ROOT/jobs; O=$ROOT/ComfyUI/output; UV=/usr/local/bin/uv; export UV_PYTHON_INSTALL_DIR=$ROOT/python
echo "== images"; $ROOT/ComfyUI/.venv/bin/python $J/comfy_submit.py $J/smoke_jobs.json
export HF_TOKEN=$(aws ssm get-parameter --region us-east-1 --name /vrea/hf_token --with-decryption --query Parameter.Value --output text 2>/dev/null) PYTHONPATH=$J/pipeline HF_HOME=$ROOT/hf
echo "HF token present: ${HF_TOKEN:+yes}"
echo "== tts venv"; cd $ROOT
$UV venv -q --python 3.12 tts && $UV pip install -q --python tts/bin/python torch torchaudio --index-url https://download.pytorch.org/whl/cu128 \
  && $UV pip install -q --python tts/bin/python git+https://github.com/huggingface/parler-tts.git soundfile
echo "== tts"; tts/bin/python $J/tts_parler.py $J/storyboard.json $O/tts
echo "== asr venv"
$UV venv -q --python 3.12 asr && $UV pip install -q --python asr/bin/python torch torchaudio --index-url https://download.pytorch.org/whl/cu128 \
  && $UV pip install -q --python asr/bin/python transformers "onnxruntime<1.23" soundfile
echo "== asr"; asr/bin/python $J/asr_rank.py $O/tts
for d in input output user; do s5cmd sync "$ROOT/ComfyUI/$d/" "s3://$BUCKET/work/$d/"; done
echo "RUN DONE"
