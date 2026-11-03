"""Clip 1.3 'Tridev Appear': golden field + breathing Om -> unfurls into three lights (FLF) -> crystallize into the
Tridev (FLF, ends on the group keyframe) -> close shots of Brahma/Vishnu/Shiva cut on Dadi's words, with अ/उ/म."""
import json, math, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import comfy, s34

W = Path("/mnt/nvme/work3/s3"); W.mkdir(parents=True, exist_ok=True)
C = s34.clip("1.3"); SH = {s["id"]: s for s in C["shots"]}; LINE = C["lines"][0]
VO = s34.J / "voices" / "1.3-L1_f5_t1.wav"; VO_START = 1.0
HQ = (720, 1280)


def om_frames(bg_video, out, L):
    """Composite a steady, breathing golden Om over the swirling background video."""
    d = W / "a"; d.mkdir(exist_ok=True)
    s34.sh("ffmpeg", "-loglevel", "error", "-y", "-i", bg_video, "-vf", f"scale={s34.WD}:{s34.HT},fps={s34.FPS}", "-t", L, d / "bg_%05d.png")
    font = ImageFont.truetype(s34.DEV_FONT, 560)
    base = Image.new("L", (s34.WD, s34.HT), 0); dr = ImageDraw.Draw(base); bb = dr.textbbox((0, 0), "ॐ", font=font)
    dr.text(((s34.WD - (bb[2] - bb[0])) / 2 - bb[0], s34.HT * 0.45 - (bb[3] - bb[1]) / 2 - bb[1]), "ॐ", font=font, fill=255)
    glow = np.asarray(base.filter(ImageFilter.GaussianBlur(30)), dtype=np.float32)[..., None] / 255
    core = np.asarray(base.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)[..., None] / 255
    frames = sorted(d.glob("bg_*.png"))
    for i, f in enumerate(frames):
        b = 0.85 + 0.15 * math.sin(2 * math.pi * i / s34.FPS / 2.5)            # slow breathing
        img = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32) * 0.8
        img = img + glow * np.array(s34.GOLD) * 1.6 * b + core * np.array([255, 232, 170]) * b
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(d / f"{i:05d}.png")
    s34.sh("ffmpeg", "-loglevel", "error", "-y", "-framerate", s34.FPS, "-i", d / "%05d.png", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out)
    return out


def main():
    comfy.wait_up()
    words, vo_len = s34.word_times(LINE["tts"], VO, ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    vo_start = max(VO_START, 9.0 - words["अ से ब्रह्मा"])          # A+B+C get at least 9 s before Brahma appears
    tD, tE, tF = (vo_start + words[w] - 0.15 for w in ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    end = vo_start + vo_len + 0.8
    la, lb = tD * 4 / 15, tD * 5 / 15; lc = tD - la - lb                 # storyboard ratio 4:5:6
    print("timeline", dict(vo_start=round(vo_start, 2), A=round(la, 2), B=round(lb, 2), C=round(lc, 2), D=round(tD, 2),
                           E=round(tE, 2), F=round(tF, 2), end=round(end, 2)), flush=True)
    # A: swirling golden field (t2i -> i2v) + breathing Om
    files, _ = comfy.run(s34.g_t2i("abstract soft swirling golden light field, glowing mist and gentle luminous swirls, deep indigo edges, "
                                   "no symbols, no text, no people, vertical, " + s34.LOOK, "srishti/s3/field", 1500))
    field = comfy.to_input(files[0], "s3_field.png")
    files, sec = comfy.run(comfy.g_i2v(field, "soft golden light slowly swirls and breathes, gentle luminous mist, calm", "srishti/s3/A_bg",
                                       1501, s34.nframes(la), *HQ)); print("1.3-A bg", sec, "s", flush=True)
    a_vid = om_frames(str(files[0]), W / "1.3-A.mp4", la)
    a_last = s34.last_frame(a_vid, W / "A_last.png", *HQ)
    # B end keyframe: same field, Om replaced by three light forms
    a_in = comfy.to_input(a_last, "s3_A_last.png")
    files, _ = comfy.run(comfy.g_keyframe("Keep exactly this golden light field background and lighting. Replace the glowing Om symbol with "
                                          + SH["1.3-B"]["last_frame_prompt"] + ". No text, no symbols. Style: " + s34.LOOK,
                                          [a_in], "srishti/s3/B_end", 1502))
    b_end = comfy.to_input(files[0], "s3_B_end.png")
    files, sec = comfy.run(s34.g_flf(a_in, b_end, SH["1.3-B"]["motion_prompt"] + ". golden light, no text.", "srishti/s3/B", 1503,
                                     s34.nframes(lb), *HQ)); b_vid = str(files[0]); print("1.3-B", sec, "s", flush=True)
    # C: the three lights crystallize into the Tridev (ends on the shared group keyframe)
    while not (s34.DW / "state.json").exists() or "close" not in json.load(open(s34.DW / "state.json")):
        time.sleep(10)
    D = json.load(open(s34.DW / "state.json"))
    grp = comfy.to_input(D["group"], "s3_group.png")
    files, sec = comfy.run(s34.g_flf(b_end, grp, SH["1.3-C"]["motion_prompt"], "srishti/s3/C", 1504, s34.nframes(lc), *HQ))
    c_vid = str(files[0]); print("1.3-C", sec, "s", flush=True)
    # D/E/F: close shots (cropped from the group frame), cut on the names
    seg = {"1.3-D": ("brahma", tD, tE), "1.3-E": ("vishnu", tE, tF), "1.3-F": ("shiva", tF, end)}
    vids = {}
    for sid, (k, a, b) in seg.items():
        kf = comfy.to_input(D["close"][k], f"s3_close_{k}.png")
        files, sec = comfy.run(comfy.g_i2v(kf, SH[sid]["motion_prompt"] + ". " + s34.LOOK, f"srishti/s3/{sid}", 1505, s34.nframes(b - a)))
        vids[sid] = str(files[0]); print(sid, sec, "s", flush=True)
    parts = [s34.norm(a_vid, W / "p_A.mp4", la, fade_in=0.5), s34.norm(b_vid, W / "p_B.mp4", lb), s34.norm(c_vid, W / "p_C.mp4", lc)]
    labels = []
    for sid, (k, a, b) in seg.items():
        parts.append(s34.norm(vids[sid], W / f"p_{sid}.mp4", b - a, fade_out=0.8 if sid == "1.3-F" else 0))
        labels.append((s34.label_png(SH[sid]["overlay"]["text"], W / f"label_{sid}.png", 220), a + 0.25, min(b, a + 2.6)))
    s34.finish(parts, labels, VO, vo_start, LINE["caption"], Path("/mnt/nvme/ComfyUI/output/srishti/clip_1.3.mp4"), W)


if __name__ == "__main__":
    main()
