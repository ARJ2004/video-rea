"""English voice takes with Parler-TTS (default: parler-tts/parler-tts-large-v1, English-only, more natural than Indic Parler). The platform's main voice path is IndicF5 cloning a
locked Hindi reference voice; English stories use this instead. Consistency comes from a fixed NAMED speaker and a fixed
description per character (from the storyboard's "voices"), and the same seeds for every line.
usage: tts/bin/python en_lines.py lines.json out_dir      lines.json: [{"id","text","description","takes"}]"""
import json, sys, time
from pathlib import Path
import soundfile as sf, torch
from transformers import AutoTokenizer
from parler_tts import ParlerTTSForConditionalGeneration

jobs, out = json.load(open(sys.argv[1])), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
dev = "cuda"
MODEL = (jobs[0].get("model") if jobs else None) or "parler-tts/parler-tts-large-v1"
m = ParlerTTSForConditionalGeneration.from_pretrained(MODEL).to(dev)
tok = AutoTokenizer.from_pretrained(MODEL)
dtok = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
manifest = []
for j in jobs:
    d = dtok(j["description"], return_tensors="pt").to(dev)
    p = tok(j["text"], return_tensors="pt").to(dev)
    for k in range(j.get("takes", 3)):
        torch.manual_seed(500 + k); t0 = time.time()
        a = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask, prompt_input_ids=p.input_ids,
                       prompt_attention_mask=p.attention_mask)
        f = out / f"{j['id']}_en_t{k + 1}.wav"
        sf.write(f, a.cpu().float().numpy().squeeze(), m.config.sampling_rate)
        manifest.append({"line": j["id"], "take": f.name, "seed": 500 + k, "gen_s": round(time.time() - t0, 1),
                         "sec": round(sf.info(f).duration, 2), "chars": len(j["text"])})
        print(manifest[-1], flush=True)
json.dump(manifest, open(out / "takes.json", "w"), indent=2)
