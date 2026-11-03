"""Score takes: ASR word issues (qa.py) + speaker embedding (WavLM x-vector) + expressiveness (pitch spread).
usage: voice_score.py DIR [--ref-json refs.json]   (reads DIR/takes.json, writes DIR/voice_scores.json)
Consistency = cosine similarity of each take to its character's reference voice (or to the
character's mean embedding when no reference is given). Expressiveness = F0 std in semitones."""
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np, soundfile as sf, torch, librosa
from transformers import AutoFeatureExtractor, WavLMForXVector
from vrea.pronounce.qa import indic_conformer_asr, score_take
d = Path(sys.argv[1]); takes = json.load(open(d / "takes.json"))
refs = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}
fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv")
sv = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv").cuda().eval()
asr = indic_conformer_asr()
def load16(p):
    x, sr = sf.read(p, dtype="float32", always_2d=True); x = x.mean(1)
    return librosa.resample(x, orig_sr=sr, target_sr=16000) if sr != 16000 else x
def emb(p):
    x = load16(p); i = fe(x, sampling_rate=16000, return_tensors="pt").to("cuda")
    with torch.no_grad(): e = sv(**i).embeddings[0]
    return torch.nn.functional.normalize(e, dim=-1).cpu().numpy()
def f0_st(p):
    x = load16(p); f0, v, _ = librosa.pyin(x, fmin=70, fmax=600, sr=16000)
    f0 = f0[v & ~np.isnan(f0)]
    return float(np.std(12 * np.log2(f0 / np.median(f0)))) if len(f0) > 10 else 0.0
rows = []
for t in takes:
    p = str(d / t["take"]); s = score_take(t["take"], t["script"], *asr(p))
    rows.append(dict(t, transcript=s.transcript, issues=s.word_issues, n_issues=len(s.word_issues), cer=s.cer,
                     cps=s.chars_per_s, pace_ok=s.pace_ok, f0_std_st=round(f0_st(p), 2), _emb=emb(p)))
by_spk = defaultdict(list)
for r in rows: by_spk[r["speaker"]].append(r)
for spk, rs in by_spk.items():
    ref = emb(refs[spk]["audio"]) if spk in refs else np.mean([r["_emb"] for r in rs], 0)
    ref = ref / np.linalg.norm(ref)
    for r in rs: r["spk_sim"] = round(float(r["_emb"] @ ref), 3)
    E = np.stack([r["_emb"] for r in rs]); S = E @ E.T; n = len(rs)
    print(f"[{spk}] mean pairwise voice similarity across {n} takes: {(S.sum()-n)/(n*n-n):.3f}")
for r in rows: r.pop("_emb")
json.dump(rows, open(d / "voice_scores.json", "w"), ensure_ascii=False, indent=2)
for r in sorted(rows, key=lambda r: (r["line"], r["n_issues"], -r["spk_sim"])):
    print(f"{r['take']:28s} issues={r['n_issues']} cer={r['cer']:.3f} sim={r['spk_sim']:.3f} f0std={r['f0_std_st']:.2f}st cps={r['cps']}")
