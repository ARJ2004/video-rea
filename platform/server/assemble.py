"""CPU-side assembly on the server (ffmpeg): clip = approved shots + voice + timed captions + labels; episode = clips joined
with short dissolves + end card + loudness -14 LUFS + an automatic QA report (visual jumps, loudness, duration).
Lessons from Episode 1 built in: chained shots are retimed to fit (never trimmed), captions are 2-line chunks timed to the
voice, audio is laid per segment and mixed (no word is faded out at a join)."""
import json, os, re, subprocess, tempfile, textwrap, uuid
from pathlib import Path
import boto3
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
from db import one, q

BUCKET = os.environ.get("VREA_BUCKET", "vrea-686112930191-us-east-1")
s3 = boto3.client("s3", region_name=os.environ.get("VREA_REGION", "us-east-1"))
WD, HT, FPS = 1080, 1920, 30
CAPF = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
DEVF = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"
GOLD = (246, 196, 83)


def sh(*a):
    subprocess.run([str(x) for x in a], check=True, capture_output=True)


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode())


def has_audio(f):
    return bool(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(f)]).strip())


def get(key, d):
    p = Path(d) / (uuid.uuid4().hex[:8] + Path(key).suffix); s3.download_file(BUCKET, key, str(p)); return p


def put(path, task, ext):
    key = f"projects/{task['project_id']}/{task['slot_key'].replace(':', '_')}/r{task['round']}_{uuid.uuid4().hex[:10]}{ext}"
    s3.upload_file(str(path), BUCKET, key); return key


def chosen(pid, key):
    r = one("SELECT a.s3_key, a.meta FROM slots s JOIN assets a ON a.id=s.chosen_asset WHERE s.project_id=%s AND s.key=%s", pid, key)
    return r


def cap_chunks(caption, width=34, lines=2):
    words, chunks, cur = caption.split(), [], []
    for w in words:
        if cur and len(textwrap.wrap(" ".join(cur + [w]), width)) > lines:
            k = max((i for i, x in enumerate(cur) if x[-1] in ",.;:!?—–"), default=-1)
            if len(cur) // 2 <= k < len(cur) - 1:
                chunks.append(" ".join(cur[:k + 1])); cur = cur[k + 1:]
            else:
                chunks.append(" ".join(cur)); cur = []
        cur.append(w)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


SYMF = next((f for f in ("/usr/share/fonts/truetype/noto/NotoSansSymbols-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if Path(f).exists()), DEVF)


def runs(text):
    """Split a label into runs: Devanagari/Latin text in the Devanagari font, symbols (arrows etc.) in a symbols font."""
    out = []
    for ch in text:
        sym = 0x2190 <= ord(ch) <= 0x2BFF          # arrows, math operators, misc symbols: not in Noto Sans Devanagari
        if out and out[-1][1] == sym:
            out[-1][0] += ch
        else:
            out.append([ch, sym])
    return out


def label_png(text, out, size=130):
    eng = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    fonts = {False: ImageFont.truetype(DEVF, size, layout_engine=eng), True: ImageFont.truetype(SYMF, int(size * 0.8), layout_engine=eng)}
    im = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    parts = [(t, fonts[sym]) for t, sym in runs(text)]
    widths = [d.textlength(t, font=f) for t, f in parts]
    base = d.textbbox((0, 0), "क", font=fonts[False])
    x = (WD - sum(widths)) / 2; y = HT * 0.14 - base[1]
    glow = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); g = ImageDraw.Draw(glow)
    for (t, f), w in zip(parts, widths):
        if f is fonts[False]:
            dy = 0
        else:                                                   # centre the symbol on the Devanagari letters
            sb = d.textbbox((0, 0), t, font=f); dy = (base[1] + base[3]) / 2 - (sb[1] + sb[3]) / 2
        g.text((x, y + dy), t, font=f, fill=GOLD + (255,)); d.text((x, y + dy), t, font=f, fill=(255, 236, 180, 255)); x += w
    Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)), im).save(out); return out


def norm(src, out, L):
    """Retime ALL frames of a shot to exactly L seconds (speed change, no trim), 1080x1920 @30, no audio."""
    n = int(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v", "-count_frames", "-show_entries", "stream=nb_read_frames",
                                     "-of", "csv=p=0", str(src)]).decode().strip())
    nat = dur(src); f = L / max(nat, 0.1) if nat > 0 else 1.0
    vf = f"setpts=(PTS-STARTPTS)*{f:.5f},fps={FPS},scale={WD}:{HT}:flags=lanczos,tpad=stop_mode=clone:stop_duration=1,format=yuv420p"
    sh("ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-t", f"{L:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out)
    return out, n


def mix(tracks, total, out):
    """tracks: [(wav/mp4 path, start_s)] -> one 48 kHz stereo track of length total."""
    if not tracks:
        sh("ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", out); return out
    ins, fc = [], []
    for i, (p, t0) in enumerate(tracks):
        ins += ["-i", str(p)]
        fc.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(t0 * 1000)}:all=1[a{i}]")
    fc.append("".join(f"[a{i}]" for i in range(len(tracks))) + f"amix=inputs={len(tracks)}:normalize=0:duration=longest,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{total:.3f}[a]")      # clip previews at -14 LUFS too
    sh("ffmpeg", "-loglevel", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[a]", out); return out


def burn(video, audio, caps, labels, out, work):
    """caps: [(text, t0, t1)] 2-line chunks; labels: [(png, t0, t1)]."""
    ins, fc, last = ["-i", str(video), "-i", str(audio)], [], "0:v"
    total = dur(video)
    for k, (png, a, b) in enumerate(labels):
        ins += ["-loop", "1", "-t", f"{total:.2f}", "-i", str(png)]
        fc.append(f"[{k + 2}:v]format=rgba,fade=t=in:st={a:.2f}:d=0.35:alpha=1,fade=t=out:st={max(a, b - 0.35):.2f}:d=0.35:alpha=1[l{k}]")
        fc.append(f"[{last}][l{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]"); last = f"v{k}"
    for j, (text, a, b) in enumerate(caps):
        # trailing space: this ffmpeg drops a multi-byte character (e.g. an em dash) when it is the last byte of the text
        cf = Path(work) / f"cap{j}.txt"; cf.write_text("\n".join(textwrap.wrap(text, 34)) + " ", encoding="utf-8")
        fc.append(f"[{last}]drawtext=fontfile={CAPF}:textfile={cf}:fontsize=46:fontcolor=white:line_spacing=10:box=1:boxcolor=black@0.45:"
                  f"boxborderw=18:x=(w-text_w)/2:y=h-text_h-220:enable='between(t,{a:.2f},{b:.2f})':"
                  f"alpha='min(1,min((t-{a:.2f})/0.15,({b:.2f}-t)/0.15))'[c{j}]"); last = f"c{j}"
    args = ["ffmpeg", "-loglevel", "error", "-y", *ins]
    if fc:
        args += ["-filter_complex", ";".join(fc), "-map", f"[{last}]"]
    else:
        args += ["-map", "0:v"]
    args += ["-map", "1:a", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-c:a", "aac", "-b:a", "192k", str(out)]
    sh(*args); return out


def line_caps(caption, t0, t1):
    ch = cap_chunks(caption); n = sum(len(c) for c in ch) or 1; t, out = t0, []
    for i, c in enumerate(ch):
        a = t; t = t1 if i == len(ch) - 1 else t + (t1 - t0) * len(c) / n; out.append((c, a, t))
    return out


def clip_task(task):
    pid = task["project_id"]; cid = task["params"]["clip_id"]
    sb = one("SELECT storyboard FROM projects WHERE id=%s", pid)["storyboard"]
    c = next(x for x in sb["clips"] if x["id"] == cid)
    lines = {l["id"]: l for l in c.get("lines", [])}
    talk_lines = {s["line"] for s in c["shots"] if s["tech"] == "TALK"}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vids = {s["id"]: get(chosen(pid, f"video:{s['id']}")["s3_key"], d) for s in c["shots"]}
        vo = [(lid, get(chosen(pid, f"voice:{lid}")["s3_key"], d)) for lid in lines if lid not in talk_lines]
        # durations: talking heads keep their own length; other shots get their storyboard length, stretched if the voice-over needs it
        lens = {s["id"]: (dur(vids[s["id"]]) if s["tech"] == "TALK" else float(s.get("dur_s", 3))) for s in c["shots"]}
        vo_need = 0.5 + sum(dur(p) for _, p in vo) + 0.35 * max(0, len(vo) - 1) + 0.8
        non_talk = [s["id"] for s in c["shots"] if s["tech"] != "TALK"]
        have = sum(lens[i] for i in non_talk)
        if vo and non_talk and vo_need > have:
            k = vo_need / have
            for i in non_talk:
                lens[i] *= k
        parts, t, tracks, caps, labels, starts = [], 0.0, [], [], [], {}
        for s in c["shots"]:
            p, _ = norm(vids[s["id"]], d / f"n_{s['id']}.mp4", lens[s["id"]]); parts.append(p); starts[s["id"]] = t
            if s["tech"] == "TALK" and has_audio(vids[s["id"]]):
                tracks.append((vids[s["id"]], t)); l = lines.get(s["line"])
                if l:
                    caps += line_caps(l["caption"], t + 0.1, t + lens[s["id"]] - 0.1)
            ov = s.get("overlay")
            if ov and ov.get("text"):
                labels.append((label_png(ov["text"], d / f"lab_{s['id']}.png"), t + 0.3, t + lens[s["id"]] - 0.2))
            t += lens[s["id"]]
        total = t
        if vo:
            vt = starts[non_talk[0]] + 0.5
            for lid, p in vo:
                L = dur(p); tracks.append((p, vt)); caps += line_caps(lines[lid]["caption"], vt, vt + L + 0.2); vt += L + 0.35
        (d / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
        sh("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", d / "list.txt", "-c", "copy", d / "video.mp4")
        audio = mix(tracks, total, d / "audio.wav")
        out = burn(d / "video.mp4", audio, caps, labels, d / f"clip_{cid}.mp4", d)
        key = put(out, task, ".mp4")
        return [{"s3_key": key, "kind": "video", "meta": {"duration": round(dur(out), 2), "shots": len(parts), "voice_over_lines": len(vo)},
                 "scores": {"rank": 1}}]


def jumps(path):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", "scale=72:128,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 128, 72).astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)); out = []
    for i in range(len(d)):
        nb = np.concatenate([d[max(0, i - 8):i], d[i + 1:i + 9]]); base = float(np.median(nb)) if len(nb) else 0
        if d[i] > 30 and d[i] > 4 * max(base, 1.0):
            out.append(round((i + 1) / FPS, 2))
    return out


def episode_task(task):
    pid = task["project_id"]; proj = one("SELECT title, storyboard FROM projects WHERE id=%s", pid); sb = proj["storyboard"]
    X = 0.6
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        clips = [get(chosen(pid, f"clip:{c['id']}")["s3_key"], d) for c in sb["clips"]]
        end = next((s["end_card"] for c in sb["clips"] for s in c["shots"] if s.get("end_card")), None)
        if end:
            ec = d / "endcard.mp4"; txt = d / "end.txt"; txt.write_text(end.get("text", proj["title"]))
            sh("ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x0b0814:s={WD}x{HT}:r={FPS}:d={end.get('dur_s', 2)}",
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", f"drawtext=fontfile={CAPF}:textfile={txt}:fontsize=72:fontcolor=0xf6c453:"
               "x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p", "-t", str(end.get("dur_s", 2)), "-c:v", "libx264", "-c:a", "aac", "-ar", "48000", ec)
            clips.append(ec)
        lens = [dur(c) for c in clips]; ins, fc, starts, t = [], [], [], 0.0
        for i, c in enumerate(clips):
            starts.append(0.0 if i == 0 else t - X); t = starts[-1] + lens[i]
            ins += ["-i", str(c)]
            fc.append(f"[{i}:v]fps={FPS},scale={WD}:{HT},setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
            fc.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,adelay={int(starts[-1] * 1000)}:all=1[a{i}]")
        total, last, acc = t, "v0", lens[0]
        for i in range(1, len(clips)):
            off = acc - X; fc.append(f"[{last}][v{i}]xfade=transition=fade:duration={X}:offset={off:.3f}[x{i}]"); last = f"x{i}"; acc = off + lens[i]
        fc.append("".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0:duration=longest,"
                  f"loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.3f}[a]")
        out = d / "episode.mp4"
        sh("ffmpeg", "-loglevel", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
        err = subprocess.run(["ffmpeg", "-i", str(out), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
        lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
        joins = [round(s, 2) for s in starts[1:]]
        cuts = jumps(out)
        qa = {"duration_s": round(dur(out), 2), "loudness_lufs": float(lufs[-1]) if lufs else None, "clip_joins_at_s": joins,
              "hard_cuts_at_s": cuts, "hard_cuts_inside_joins": [c for c in cuts if any(j - 0.1 <= c <= j + X + 0.1 for j in joins)]}
        key = put(out, task, ".mp4")
        return [{"s3_key": key, "kind": "video", "meta": {"qa": qa}, "scores": {"rank": 1}}]


CPU_HANDLERS = {"clip": clip_task, "episode": episode_task}
