"""Re-voice 1.4-L1 as separate phrases with Dadi's locked IndicF5 reference, so each element word can be placed on
its shot. Runs in the f5 venv (voice_env.sh). Writes /mnt/nvme/work3/s4/vo/c{0..6}.wav + chunks.json."""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf, torch
from transformers import AutoModel
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))
from vrea.pronounce.normalize import prepare

PHRASES = ["फिर ब्रह्मा जी ने अपनी शक्ति से, एक-एक करके पाँच तत्व बनाए।", "आकाश,", "फिर हवा,", "फिर आग,", "फिर पानी,",
           "और अंत में धरती!", "और इन्हीं पाँच तत्वों से हमारी ये सुंदर दुनिया बनी।"]
out = Path("/mnt/nvme/work3/s4/vo"); out.mkdir(parents=True, exist_ok=True)
refs = json.load(open("/mnt/nvme/ComfyUI/output/voice_v2/refs/refs.json"))["dadi"]
m = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True).to("cuda")
meta = []
for i, p in enumerate(PHRASES):
    torch.manual_seed(302); np.random.seed(302)
    a = m(prepare(p).tts_text, ref_audio_path=refs["audio"], ref_text=refs["text"])
    a = a.astype(np.float32) / 32768.0 if a.dtype == np.int16 else np.asarray(a, dtype=np.float32)
    nz = np.where(np.abs(a) > 0.01)[0]                       # trim leading/trailing silence
    a = a[max(0, nz[0] - 1200): nz[-1] + 2400] if len(nz) else a
    sf.write(out / f"c{i}.wav", a, 24000); meta.append({"i": i, "text": p, "sec": round(len(a) / 24000, 2)})
    print(meta[-1], flush=True)
json.dump(meta, open(out / "chunks.json", "w"), ensure_ascii=False, indent=2)
print("VO CHUNKS DONE", flush=True)
