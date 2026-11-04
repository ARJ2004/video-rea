"""Re-run only the final assembly (labels, VO, captions) for clips 1.3 and 1.4 from the already-rendered, normalized shot
parts - no GPU. Used after changing captions to timed 2-line chunks. Timelines are recomputed exactly as the scene
scripts do. usage: python reassemble.py 1.3 1.4"""
import json, sys
from pathlib import Path
import s34

OUT = Path("/mnt/nvme/ComfyUI/output/srishti")


def r13():
    W = Path("/mnt/nvme/work3/s3"); C = s34.clip("1.3"); SH = {s["id"]: s for s in C["shots"]}; LINE = C["lines"][0]
    VO = s34.J / "voices" / "1.3-L1_f5_t1.wav"
    words, vo_len = s34.word_times(LINE["tts"], VO, ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    vo_start = max(1.0, 9.0 - words["अ से ब्रह्मा"])
    tD, tE, tF = (vo_start + words[w] - 0.15 for w in ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    end = vo_start + vo_len + 0.8
    seg = {"1.3-D": (tD, tE), "1.3-E": (tE, tF), "1.3-F": (tF, end)}
    parts = [W / "p_A.mp4", W / "p_B.mp4", W / "p_C.mp4"] + [W / f"p_{sid}.mp4" for sid in seg]
    labels = [(W / f"label_{sid}.png", a + 0.25, min(b, a + 2.6)) for sid, (a, b) in seg.items()]
    s34.finish(parts, labels, VO, vo_start, LINE["caption"], OUT / "clip_1.3.mp4", W)


def r14():
    W = Path("/mnt/nvme/work3/s4"); C = s34.clip("1.4"); LINE = C["lines"][0]
    CHAIN = ["1.4-B", "1.4-C", "1.4-D", "1.4-E", "1.4-F"]
    L = [c["sec"] for c in json.load(open(W / "vo" / "chunks.json"))]
    SEG = 3.4; a_len = max(3.0, 0.6 + L[0] - 0.8); start = {0: 0.6}; bounds, prev = {}, a_len
    for i, sid in enumerate(CHAIN):
        b0 = prev; b1 = b0 + SEG
        if sid == "1.4-F":
            start[5] = b0 + 1.0; start[6] = start[5] + L[5] + 0.6; b1 = start[6] + L[6] + 1.0
        else:
            start[i + 1] = max(b1 - 0.9 - (0.35 if i else 0.0), start.get(i, 0) + L[i] + 0.25)
        bounds[sid] = (b0, b1); prev = b1
    word_at = {sid: start[i + 1] + (0.35 if 0 < i < 4 else 0.9 if i == 4 else 0.0) for i, sid in enumerate(CHAIN)}
    total = prev
    parts = [W / "p_A.mp4"] + [W / f"p_{sid}.mp4" for sid in CHAIN]
    labels = [(W / f"label_{sid}.png", word_at[sid] - 0.1, min(bounds[sid][1], word_at[sid] + 1.8)) for sid in CHAIN]
    # 1.4 is voiced as phrases; caption chunks follow the phrases' real start times
    s34.finish(parts, labels, W / "vo_mix.wav", 0.0, LINE["caption"], OUT / "clip_1.4.mp4", W, cap_span=(0.6, total - 0.5),
               cap_starts=[0.6, start[1] - 0.2, start[6] - 0.2])


if __name__ == "__main__":
    for c in sys.argv[1:]:
        {"1.3": r13, "1.4": r14}[c]()
