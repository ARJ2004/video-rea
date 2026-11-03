#!/bin/bash
# Voice v2: seed voices -> pick -> IndicF5 clone for all lines -> score consistency/expressiveness.
set -x
set -a; . /etc/vrea.env; set +a; export HOME=/root
J=$ROOT/jobs2; O=$ROOT/ComfyUI/output/voice_v2; UV=/usr/local/bin/uv; export UV_PYTHON_INSTALL_DIR=$ROOT/python
export HF_TOKEN=$(aws ssm get-parameter --region us-east-1 --name /vrea/hf_token --with-decryption --query Parameter.Value --output text 2>/dev/null) PYTHONPATH=$J/pipeline HF_HOME=$ROOT/hf
echo "HF token present: ${HF_TOKEN:+yes}"
cd $ROOT; TORCH="torch torchaudio --index-url https://download.pytorch.org/whl/cu128"
( $UV venv -q --python 3.12 tts && $UV pip install -q --python tts/bin/python $TORCH && $UV pip install -q --python tts/bin/python git+https://github.com/huggingface/parler-tts.git soundfile ) > venv_tts.log 2>&1 &
( $UV venv -q --python 3.12 asr && $UV pip install -q --python asr/bin/python $TORCH && $UV pip install -q --python asr/bin/python transformers "onnxruntime<1.23" soundfile librosa ) > venv_asr.log 2>&1 &
( $UV venv -q --python 3.10 f5 && $UV pip install -q --python f5/bin/python "torch==2.8.0" "torchaudio==2.8.0" --index-url https://download.pytorch.org/whl/cu128 && $UV pip install -q --python f5/bin/python git+https://github.com/ai4bharat/IndicF5.git soundfile "transformers==4.49.0" "datasets==3.3.2" "huggingface_hub<0.30" accelerate ) > venv_f5.log 2>&1 &
wait; tail -3 venv_*.log
echo "== seeds"; tts/bin/python $J/seed_refs.py $O/seeds
echo "== score seeds"; asr/bin/python $J/voice_score.py $O/seeds
echo "== pick refs"; asr/bin/python $J/pick_refs.py $O/seeds $O/refs
echo "== f5 lines"; f5/bin/python $J/f5_lines.py $J/storyboard.json $O/refs/refs.json $O/lines
echo "== score f5"; asr/bin/python $J/voice_score.py $O/lines --ref-json $O/refs/refs.json
echo "== score old parler takes (baseline)"; asr/bin/python $J/voice_score.py $ROOT/ComfyUI/output/tts
for d in input output user; do s5cmd sync "$ROOT/ComfyUI/$d/" "s3://$BUCKET/work/$d/"; done
echo "RUN DONE"
