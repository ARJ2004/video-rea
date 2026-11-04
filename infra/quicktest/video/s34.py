"""Shared helpers for clips 1.3 and 1.4: text-to-image, first/last-frame video, word timings, overlays, assembly."""
import json, re, subprocess, textwrap
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
import comfy

J = Path(__file__).parent
SB = json.load(open(J / "storyboard.json"))
LOOK = SB["style"]["look"]
FPS, WD, HT = 30, 1080, 1920
DEV_FONT = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"
CAPF = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
GOLD = (246, 196, 83)
DEITY = {k: SB["characters"][k]["description"] for k in ("brahma", "vishnu", "shiva")}
DW = Path("/mnt/nvme/work3/deities")


def sh(*a):
    subprocess.run([str(x) for x in a], check=True)


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode())


def clip(cid):
    return next(c for c in SB["clips"] if c["id"] == cid)


def g_t2i(prompt, prefix, seed, w=720, h=1280):
    neg = SB["style"]["negative"]
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors", "strength_model": 1.0}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4", 0], "shift": 3.1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": neg}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
                                                    "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def g_flf(start, end, prompt, prefix, seed, frames, w, h):
    g = comfy.g_i2v(start, prompt, prefix, seed, frames, w, h)
    g["img2"] = {"class_type": "LoadImage", "inputs": {"image": end}}
    g["i2v"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": {
        "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["img", 0], "end_image": ["img2", 0],
        "width": w, "height": h, "length": frames, "batch_size": 1}}
    return g


def nframes(sec, fps=16, lo=33):
    n = max(lo, int(round(sec * fps)) + 1)
    return n + (4 - (n - 1) % 4) % 4


def last_frame(video, out, w=None, h=None):
    vf = ["-vf", f"scale={w}:{h}"] if w else []
    sh("ffmpeg", "-loglevel", "error", "-y", "-sseof", "-0.1", "-i", video, "-frames:v", "1", *vf, out)
    return out


def silences(f, db=-35, d=0.12):
    err = subprocess.run(["ffmpeg", "-i", str(f), "-af", f"silencedetect=n={db}dB:d={d}", "-f", "null", "-"], capture_output=True, text=True).stderr
    return list(zip([float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)], [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]))


def word_times(text, wav, words):
    """Approximate start time of each word: position by character share of the speech span, snapped to the end of a
    nearby pause (a word after a pause starts when the pause ends). Good to ~0.2 s for cutting and overlays."""
    D = dur(wav); sil = silences(wav)
    t0 = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    t1 = sil[-1][0] if sil and sil[-1][1] > D - 0.05 else D
    letters = re.sub(r"[\s\W]", "", text); n = len(letters)
    out = {}
    for w in words:
        i = text.index(w); share = len(re.sub(r"[\s\W]", "", text[:i])) / n
        t = t0 + share * (t1 - t0)
        ends = [e for s, e in sil if abs(e - t) < 0.45]
        out[w] = round(min(ends, key=lambda e: abs(e - t)) if ends else t, 2)
    return out, D


def label_png(text, out, size=150):
    font = ImageFont.truetype(DEV_FONT, size, layout_engine=ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC)
    im = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    bb = d.textbbox((0, 0), text, font=font)
    xy = ((WD - (bb[2] - bb[0])) / 2 - bb[0], HT * 0.16 - bb[1])
    glow = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); ImageDraw.Draw(glow).text(xy, text, font=font, fill=GOLD + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    d.text(xy, text, font=font, fill=(255, 236, 180, 255))
    Image.alpha_composite(glow, im).save(out)
    return out


def label2_png(main, sub, out, size=150):
    """Spoken word large (what the viewer hears) + the Sanskrit name smaller underneath."""
    eng = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    big, small = ImageFont.truetype(DEV_FONT, size, layout_engine=eng), ImageFont.truetype(DEV_FONT, int(size * 0.42), layout_engine=eng)
    im = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); glow = Image.new("RGBA", (WD, HT), (0, 0, 0, 0))
    d, g = ImageDraw.Draw(im), ImageDraw.Draw(glow)
    bb = d.textbbox((0, 0), main, font=big); xy = ((WD - (bb[2] - bb[0])) / 2 - bb[0], HT * 0.14 - bb[1])
    g.text(xy, main, font=big, fill=GOLD + (255,)); d.text(xy, main, font=big, fill=(255, 236, 180, 255))
    if sub and sub != main:
        sb = d.textbbox((0, 0), sub, font=small); sxy = ((WD - (sb[2] - sb[0])) / 2 - sb[0], xy[1] + bb[3] + 24 - sb[1])
        g.text(sxy, sub, font=small, fill=GOLD + (255,)); d.text(sxy, sub, font=small, fill=(255, 236, 180, 230))
    Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)), im).save(out)
    return out


def norm(src, out, L, fade_in=0, fade_out=0):
    vf = f"scale={WD}:{HT}:flags=lanczos,fps={FPS},tpad=stop_mode=clone:stop_duration={L + 1},format=yuv420p"
    if fade_in: vf += f",fade=t=in:st=0:d={fade_in}"
    if fade_out: vf += f",fade=t=out:st={L - fade_out:.3f}:d={fade_out}"
    sh("ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-t", f"{L:.3f}", "-an", "-c:v", "libx264", "-crf", "16", out)
    return out


def cap_chunks(caption, width=34, lines=2):
    """Split a caption into chunks of at most `lines` wrapped lines, breaking after punctuation where possible."""
    words = caption.split(); chunks, cur = [], []
    for w in words:
        if cur and len(textwrap.wrap(" ".join(cur + [w]), width)) > lines:
            # back up to the last word ending in punctuation, if that keeps the chunk at least half full
            k = max((i for i, x in enumerate(cur) if x[-1] in ",.;:!?—–"), default=-1)
            if k >= len(cur) // 2 and k < len(cur) - 1:
                chunks.append(" ".join(cur[:k + 1])); cur = cur[k + 1:]
            else:
                chunks.append(" ".join(cur)); cur = []
        cur.append(w)
    if cur: chunks.append(" ".join(cur))
    return chunks


def finish(parts, labels, vo, vo_start, caption, out, work, cap_span=None, cap_starts=None):
    """concat video parts; overlay labels [(png, t_in, t_out)]; VO at vo_start; caption during VO; -14 LUFS."""
    lst = work / "list.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
    video = work / "video.mp4"; sh("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video)
    total = dur(video)
    inputs = ["-i", video, "-i", vo]; fc = []; last = "0:v"
    for k, (png, a, b) in enumerate(labels):
        inputs += ["-loop", "1", "-t", f"{total:.2f}", "-i", png]
        fc.append(f"[{k + 2}:v]format=rgba,fade=t=in:st={a:.2f}:d=0.35:alpha=1,fade=t=out:st={b - 0.35:.2f}:d=0.35:alpha=1[l{k}]")
        fc.append(f"[{last}][l{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]"); last = f"v{k}"
    vl = dur(vo); c0, c1 = cap_span or (vo_start, vo_start + vl + 0.3)
    chunks = cap_chunks(caption); n = sum(len(c) for c in chunks); t = c0
    for j, ch in enumerate(chunks):                       # 2-line chunks, each on screen for its share of the speech
        if cap_starts and len(cap_starts) == len(chunks):  # explicit chunk start times (phrase-voiced clips)
            a = cap_starts[j]; t = c1 if j == len(chunks) - 1 else cap_starts[j + 1]
        else:
            a = t; t = c1 if j == len(chunks) - 1 else t + (c1 - c0) * len(ch) / n
        cf = work / f"cap{j}.txt"; cf.write_text("\n".join(textwrap.wrap(ch, 34)))
        out_l = "[v]" if j == len(chunks) - 1 else f"[c{j}]"
        fc.append(f"[{last}]drawtext=fontfile={CAPF}:textfile={cf}:fontsize=46:fontcolor=white:line_spacing=10:box=1:boxcolor=black@0.45:"
                  f"boxborderw=18:x=(w-text_w)/2:y=h-text_h-220:enable='between(t,{a:.2f},{t:.2f})':"
                  f"alpha='min(1,min((t-{a:.2f})/0.15,({t:.2f}-t)/0.15))'{out_l}"); last = out_l[1:-1]
    fc.append(f"[1:a]aresample=48000,adelay={int(vo_start * 1000)}|{int(vo_start * 1000)},apad,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    sh("ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
       "-t", f"{total:.2f}", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out)
    print("wrote", out, f"{dur(out):.1f}s", flush=True)
