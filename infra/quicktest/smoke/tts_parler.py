"""4 takes per storyboard line with Indic Parler-TTS (variant 0/1 x 2 seeds), Sanskritized lexicon."""
import json, sys, time
from pathlib import Path
import torch, soundfile as sf
from transformers import AutoTokenizer
from parler_tts import ParlerTTSForConditionalGeneration
from vrea.pronounce.normalize import prepare, variant_count, load_lexicon
sb, out = json.load(open(sys.argv[1])), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
VOICE = {  # Indic Parler has no child/elderly voices; these are the closest named Hindi speakers
  "tara": "Divya speaks in a high-pitched, bright, curious and expressive tone at a moderate pace, with very clear audio and a close-sounding recording.",
  "dadi": "Rani speaks slowly in a warm, gentle, low-pitched and calm tone, with very clear audio and a close-sounding recording.",
}
dev = "cuda"
m = ParlerTTSForConditionalGeneration.from_pretrained("ai4bharat/indic-parler-tts").to(dev)
tok = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts")
dtok = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
lex, manifest = load_lexicon(), []
for clip in sb["clips"]:
    for line in clip.get("lines", []):
        nv = variant_count(line["tts"], lex)
        for k in range(4):
            v, seed = (k % nv if nv > 1 else 0), 100 + k
            text = prepare(line["tts"], lex, variant=v).tts_text
            torch.manual_seed(seed)
            d = dtok(VOICE.get(line["speaker"], VOICE["dadi"]), return_tensors="pt").to(dev)
            p = tok(text, return_tensors="pt").to(dev)
            t0 = time.time()
            a = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                           prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
            f = out / f"{line['id']}_t{k+1}.wav"
            sf.write(f, a.cpu().float().numpy().squeeze(), m.config.sampling_rate)
            manifest.append({"line": line["id"], "speaker": line["speaker"], "take": f.name, "variant": v,
                             "seed": seed, "script": line["tts"], "tts_text": text, "gen_s": round(time.time()-t0, 1)})
            print(manifest[-1]["take"], manifest[-1]["gen_s"], "s", flush=True)
json.dump(manifest, open(out / "takes.json", "w"), ensure_ascii=False, indent=2)
