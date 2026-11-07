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
import audio_fx, overlays

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
            k = max((i for i, x in enumerate(cur) if x[-1] in ",.;:!?—–-"), default=-1)
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
    nat = dur(src); f = min(L / max(nat, 0.1), 1.5) if nat > 0 else 1.0    # slow down at most 1.5x, then hold the last frame
    hold = max(1.0, L - nat * f + 0.5)
    vf = f"setpts=(PTS-STARTPTS)*{f:.5f},fps={FPS},scale={WD}:{HT}:flags=lanczos,tpad=stop_mode=clone:stop_duration={hold:.2f},format=yuv420p"
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


PLAIN = {"\u2014": " - ", "\u2013": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " "}


def plain(text):
    """Captions are Hinglish (Latin script). This server's ffmpeg drawtext garbles multi-byte punctuation in wrapped,
    multi-line text (an em dash rendered as one or two boxes), so typographic punctuation becomes plain ASCII."""
    for a, b in PLAIN.items():
        text = text.replace(a, b)
    return " ".join(text.split())


def line_caps(caption, t0, t1):
    ch = cap_chunks(plain(caption)); n = sum(len(c) for c in ch) or 1; t, out = t0, []
    for i, c in enumerate(ch):
        a = t; t = t1 if i == len(ch) - 1 else t + (t1 - t0) * len(c) / n; out.append((c, a, t))
    return out


def silences(f, db=-35, d=0.12):
    err = subprocess.run(["ffmpeg", "-i", str(f), "-af", f"silencedetect=n={db}dB:d={d}", "-f", "null", "-"], capture_output=True, text=True).stderr
    return list(zip([float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)], [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]))


def letters(x):
    return re.sub(r"[\s\W]", "", x)


def phrase_starts(text, wav, phrases):
    """Start time of each phrase inside one recorded line. A first estimate comes from the character share of the speech
    span; then ALL boundaries are snapped together to the line's pauses (in order, each pause used once) choosing the
    assignment closest to the estimates overall (dynamic programming). Phrases split at punctuation, where the voice
    pauses, so this finds the real cut points even where the character estimate runs late (Ep2 2.3: 'पंछी')."""
    D = dur(wav); sil = silences(wav)
    t0 = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    t1 = sil[-1][0] if sil and sil[-1][1] > D - 0.05 else D
    n = len(letters(text))
    est = [t0 + len(letters(text[:text.index(ph)])) / n * (t1 - t0) for ph in phrases[1:]]
    ends = [e for a, e in sil if t0 + 0.2 < e < t1 - 0.1]           # pause ends inside the speech
    TOL, MISS = 1.0, 0.6                                             # snap window; cost of leaving a boundary unsnapped
    INF = float("inf")
    # best[i][j]: min cost placing boundaries 0..i-1 using only pauses before index j
    k, m = len(est), len(ends)
    best = [[INF] * (m + 1) for _ in range(k + 1)]; choice = [[None] * (m + 1) for _ in range(k + 1)]
    for j in range(m + 1):
        best[0][j] = 0.0
    for i in range(1, k + 1):
        for j in range(m + 1):
            c = best[i - 1][j] + MISS                               # boundary i-1 not snapped
            if c < best[i][j]:
                best[i][j], choice[i][j] = c, ("miss", j)
            if j > 0:
                c2 = best[i][j - 1]                                  # pause j-1 skipped
                if c2 < best[i][j]:
                    best[i][j], choice[i][j] = c2, ("skip", j - 1)
                if abs(ends[j - 1] - est[i - 1]) < TOL:
                    c3 = best[i - 1][j - 1] + abs(ends[j - 1] - est[i - 1])
                    if c3 < best[i][j]:
                        best[i][j], choice[i][j] = c3, ("snap", j - 1)
    out, i, j = [None] * k, k, m
    while i > 0:
        kind, jj = choice[i][j]
        if kind == "snap":
            out[i - 1] = ends[jj]; i, j = i - 1, jj
        elif kind == "skip":
            j = jj
        else:
            out[i - 1] = None; i -= 1
    starts, prev = [round(t0, 3)], t0
    for e, x in zip(est, out):
        v = x if x is not None else e
        v = max(v, prev + 0.3); starts.append(round(v, 3)); prev = v
    return starts, t1


def cut(wav, a, b, out):
    L = max(0.05, b - a)
    sh("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{L:.3f}", "-i", wav, "-af",
       f"afade=t=in:d=0.02,afade=t=out:st={max(0, L - 0.04):.3f}:d=0.04", out)
    return out


def split_caption(caption, text, phrases):
    """No per-shot caption given: split the line's caption at the same word share as the phrases split the spoken text."""
    words = plain(caption).split(); n = len(letters(text)); cuts = []
    for ph in phrases[1:]:
        cuts.append(round(len(letters(text[:text.index(ph)])) / n * len(words)))
    bounds = [0] + cuts + [len(words)]
    return [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]


def clip_task(task):
    pid = task["project_id"]; cid = task["params"]["clip_id"]
    sb = one("SELECT storyboard FROM projects WHERE id=%s", pid)["storyboard"]
    c = next(x for x in sb["clips"] if x["id"] == cid)
    lines = {l["id"]: l for l in c.get("lines", [])}
    talk_lines = {s["line"] for s in c["shots"] if s["tech"] == "TALK"}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        vids = {s["id"]: get(chosen(pid, f"video:{s['id']}")["s3_key"], d) for s in c["shots"]}
        per_shot = {lid for s in c["shots"] for lid in s.get("vo_lines", [])}     # voice-only lines placed on a named shot
        vo = [(lid, get(chosen(pid, f"voice:{lid}")["s3_key"], d)) for lid in lines if lid not in talk_lines and lid not in per_shot]
        shot_vo = {}
        for s in c["shots"]:
            for lid in s.get("vo_lines", []):
                src = get(chosen(pid, f"voice:{lid}")["s3_key"], d)
                fx = lines[lid].get("fx")
                shot_vo.setdefault(s["id"], []).append((lid, audio_fx.voice_fx(src, fx, d / f"fx_{lid}.wav") if fx else src))
        # durations: talking heads keep their own length; other shots get their storyboard length, stretched if the voice-over needs it
        lens = {s["id"]: (dur(vids[s["id"]]) if s["tech"] == "TALK" else float(s.get("dur_s", 3))) for s in c["shots"]}
        for sid, lst in shot_vo.items():                                    # a shot lasts at least as long as its lines
            need = 0.3 + sum(dur(p) for _, p in lst) + 0.35 * (len(lst) - 1) + 0.6
            if sid in lens and need > lens[sid]:
                lens[sid] = need
        non_talk = [s["id"] for s in c["shots"] if s["tech"] != "TALK"]
        shots_nt = [s for s in c["shots"] if s["tech"] != "TALK"]
        # narration mapped to shots: every narrated shot names its phrase ("vo") -> that phrase plays on that shot
        mapped = None
        if len(vo) == 1 and shots_nt and all(s.get("vo") and s["vo"] in lines[vo[0][0]]["tts"] for s in shots_nt):
            lid, wav = vo[0]; text = lines[lid]["tts"]; phrases = [s["vo"] for s in shots_nt]
            starts_in, end_in = phrase_starts(text, wav, phrases)
            caps_nt = [s.get("vo_caption") for s in shots_nt]
            if not all(caps_nt):
                caps_nt = split_caption(lines[lid]["caption"], text, phrases)
            mapped = {}
            for i, s in enumerate(shots_nt):
                a = starts_in[i]; b = starts_in[i + 1] if i + 1 < len(shots_nt) else end_in + 0.15
                seg = cut(wav, a, b, d / f"vo_{s['id']}.wav"); L = dur(seg)
                mapped[s["id"]] = (seg, L, plain(caps_nt[i]))
                lens[s["id"]] = max(lens[s["id"]], L + 0.3 + 0.6)          # the shot lasts at least as long as its phrase
            vo = []
        vo_need = 0.5 + sum(dur(p) for _, p in vo) + 0.35 * max(0, len(vo) - 1) + 0.8
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
            if mapped and s["id"] in mapped:
                seg, L, cap = mapped[s["id"]]
                tracks.append((seg, t + 0.3)); caps += line_caps(cap, t + 0.3, t + 0.3 + L + 0.2)
            vt = t + 0.3
            for lid, pth in shot_vo.get(s["id"], []):                       # radio / narrator / off-screen lines on this shot
                L = dur(pth); tracks.append((pth, vt)); caps += line_caps(lines[lid]["caption"], vt, vt + L + 0.2); vt += L + 0.35
            tracks += audio_fx.sfx_tracks(s, t, d)
            labels += overlays.shot_overlays(s, t, lens[s["id"]], d, label_png)
            t += lens[s["id"]]
        total = t
        if vo:
            vt = starts[non_talk[0]] + 0.5
            for lid, p in vo:
                L = dur(p); tracks.append((p, vt)); caps += line_caps(lines[lid]["caption"], vt, vt + L + 0.2); vt += L + 0.35
        if c.get("ambience"):
            tracks.append((audio_fx.ambience(c["ambience"], total, d / "amb.wav"), 0.0))
        if c.get("music") == "drone":
            tracks.append((audio_fx.drone(total, d / "drone.wav"), 0.0))
        (d / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
        sh("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", d / "list.txt", "-c", "copy", d / "video.mp4")
        audio = mix(tracks, total, d / "audio.wav")
        out = burn(d / "video.mp4", audio, caps, labels, d / f"clip_{cid}.mp4", d)
        key = put(out, task, ".mp4")
        return [{"s3_key": key, "kind": "video", "meta": {"duration": round(dur(out), 2), "shots": len(parts), "voice_over_lines": len(vo), "narration_mapped_to_shots": bool(mapped),
                                                         "voice_lines_on_shots": sum(len(v) for v in shot_vo.values())},
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


def still_task(task):
    """Animate an approved keyframe without a video model: slow push-in plus a gentle brightness shimmer. Used for shots the
    video model keeps hallucinating in (Ep2 2.2-C: figures formed from a constellation). Nothing new can appear."""
    p = task["params"]; s = p["shot"]; L = float(s.get("dur_s", 4)); n = int(round(L * FPS))
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); kf = get(p["kf"]["s3"], d); out = d / "still.mp4"
        sh("ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", kf, "-vf",
           f"scale={WD * 2}:{HT * 2},zoompan=z='1+0.07*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={WD}x{HT}:fps={FPS},"
           f"eq=brightness='0.025*sin(2*PI*t/2.6)':eval=frame,format=yuv420p", "-frames:v", n, "-c:v", "libx264", "-crf", "18", out)
        return [{"s3_key": put(out, task, ".mp4"), "kind": "video", "meta": {"animate": "still", "duration": L}, "scores": {"rank": 1}}]


CPU_HANDLERS = {"clip": clip_task, "episode": episode_task, "still": still_task}
