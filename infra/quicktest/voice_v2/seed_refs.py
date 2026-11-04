"""Step 1: candidate 'seed' voices per character from Indic Parler-TTS (expressive captions).
One seed per character is later cloned by IndicF5 for EVERY line, so the voice stays the same.
Replace the seed with a real recorded actor clip when available (better emotion)."""
import json, sys
from pathlib import Path
import torch, soundfile as sf
from transformers import AutoTokenizer
from parler_tts import ParlerTTSForConditionalGeneration
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
SEEDS = {
 "tara": {"text": "दादी, दादी! आज स्कूल में मैंने आसमान में एक चमकता तारा देखा! आप बताओ ना, वो इतना चमकता क्यों है?",
          "captions": ["Divya speaks in a high-pitched, very expressive and animated, cheerful and curious tone, like an excited young girl, at a moderate pace. The recording is of very high quality, with the speaker's voice sounding clear and very close up.",
                       "A young girl speaks in a high-pitched, bright, very expressive and playful tone, full of wonder and excitement, at a moderate pace. The recording is of very high quality, with the voice sounding clear and very close up."]},
 "dadi": {"text": "आओ बेटा, मेरे पास बैठो। आज मैं तुम्हें एक बहुत पुरानी कहानी सुनाती हूँ, जो मेरी दादी ने मुझे सुनाई थी।",
          "captions": ["Rani speaks in a warm, gentle, very expressive storytelling tone with a slightly low pitch and a slow pace, full of affection. The recording is of very high quality, with the speaker's voice sounding clear and very close up.",
                       "An elderly woman speaks in a warm, soft, loving and expressive storytelling tone with a low pitch and a slow pace. The recording is of very high quality, with the voice sounding clear and very close up."]},
}
m = ParlerTTSForConditionalGeneration.from_pretrained("ai4bharat/indic-parler-tts").to("cuda")
tok = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts")
dtok = AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
takes = []
for ch, s in SEEDS.items():
    for ci, cap in enumerate(s["captions"]):
        for k in range(4):
            torch.manual_seed(200 + k)
            d = dtok(cap, return_tensors="pt").to("cuda"); p = tok(s["text"], return_tensors="pt").to("cuda")
            a = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask, prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
            f = f"seed_{ch}_c{ci}_s{k}.wav"; sf.write(out / f, a.cpu().float().numpy().squeeze(), m.config.sampling_rate)
            takes.append({"line": f"seed-{ch}", "speaker": ch, "take": f, "variant": 0, "script": s["text"], "tts_text": s["text"]}); print(f, flush=True)
json.dump(takes, open(out / "takes.json", "w"), ensure_ascii=False, indent=2)
