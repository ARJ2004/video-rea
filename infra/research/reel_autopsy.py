"""Reel autopsy: measure what a set of short vertical videos actually does, so we copy what works, not what blogs say.

For each video (mp4/mov/webm) it measures, CPU only (ffmpeg + numpy):
  structure  duration, size, cuts (scene changes), first cut time, cuts in the first 3 s, shot lengths (mean/median/max),
             cuts per 10 s over time (does the pace speed up or slow down?)
  hook       motion in the first 1.5 s vs the rest, first-frame contrast / brightness / saturation,
             audio energy in the first 0.5 s vs the median (a "hit"), time until sound starts
  audio      integrated loudness (LUFS), share of near-silence, dynamic range of the energy envelope
  ending     how close the last frame is to the first (1.0 = perfect loop)
and writes, next to a JSON report, a contact sheet per video: the hook strip (0, 0.5, 1, 1.5, 2, 3 s) and the first
frame of every shot. Read the sheets for what numbers cannot capture (hook archetype, on-screen text, framing).

Usage:  python3 reel_autopsy.py <video or folder> [...] --out <dir> [--scene 0.3] [--meta meta.json]
  meta.json (optional): {"<file name>": {"page": "...", "views": 1234567, "likes": ..., "followers": ...}} - when views are
  given, the summary compares the top third of videos against the bottom third on every metric (what separates winners).
"""
import argparse, json, re, statistics as st, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

W, H, FPS_A = 72, 128, 10          # analysis frame size (9:16) and rate
VID = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def run(*a, **kw):
    return subprocess.run([str(x) for x in a], capture_output=True, **kw)


def probe(p):
    r = json.loads(run("ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", p).stdout or "{}")
    v = next((s for s in r.get("streams", []) if s["codec_type"] == "video"), {})
    a = any(s["codec_type"] == "audio" for s in r.get("streams", []))
    num, den = (v.get("avg_frame_rate", "0/1").split("/") + ["1"])[:2]
    return {"duration_s": round(float(r.get("format", {}).get("duration", 0)), 2), "width": v.get("width"), "height": v.get("height"),
            "fps": round(float(num) / float(den or 1), 2) if float(den or 1) else None, "has_audio": a}


def cuts(p, thr):
    err = run("ffmpeg", "-hide_banner", "-i", p, "-vf", f"select='gt(scene,{thr})',showinfo", "-an", "-f", "null", "-").stderr.decode("utf8", "replace")
    return [round(float(t), 2) for t in re.findall(r"pts_time:([0-9.]+)", err)]


def frames(p):
    raw = run("ffmpeg", "-v", "error", "-i", p, "-vf", f"fps={FPS_A},scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2", "-pix_fmt", "rgb24", "-f", "rawvideo", "-").stdout
    n = len(raw) // (W * H * 3)
    return np.frombuffer(raw[: n * W * H * 3], np.uint8).reshape(n, H, W, 3).astype(np.float32)


def audio(p, sr=16000):
    raw = run("ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-").stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0, sr


def lufs(p):
    err = run("ffmpeg", "-hide_banner", "-i", p, "-af", "ebur128", "-f", "null", "-").stderr.decode("utf8", "replace")
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", err)
    return float(m[-1]) if m else None


def grab(p, t, w=270):
    raw = run("ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", p, "-frames:v", "1", "-vf", f"scale={w}:-2", "-f", "image2pipe",
              "-vcodec", "png", "-").stdout
    from io import BytesIO
    try:
        return Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return Image.new("RGB", (w, w * 16 // 9), (40, 40, 40))


def sheet(p, rep, out):
    hook_t = [0, 0.5, 1, 1.5, 2, 3]
    shot_t = [0.0] + rep["cuts_s"]
    shot_t = shot_t[:18]
    tiles = [(f"{t:g}s", grab(p, t + 0.04)) for t in hook_t] + [(f"shot {i + 1} @{t:g}s", grab(p, t + 0.08)) for i, t in enumerate(shot_t)]
    tw, th = 270, max(im.height for _, im in tiles)
    cols = 6
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (cols * tw, rows * (th + 22) + 26), (18, 18, 18))
    d = ImageDraw.Draw(img)
    d.text((6, 6), f"{Path(p).name}  ·  hook strip (row 1) then the first frame of every shot", fill=(230, 230, 230))
    for i, (lab, im) in enumerate(tiles):
        x, y = (i % cols) * tw, 26 + (i // cols) * (th + 22)
        img.paste(im, (x, y + 20)); d.text((x + 4, y + 4), lab, fill=(250, 200, 80) if i < len(hook_t) else (200, 200, 200))
    img.save(out)


def analyse(p, thr):
    rep = {"file": Path(p).name, **probe(p)}
    dur = rep["duration_s"] or 0.01
    c = [t for t in cuts(p, thr) if 0.15 < t < dur - 0.1]
    rep["cuts_s"] = c
    bounds = [0.0] + c + [dur]
    shots = [round(b - a, 2) for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]
    rep.update({"shots": len(shots), "first_cut_s": c[0] if c else None, "cuts_in_first_3s": sum(t <= 3 for t in c),
                "shot_mean_s": round(st.mean(shots), 2), "shot_median_s": round(st.median(shots), 2), "shot_max_s": max(shots),
                "cuts_per_10s_by_quarter": [round(10 * sum(dur * q / 4 <= t < dur * (q + 1) / 4 for t in c) / (dur / 4), 1) for q in range(4)]})
    f = frames(p)
    if len(f) > 3:
        diff = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2, 3))
        k = int(1.5 * FPS_A)
        rest = float(np.median(diff[k:])) if len(diff) > k else float(np.median(diff))
        rep["hook_motion_ratio"] = round(float(np.mean(diff[:k])) / (rest + 1e-6), 2)     # >1: the opening moves more than the rest
        g = f[0].mean(axis=2)
        mx, mn = f[0].max(axis=2), f[0].min(axis=2)
        rep["first_frame"] = {"brightness": round(float(g.mean()) / 255, 2), "contrast": round(float(g.std()) / 255, 2),
                              "saturation": round(float(((mx - mn) / (mx + 1e-6)).mean()), 2)}
        rep["loop_similarity"] = round(1 - float(np.abs(f[-1] - f[0]).mean()) / 255, 2)
    if rep["has_audio"]:
        a, sr = audio(p)
        if len(a) > sr // 2:
            hop = sr // 20                                   # 50 ms envelope
            env = np.sqrt(np.convolve(a ** 2, np.ones(hop) / hop, "valid")[::hop] + 1e-12)
            db = 20 * np.log10(env + 1e-9)
            med = float(np.median(db))
            rep["audio"] = {"lufs": lufs(p), "hit_first_0_5s_db": round(float(db[:10].max()) - med, 1),
                            "sound_starts_s": round(float(np.argmax(db > med - 6)) * 0.05, 2),
                            "silence_share": round(float(np.mean(db < med - 25)), 2),
                            "dynamic_range_db": round(float(np.percentile(db, 95) - np.percentile(db, 10)), 1)}
    return rep


FLAT = [("duration_s", "duration_s"), ("first_cut_s", "first_cut_s"), ("cuts_in_first_3s", "cuts_in_first_3s"),
        ("shot_mean_s", "shot_mean_s"), ("shot_median_s", "shot_median_s"), ("hook_motion_ratio", "hook_motion_ratio"),
        ("first_frame.contrast", "ff_contrast"), ("first_frame.saturation", "ff_saturation"), ("loop_similarity", "loop_similarity"),
        ("audio.hit_first_0_5s_db", "hit_db"), ("audio.sound_starts_s", "sound_starts_s"), ("audio.lufs", "lufs"),
        ("audio.silence_share", "silence_share")]


def get(r, path):
    for k in path.split("."):
        r = (r or {}).get(k) if isinstance(r, dict) else None
    return r


def summary(reps, meta):
    def med(rs, path):
        xs = [get(r, path) for r in rs if isinstance(get(r, path), (int, float))]
        return round(st.median(xs), 2) if xs else None
    out = {"videos": len(reps), "median": {name: med(reps, path) for path, name in FLAT}}
    ranked = [r for r in reps if (meta.get(r["file"]) or {}).get("views")]
    if len(ranked) >= 6:
        ranked.sort(key=lambda r: meta[r["file"]]["views"], reverse=True)
        k = len(ranked) // 3
        top, bot = ranked[:k], ranked[-k:]
        out["top_vs_bottom_third_by_views"] = {name: {"top": med(top, path), "bottom": med(bot, path)} for path, name in FLAT}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+"); ap.add_argument("--out", required=True)
    ap.add_argument("--scene", type=float, default=0.3, help="scene-change threshold (lower finds more cuts)")
    ap.add_argument("--meta", help="json with views/likes per file name")
    a = ap.parse_args()
    files = []
    for i in a.inputs:
        p = Path(i)
        files += sorted(x for x in p.rglob("*") if x.suffix.lower() in VID) if p.is_dir() else [p]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    meta = json.loads(Path(a.meta).read_text()) if a.meta else {}
    reps = []
    for p in files:
        try:
            r = analyse(str(p), a.scene); r.update(meta.get(p.name) or {})
            sheet(str(p), r, out / f"{p.stem}_sheet.jpg"); reps.append(r)
            print(f"{p.name}: {r['duration_s']} s, {r['shots']} shots, first cut {r['first_cut_s']} s, "
                  f"median shot {r['shot_median_s']} s, hit {get(r, 'audio.hit_first_0_5s_db')} dB", flush=True)
        except Exception as e:
            print(f"{p.name}: failed ({e})", file=sys.stderr)
    (out / "autopsy.json").write_text(json.dumps({"summary": summary(reps, meta), "videos": reps}, indent=1))
    print(json.dumps(summary(reps, meta), indent=1))


if __name__ == "__main__":
    main()
