"""Clip 1.4 'Making the Material World': Brahma (from his 1.3 close-up) extends his palm -> the five elements morph
one into the next above the palm (FLF chain between same-composition keyframes), each label shown when Dadi says it."""
import json, time
from pathlib import Path
import comfy, s34

W = Path("/mnt/nvme/work3/s4"); W.mkdir(parents=True, exist_ok=True)
C = s34.clip("1.4"); SH = {s["id"]: s for s in C["shots"]}; LINE = C["lines"][0]
KF = next(s for s in C["shots"] if s["id"] == "1.4-KF")["keyframes"]
VO = s34.J / "voices" / "1.4-L1_f5_t3.wav"; VO_START = 0.8
CHAIN = [("1.4-B", "aakash", "आकाश"), ("1.4-C", "vayu", "हवा"), ("1.4-D", "agni", "आग"), ("1.4-E", "jal", "पानी"), ("1.4-F", "prithvi", "धरती")]
BR = ("Image 1 is Brahma in this scene; image 2 is his character reference: keep his four bearded faces, skin, four arms, attributes and "
      "saffron-gold clothing exactly. ")


def main():
    comfy.wait_up()
    vo_dir = W / "vo"
    while not (vo_dir / "chunks.json").exists():
        time.sleep(5)
    ch = json.load(open(vo_dir / "chunks.json")); L = [c["sec"] for c in ch]
    # layout: phrase start times (s) and shot bounds; each element word lands as its element finishes forming
    SEG = 3.4                                            # seconds per element morph
    a_len = max(3.0, 0.6 + L[0] - 0.8)                   # intro phrase runs over A and into B
    start = {0: 0.6}
    bounds, prev = {}, a_len
    for i, (sid, _, _) in enumerate(CHAIN):
        b0 = prev; b1 = b0 + SEG
        if sid == "1.4-F":
            start[5] = b0 + 1.0; start[6] = start[5] + L[5] + 0.6; b1 = start[6] + L[6] + 1.0
        else:
            start[i + 1] = max(b1 - 0.9 - (0.35 if i else 0.0), start.get(i, 0) + L[i] + 0.25)
        bounds[sid] = (b0, b1); prev = b1
    word_at = {w: start[i + 1] + (0.35 if 0 < i < 4 else 0.9 if i == 4 else 0.0) for i, (_, _, w) in enumerate(CHAIN)}
    t = word_at
    vo = W / "vo_mix.wav"; total = prev
    import numpy as np, wave
    mix = np.zeros(int(24000 * (total + 1)), dtype=np.float32)
    for i, s0 in start.items():
        with wave.open(str(vo_dir / f"c{i}.wav")) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16 if w.getsampwidth() == 2 else np.int32).astype(np.float32)
            x /= 32768.0 if w.getsampwidth() == 2 else 2 ** 31
        k = int(s0 * 24000); mix[k:k + len(x)] += x[: len(mix) - k]
    with wave.open(str(vo), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    print("timeline", {"A": round(a_len, 2), **{k: (round(x, 2), round(y, 2)) for k, (x, y) in bounds.items()},
                       "phrases": {k: round(v, 2) for k, v in start.items()}}, flush=True)
    while not (s34.DW / "state.json").exists() or "close" not in json.load(open(s34.DW / "state.json")):
        time.sleep(10)
    D = json.load(open(s34.DW / "state.json"))
    close = comfy.to_input(D["close"]["brahma"], "s4_brahma_close.png"); sheet = comfy.to_input(D["chosen"]["brahma"], "s4_brahma_sheet.png")
    # A keyframe: same Brahma as in 1.3, now with the open palm in the lower third
    files, _ = comfy.run(comfy.g_keyframe(BR + "New vertical 9:16 frame: " + SH["1.4-A"]["keyframe_prompt"] + "; his open palm is centred in the "
                                          "lower third of the frame with clear space above it. Only Brahma. Style: " + s34.LOOK,
                                          [close, sheet], "srishti/s4/A_kf", 1600, 480, 832))
    a_kf = comfy.to_input(files[0], "s4_A_kf.png")
    files, sec = comfy.run(comfy.g_i2v(a_kf, SH["1.4-A"]["motion_prompt"] + ". " + s34.LOOK, "srishti/s4/A", 1601, s34.nframes(a_len)))
    a_vid = str(files[0]); print("1.4-A", sec, "s", flush=True)
    a_last = comfy.to_input(s34.last_frame(a_vid, W / "A_last.png", 480, 832), "s4_A_last.png")
    # five element keyframes, all edits of the same palm frame -> identical composition
    kfs = {}
    for _, k, _ in CHAIN:
        files, _ = comfy.run(comfy.g_keyframe("Keep EXACTLY this composition, Brahma, his open palm, camera and lighting. Change only what is "
                                              f"above the palm: {KF[k]}. Style: " + s34.LOOK, [a_last], f"srishti/s4/kf_{k}", 1610, 480, 832))
        kfs[k] = comfy.to_input(files[0], f"s4_kf_{k}.png"); print("kf", k, flush=True)
    vids, start = {}, a_last
    for sid, k, w in CHAIN:
        a, b = bounds[sid]
        files, sec = comfy.run(s34.g_flf(start, kfs[k], SH[sid]["motion_prompt"] + ", above Brahma's open palm. " + s34.LOOK,
                                         f"srishti/s4/{sid}", 1620, s34.nframes(b - a), 480, 832))
        vids[sid] = str(files[0]); start = kfs[k]; print(sid, sec, "s", flush=True)
    parts = [s34.norm(a_vid, W / "p_A.mp4", a_len, fade_in=0.4)]
    labels = []
    for sid, k, w in CHAIN:
        a, b = bounds[sid]
        parts.append(s34.norm(vids[sid], W / f"p_{sid}.mp4", b - a, fade_out=0.8 if sid == "1.4-F" else 0))
        labels.append((s34.label_png(SH[sid]["overlay"]["text"], W / f"label_{sid}.png"), t[w] - 0.1, min(b, t[w] + 1.8)))
    s34.finish(parts, labels, vo, 0.0, LINE["caption"], Path("/mnt/nvme/ComfyUI/output/srishti/clip_1.4.mp4"), W, cap_span=(0.6, total - 0.5))


if __name__ == "__main__":
    main()
