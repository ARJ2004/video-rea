"""Step 2: every line with IndicF5 cloning ONE fixed reference per character -> same voice in every line.
4 takes per line (seeds x lexicon variants)."""
import json, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, torch
from transformers import AutoModel
from vrea.pronounce.normalize import prepare, variant_count, load_lexicon
sb, refs, out = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)
m = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True).to("cuda")
lex, takes = load_lexicon(), []
for clip in sb["clips"]:
    for line in clip.get("lines", []):
        r = refs[line["speaker"]]; nv = variant_count(line["tts"], lex)
        for k in range(4):
            v = k % nv if nv > 1 else 0; text = prepare(line["tts"], lex, variant=v).tts_text
            torch.manual_seed(300 + k); np.random.seed(300 + k); t0 = time.time()
            a = m(text, ref_audio_path=r["audio"], ref_text=r["text"])
            a = a.astype(np.float32) / 32768.0 if a.dtype == np.int16 else np.asarray(a, dtype=np.float32)
            f = f"{line['id']}_f5_t{k+1}.wav"; sf.write(out / f, a, 24000)
            takes.append({"line": line["id"], "speaker": line["speaker"], "take": f, "variant": v, "seed": 300 + k,
                          "script": line["tts"], "tts_text": text, "gen_s": round(time.time() - t0, 1)}); print(f, takes[-1]["gen_s"], flush=True)
json.dump(takes, open(out / "takes.json", "w"), ensure_ascii=False, indent=2)
