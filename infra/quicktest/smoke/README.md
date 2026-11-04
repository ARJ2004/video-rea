# Headless smoke run (no ComfyUI UI needed)

What `run.sh` does on the GPU box (it is started over SSM after "VREA READY"):

1. `comfy_submit.py smoke_jobs.json`: 12 Qwen-Image + Lightning 8-step images (4 each of Tara, Dadi, living room) through the ComfyUI API.
2. `tts_parler.py`: Indic Parler-TTS, 4 takes for each of the 7 Srishti ep1 lines. The text is prepared with the pronunciation lexicon (`pipeline/vrea/pronounce`), cycling through its spelling variants.
3. `asr_rank.py`: IndicConformer transcribes every take, and `qa.py` ranks the takes per line against the ORIGINAL script.

Outputs go to `ComfyUI/output/{smoke,tts}` and sync to `s3://$BUCKET/work/output/`.

To run it:
- **Bundle:** upload this folder, `pipeline/` and `stories/srishti-ep1/storyboard.json` to `s3://$BUCKET/jobs/`.
- **Hugging Face token:** store it yourself as an SSM SecureString named `/vrea/hf_token`; the box reads it with its instance role. The token needs access to the gated `ai4bharat/indic-conformer-600m-multilingual` model.
- **Start:** on the box, copy `s3://$BUCKET/jobs/*` to `/mnt/nvme/jobs/` and start `run.sh` in the background.

Known pins:
- `onnxruntime<1.23`: newer versions refuse IndicConformer's ONNX external-data files, which are reached through the Hugging Face cache's symlinks.
- `qa.py` reads audio with `soundfile`, because torchaudio ≥ 2.9 needs torchcodec.

`ranking-2026-11-03.json` holds the first run's scores. A summary is in `docs/hindi-pronunciation.md` §7.
