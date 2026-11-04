"""Pick one seed per character: no ASR issues (exact transcript needed for cloning), then most expressive."""
import json, sys, shutil
from pathlib import Path
d, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
rows = json.load(open(d / "voice_scores.json")); refs = {}
for spk in sorted({r["speaker"] for r in rows}):
    c = sorted([r for r in rows if r["speaker"] == spk], key=lambda r: (r["n_issues"], r["cer"] > 0.03, -r["f0_std_st"]))[0]
    dst = out / f"voice_{spk}.wav"; shutil.copy(d / c["take"], dst)
    refs[spk] = {"audio": str(dst), "text": c["tts_text"], "from": c["take"], "f0_std_st": c["f0_std_st"], "n_issues": c["n_issues"]}
    print(spk, refs[spk])
json.dump(refs, open(out / "refs.json", "w"), ensure_ascii=False, indent=2)
