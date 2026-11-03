# Voice v2: one consistent cloned voice per character

The pipeline, run by `run2.sh`:

1. **Seed candidates.** `seed_refs.py` asks Indic Parler-TTS for 8 expressive candidates per character, as 2 captions × 4 seeds, each reading one 10–15 s line in character.
2. **Score.** `voice_score.py` scores every clip on three things:
   - ASR word issues, from IndicConformer via `qa.py`;
   - speaker similarity, a WavLM x-vector cosine against the reference (or against the mean voice when there is no reference);
   - pitch spread: F0 std in semitones, a rough measure of how expressive or monotone the delivery is.
3. **Pick.** `pick_refs.py` keeps one seed per character: the most expressive among those with 0 ASR issues. Cloning needs an exact transcript, so clean seeds matter.
4. **Clone.** `f5_lines.py` uses IndicF5 to clone that ONE reference for every line, 4 takes each (seeds × lexicon variants). Then `voice_score.py` scores the takes against the reference.

To swap in a real voice actor later, replace `refs/voice_<char>.wav` and its `text` in `refs.json` (the exact transcript), then re-run step 4.

Pins:
- IndicF5 needs `transformers==4.49.0`, `datasets==3.3.2` and `huggingface_hub<0.30`. Version 5.x builds models on the "meta" device and crashes in IndicF5's vocoder setup.
- IndicConformer needs `onnxruntime<1.23`.

Launch with `MODELS=none` so the session skips the ComfyUI weights.
