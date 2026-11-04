#!/bin/bash
# Voice environments (Indic Parler-TTS, IndicF5, IndicConformer ASR + scoring), cached in S3.
#   voice_env.sh restore   -> restore from s3://$BUCKET/env/voice-env.tar.zst if present (about 1 min), else build + upload
#   voice_env.sh build     -> force a rebuild and upload
# Envs land in $ROOT/{tts,f5,asr}; the uv-managed Python they use lives in $ROOT/python (same path every boot).
set -euo pipefail
set -a; . /etc/vrea.env; set +a
cd "$ROOT"; UV=/usr/local/bin/uv; export UV_PYTHON_INSTALL_DIR=$ROOT/python
KEY="s3://$BUCKET/env/voice-env.tar.zst"
CU="--index-url https://download.pytorch.org/whl/cu128"
build() {
  ( $UV venv -q --python 3.12 tts && $UV pip install -q --python tts/bin/python torch torchaudio $CU \
      && $UV pip install -q --python tts/bin/python git+https://github.com/huggingface/parler-tts.git soundfile ) &
  ( $UV venv -q --python 3.12 asr && $UV pip install -q --python asr/bin/python torch torchaudio $CU \
      && $UV pip install -q --python asr/bin/python transformers "onnxruntime<1.23" soundfile librosa ) &
  # IndicF5 (early 2025) needs period-correct pins: transformers 5.x builds on "meta" device, newer
  # datasets needs newer huggingface_hub, torchaudio>=2.9 needs torchcodec to read WAVs.
  ( $UV venv -q --python 3.10 f5 && $UV pip install -q --python f5/bin/python "torch==2.8.0" "torchaudio==2.8.0" $CU \
      && $UV pip install -q --python f5/bin/python git+https://github.com/ai4bharat/IndicF5.git soundfile \
         "transformers==4.49.0" "datasets==3.3.2" "huggingface_hub<0.30" accelerate ) &
  wait
  for v in tts asr f5; do "$v/bin/python" -c "import torch; print('$v ok', torch.__version__)"; done
  tar -cf - tts asr f5 python | zstd -T0 -3 | s5cmd pipe "$KEY"
  echo "uploaded $KEY"
}
case "${1:-restore}" in
  build) build ;;
  restore)
    if s5cmd ls "$KEY" >/dev/null 2>&1; then s5cmd cat "$KEY" | zstd -d -T0 | tar -x -C "$ROOT"; echo "restored voice envs"
    else build; fi ;;
esac
