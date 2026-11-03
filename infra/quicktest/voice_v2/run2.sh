#!/bin/bash
# Voice v2: seed voices -> pick -> IndicF5 clone for all lines -> score consistency/expressiveness.
set -x
set -a; . /etc/vrea.env; set +a; export HOME=/root
J=$ROOT/jobs2; O=$ROOT/ComfyUI/output/voice_v2; UV=/usr/local/bin/uv; export UV_PYTHON_INSTALL_DIR=$ROOT/python
export HF_TOKEN=$(aws ssm get-parameter --region us-east-1 --name /vrea/hf_token --with-decryption --query Parameter.Value --output text 2>/dev/null) PYTHONPATH=$J/pipeline HF_HOME=$ROOT/hf
echo "HF token present: ${HF_TOKEN:+yes}"
cd $ROOT; bash $J/voice_env.sh restore   # cached in S3 after the first build (infra/quicktest/voice_env.sh)
echo "== seeds"; tts/bin/python $J/seed_refs.py $O/seeds
echo "== score seeds"; asr/bin/python $J/voice_score.py $O/seeds
echo "== pick refs"; asr/bin/python $J/pick_refs.py $O/seeds $O/refs
echo "== f5 lines"; f5/bin/python $J/f5_lines.py $J/storyboard.json $O/refs/refs.json $O/lines
echo "== score f5"; asr/bin/python $J/voice_score.py $O/lines --ref-json $O/refs/refs.json
echo "== score old parler takes (baseline)"; asr/bin/python $J/voice_score.py $ROOT/ComfyUI/output/tts
for d in input output user; do s5cmd sync "$ROOT/ComfyUI/$d/" "s3://$BUCKET/work/$d/"; done
echo "RUN DONE"
