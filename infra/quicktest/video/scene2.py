"""Clip 1.2 'The First Light' (20 s): void -> Om pulse (composited) -> burst -> light waves (Wan 2.2, chained
from the previous shot's last frame) + Dadi's VO (cloned voice) + synthesized heartbeat under the pulses."""
import json, math, subprocess, sys, textwrap
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import comfy

J = Path(__file__).parent
W = Path("/mnt/nvme/work3/s2"); W.mkdir(parents=True, exist_ok=True)
SB = json.load(open(J / "storyboard.json"))
CLIP = next(c for c in SB["clips"] if c["id"] == "1.2")
SH = {s["id"]: s for s in CLIP["shots"]}
LINE = CLIP["lines"][0]
FPS, WD, HT = 30, 1080, 1920
GOLD = (246, 196, 83)
FONT = next((p for p in ["/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
                         "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Bold.ttf"] if Path(p).exists()), None)
CAPF = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
VO = J / "voices" / "1.2-L1_f5_t1.wav"
B_START, B_LEN, PULSES = 4.0, 8.0, [1.6, 2.9, 4.1, 5.2, 6.2]  # pulse times inside 1.2-B (accelerating heartbeat)


def sh(*a):
    subprocess.run([str(x) for x in a], check=True)


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode())


def encode(frames_dir, out, n):
    sh("ffmpeg", "-loglevel", "error", "-y", "-framerate", FPS, "-i", frames_dir / "%05d.png", "-frames:v", n,
       "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out)


def void_bg(t):
    """Same look as pipeline/comp/void.sh (dark blue-black shimmer), as a numpy frame."""
    y, x = np.mgrid[0:HT // 4, 0:WD // 4].astype(np.float32) * 4
    lum = 24 + 7 * np.sin(0.02 * y + 2 * np.pi * t / 6 + 3 * np.sin(0.01 * x + 2 * np.pi * t / 3)) + 4 * np.sin(0.015 * x - 2 * np.pi * t / 2)
    img = Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).resize((WD, HT), Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
    a = np.asarray(img, dtype=np.float32)[..., None] / 255.0
    return np.concatenate([a * 0.55 * 255 / 255, a * 0.5, a * 0.75], axis=2) * 255  # cool tint


def radial(intensity, radius):
    y, x = np.mgrid[0:HT, 0:WD].astype(np.float32)
    d = np.sqrt((x - WD / 2) ** 2 + (y - HT * 0.45) ** 2) / radius
    g = np.exp(-d ** 2) * intensity
    return g[..., None] * np.array(GOLD, dtype=np.float32)[None, None, :]


def shot_a():
    d = W / "a"; d.mkdir(exist_ok=True); n = int(SH["1.2-A"]["dur_s"] * FPS)
    for i in range(n):
        t = i / FPS; k = t / SH["1.2-A"]["dur_s"]
        f = void_bg(t) + radial(0.2 * k ** 1.5, 520)
        Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)).save(d / f"{i:05d}.png")
    encode(d, W / "1.2-A.mp4", n); print("1.2-A done", flush=True)


def glyph_layer(scale, alpha):
    size = int(560 * scale)
    font = ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()
    im = Image.new("L", (WD, HT), 0); dr = ImageDraw.Draw(im)
    bb = dr.textbbox((0, 0), "ॐ", font=font)
    dr.text(((WD - (bb[2] - bb[0])) / 2 - bb[0], HT * 0.45 - (bb[3] - bb[1]) / 2 - bb[1]), "ॐ", font=font, fill=int(255 * alpha))
    return im


def shot_b():
    d = W / "b"; d.mkdir(exist_ok=True); n = int(B_LEN * FPS)
    for i in range(n):
        t = i / FPS
        emerge = min(1.0, max(0.0, (t - 0.3) / 1.6))           # rises out of the ripple
        pulse = sum(math.exp(-((t - p) / 0.13) ** 2) for p in PULSES)
        bright = 0.55 + 0.45 * (t / B_LEN)                      # brightness curve: increasing
        g = glyph_layer(1.0 + 0.06 * pulse, emerge * bright)
        glow = np.asarray(g.filter(ImageFilter.GaussianBlur(28)), dtype=np.float32)[..., None] / 255.0
        core = np.asarray(g.filter(ImageFilter.GaussianBlur(2 + 6 * (1 - emerge))), dtype=np.float32)[..., None] / 255.0
        f = void_bg(B_START + t) * (1 - 0.3 * emerge) + radial(0.2 + 0.25 * (t / B_LEN) + 0.25 * pulse, 520)
        f = f + glow * np.array(GOLD) * (1.4 + 1.2 * pulse) + core * np.array([255, 226, 150])
        Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)).save(d / f"{i:05d}.png")
    encode(d, W / "1.2-B.mp4", n)
    Image.open(d / f"{n - 1:05d}.png").resize((720, 1280), Image.LANCZOS).save(W / "1.2-B_last.png")
    print("1.2-B done", flush=True)


def heartbeat(out, total):
    sr = 48000; a = np.zeros(int(sr * total), dtype=np.float32)
    def thump(t0, amp, f0=55):
        n = int(0.18 * sr); tt = np.arange(n) / sr
        w = np.sin(2 * np.pi * f0 * tt * (1 - 0.3 * tt / 0.18)) * np.exp(-tt / 0.05) * amp
        s = int(t0 * sr); a[s:s + n] += w[: max(0, min(n, len(a) - s))]
    for k, p in enumerate(PULSES):
        amp = 0.35 + 0.1 * k
        thump(B_START + p - 0.02, amp); thump(B_START + p + 0.20, amp * 0.6, 48)   # lub-dub
    import wave
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def last_frame(video, out):
    sh("ffmpeg", "-loglevel", "error", "-y", "-sseof", "-0.1", "-i", video, "-frames:v", "1", "-vf", "scale=720:1280", out)


def shot_i2v(sid, start_png):
    s = SH[sid]; name = comfy.to_input(start_png, f"s2_{sid}_start.png")
    n = int(round(s["dur_s"] * 16)) + 1; n += (4 - (n - 1) % 4) % 4
    prompt = s["motion_prompt"] + ". Pure abstract cosmic light, no people, no text, no faces, deep indigo-black to radiant gold palette."
    files, sec = comfy.run(comfy.g_i2v(name, prompt, f"srishti/s2/{sid}", seed=710, frames=n, w=720, h=1280))
    print(sid, "i2v", sec, "s", flush=True)
    return str(files[0])


def assemble(c_vid, d_vid):
    parts = []
    for sid, src in [("1.2-A", W / "1.2-A.mp4"), ("1.2-B", W / "1.2-B.mp4"), ("1.2-C", c_vid), ("1.2-D", d_vid)]:
        o = W / f"seg_{sid}.mp4"; L = SH[sid]["dur_s"]
        sh("ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf",
           f"scale={WD}:{HT}:flags=lanczos,fps={FPS},tpad=stop_mode=clone:stop_duration=1,format=yuv420p", "-t", L, "-an",
           "-c:v", "libx264", "-crf", "16", o)
        parts.append(o)
    lst = W / "list.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
    video = W / "video.mp4"; sh("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video)
    total = sum(SH[s]["dur_s"] for s in SH)
    hb = W / "heartbeat.wav"; heartbeat(hb, total)
    vo_len = dur(VO)
    # VO lands its last words ("roshni phail gayi") on the burst at the start of 1.2-C (+0.8 s)
    vo_start = max(B_START + 0.5, B_START + B_LEN + 0.8 - vo_len)
    cap = W / "cap.txt"; cap.write_text("\n".join(textwrap.wrap(LINE["caption"], 34)))
    out = Path("/mnt/nvme/ComfyUI/output/srishti/clip_1.2.mp4")
    sh("ffmpeg", "-loglevel", "error", "-y", "-i", video, "-i", VO, "-i", hb, "-filter_complex",
       f"[1:a]aresample=48000,adelay={int(vo_start * 1000)}|{int(vo_start * 1000)},apad[vo];"
       f"[2:a]aresample=48000,volume=0.9,apad[hb];[vo][hb]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a];"
       f"[0:v]drawtext=fontfile={CAPF}:textfile={cap}:fontsize=46:fontcolor=white:line_spacing=10:box=1:boxcolor=black@0.45:"
       f"boxborderw=18:x=(w-text_w)/2:y=h-text_h-220:enable='between(t,{vo_start:.2f},{vo_start + vo_len + 0.3:.2f})'[v]",
       "-map", "[v]", "-map", "[a]", "-t", total, "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out)
    print("wrote", out, f"{dur(out):.1f}s", f"(VO {vo_len:.1f}s from {vo_start:.1f}s)", flush=True)


if __name__ == "__main__":
    comfy.wait_up()
    shot_a(); shot_b()
    c = shot_i2v("1.2-C", W / "1.2-B_last.png")
    last_frame(c, W / "1.2-C_last.png")
    d = shot_i2v("1.2-D", W / "1.2-C_last.png")
    assemble(c, d)
