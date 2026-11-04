"""Score and rank several TTS takes of one line by transcribing them with Hindi ASR.

Why: TTS output is stochastic. A few takes per line (seconds of GPU each) plus automatic
ranking catch skipped or garbled words, wrong words, repeated phrases and mangled loanwords
before any lip-sync video is generated from the audio.

Limits: ASR has its own language model, so it often "hears" the correct word even when a
schwa or vowel length is slightly off. Treat the ranking as a filter. A native listener still
approves the top take of each line (see docs/hindi-pronunciation.md).

CLI (on the GPU box, after `pip install transformers torchaudio soundfile "onnxruntime<1.23"`; the ASR model is
gated, so accept its terms and set HF_TOKEN):
  python -m vrea.pronounce.qa --text "<ORIGINAL script line>" take1.wav take2.wav ...
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Callable

# Characters/s (Devanagari, no spaces). Calibrated on Indic Parler-TTS takes of Srishti ep1
# (2026-11-03): normal takes ran 7.8–9.9 cps; a take with a long stall ran 5.8. Outside this band
# a take usually skipped words (too fast) or stalled/repeated (too slow).
CPS_RANGE = (6.5, 18.0)


def canon(text: str) -> str:
    """Spelling-insensitive form for comparison: ASR and script may differ in nukta,
    chandrabindu vs anusvara, final halant, ष/श and punctuation without any audible difference."""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("़", "")            # nukta
    t = t.replace("ँ", "ं")      # chandrabindu -> anusvara
    # ASR spelling noise seen in practice, not audible differences:
    t = re.sub("न्ं|ंं+", "ं", t)      # doubled nasal marks: अन्ंदर, चाँंद, पांँच
    t = re.sub("््+", "्", t)          # doubled halant: ब्रह््मा
    t = t.replace("त्त्व", "त्व")      # तत्त्व == तत्व
    t = re.sub(r"\s+जी(?=\s|$)", "जी", t)  # honorific written apart or joined: ब्रह्मा जी == ब्रह्माजी
    t = t.replace("ष", "श")
    t = t.replace("ॐ", "ओम")
    t = re.sub(r"[।॥]", " ", t)
    t = re.sub(r"[^ऀ-ॿ\sA-Za-z]", " ", t)
    t = re.sub(r"्(?=\s|$)", "", t)   # word-final halant (ओम् == ओम), after punctuation is gone
    return re.sub(r"\s+", " ", t).strip().lower()


def cer(ref: str, hyp: str) -> float:
    ref, hyp = ref.replace(" ", ""), hyp.replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, hc in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(ref)


@dataclass
class TakeScore:
    path: str
    transcript: str
    cer: float
    duration_s: float
    chars_per_s: float
    word_issues: list[dict] = field(default_factory=list)  # {"expected": .., "heard": ..}
    pace_ok: bool = True
    rank_key: tuple = ()


def word_issues(ref: str, hyp: str) -> list[dict]:
    r, h = canon(ref).split(), canon(hyp).split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=r, b=h, autojunk=False).get_opcodes():
        if op != "equal":
            out.append({"expected": " ".join(r[i1:i2]), "heard": " ".join(h[j1:j2]), "op": op})
    return out


def score_take(path: str, script: str, transcript: str, duration_s: float) -> TakeScore:
    ref = canon(script)
    c = cer(ref, canon(transcript))
    cps = len(ref.replace(" ", "")) / max(duration_s, 1e-6)
    issues = word_issues(script, transcript)
    pace_ok = CPS_RANGE[0] <= cps <= CPS_RANGE[1]
    s = TakeScore(path, transcript, round(c, 4), round(duration_s, 2), round(cps, 1), issues, pace_ok)
    s.rank_key = (len(issues), 0 if pace_ok else 1, c)
    return s


def rank(takes: list[TakeScore]) -> list[TakeScore]:
    return sorted(takes, key=lambda t: t.rank_key)


def indic_conformer_asr() -> Callable[[str], tuple[str, float]]:
    """ASR backend: AI4Bharat IndicConformer (MIT). Returns fn(path) -> (transcript, duration_s)."""
    import torch
    import soundfile as sf
    import torchaudio
    from transformers import AutoModel

    model = AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual", trust_remote_code=True)

    def run(path: str) -> tuple[str, float]:
        # soundfile, not torchaudio.load: torchaudio >= 2.9 needs the separate torchcodec package
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        wav = torch.from_numpy(data.T).mean(dim=0, keepdim=True)
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        return str(model(wav, "hi", "ctc")), wav.shape[-1] / 16000

    return run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", required=True, help="ORIGINAL script line (not the respelled TTS text)")
    ap.add_argument("takes", nargs="+")
    args = ap.parse_args()
    asr = indic_conformer_asr()
    scored = rank([score_take(p, args.text, *asr(p)) for p in args.takes])
    print(json.dumps([asdict(s) for s in scored], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
