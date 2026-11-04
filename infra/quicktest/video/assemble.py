"""Audio prep + final assembly of clips 1.1 and 1.5 (FFmpeg only).
  prep     : split 1.1-L2 after 'ओम्।' -> 1.1-C (on camera) + 1.1-D (voice-over)
  assemble : normalize every shot to 1080x1920 @30 fps, lay dialogue, burn captions, concat per clip
Real-ESRGAN/RIFE polish is a later pass; this is the consistency test cut."""
import json, re, subprocess, sys, textwrap
from pathlib import Path

J = Path(__file__).parent
W = Path("/mnt/nvme/work3"); STATE = W / "state.json"
SB = json.load(open(J / "storyboard.json"))
FONT = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
LINES = {l["id"]: l for c in SB["clips"] for l in c.get("lines", [])}


def sh(*a):
    subprocess.run([str(x) for x in a], check=True)


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode())


def silences(f, db=-35, d=0.18):
    err = subprocess.run(["ffmpeg", "-i", str(f), "-af", f"silencedetect=n={db}dB:d={d}", "-f", "null", "-"], capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(st, en))


def prep():
    S = json.load(open(STATE)) if STATE.exists() else {}
    src = J / "voices" / "1.1-L2_f5_t2.wav"
    text = LINES["1.1-L2"]["tts"]; cut_ratio = (text.index("ओम्") + len("ओम्।")) / len(text)
    D = dur(src); target = cut_ratio * D
    gaps = [(s, e) for s, e in silences(src) if 0.2 < s < D - 0.5]
    s, e = min(gaps, key=lambda g: abs((g[0] + g[1]) / 2 - target))
    cut = (s + e) / 2
    a, b = W / "1.1-L2_part1.wav", W / "1.1-L2_part2.wav"
    sh("ffmpeg", "-loglevel", "error", "-y", "-i", src, "-t", f"{cut:.3f}", a)
    sh("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{cut:.3f}", "-i", src, b)
    S.setdefault("1.1-C", {})["audio"] = str(a); S.setdefault("1.1-D", {})["vo"] = str(b)
    json.dump(S, open(STATE, "w"), indent=2, ensure_ascii=False)
    print(f"1.1-L2 {D:.2f}s split at {cut:.2f}s (target {target:.2f}s, gaps {gaps})")


def caption_file(text, name):
    p = W / f"cap_{name}.txt"
    p.write_text("\n".join(textwrap.wrap(text, 34)))
    return p


def seg(sid, video, out, length=None, audio=None, caption=None, freeze_to=None, fade_out=0, fade_in=0):
    """One normalized segment: video (or color) + optional audio + optional caption + optional fades to/from black."""
    vf = "scale=1080:1920:flags=lanczos,fps=30,format=yuv420p"
    if freeze_to:
        vf += f",tpad=stop_mode=clone:stop_duration={freeze_to}"
    if fade_out:
        vf += f",fade=t=out:st={length - fade_out:.3f}:d={fade_out}"
    if fade_in:
        vf += f",fade=t=in:st=0:d={fade_in}"
    if caption:
        vf += (f",drawtext=fontfile={FONT}:textfile={caption}:fontsize=46:fontcolor=white:line_spacing=10:"
               f"box=1:boxcolor=black@0.45:boxborderw=18:x=(w-text_w)/2:y=h-text_h-220")
    args = ["ffmpeg", "-loglevel", "error", "-y", "-i", video]
    if audio:
        args += ["-i", audio, "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad[a]", "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"]
    args += ["-t", f"{length:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-ar", "48000", "-ac", "2", out]
    sh(*args)
    return out


def assemble():
    S = json.load(open(STATE))
    segs = {"1.1": [], "1.5": []}
    for c in SB["clips"]:
        if c["id"] not in segs:
            continue
        for s in c["shots"]:
            sid, x, o = s["id"], S.get(s["id"], {}), W / f"seg_{s['id']}.mp4"
            if s["tech"] == "TALK":
                ln = LINES[s["line"]]; a = x.get("audio") or x.get("audio_used")
                L = dur(a) + 0.35
                cap = ln["caption"].split("'Om'.")[0] + "'Om'." if sid == "1.1-C" else ln["caption"]  # 1.1-C: on camera until Om
                segs[c["id"]].append(seg(sid, x["video"], o, L, a, caption_file(cap, sid), freeze_to=1))
            elif s.get("module") == "void":
                v = W / "void.mp4"; sh("bash", J / "void.sh", v, s["dur_s"])
                segs[c["id"]].append(seg(sid, v, o, s["dur_s"], fade_in=0.6))  # soft arrival from the paper push-in
            elif x.get("video"):
                L = s.get("dur_s", 3); a = x.get("vo"); cap = None
                if a:
                    L = max(L, dur(a) + 0.3)
                    cap = caption_file(LINES["1.1-L2"]["caption"].split("'Om'.")[1].strip(), sid)
                vlen = dur(x["video"])
                fo = 1.0 if sid == "1.1-D" else 0  # push-in into the paper dissolves to black, then the void
                segs[c["id"]].append(seg(sid, x["video"], o, L, a, cap, freeze_to=max(0, L - vlen) + 0.1, fade_out=fo))
            else:
                print("skip (no video):", sid)
        if c["id"] == "1.5":  # end card
            ec = W / "seg_endcard.mp4"
            sh("ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x0b0814:s=1080x1920:r=30:d=2",
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", f"drawtext=fontfile={FONT}:text='Srishti · Episode 1':fontsize=72:fontcolor=0xf6c453:x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p",
               "-t", "2", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-ar", "48000", "-ac", "2", ec)
            segs["1.5"].append(ec)
    for cid, ss in segs.items():
        lst = W / f"list_{cid}.txt"; lst.write_text("".join(f"file '{p}'\n" for p in ss))
        out = Path("/mnt/nvme/ComfyUI/output/srishti") / f"clip_{cid}.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
        sh("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", out)
        print("wrote", out, f"{dur(out):.1f}s")


if __name__ == "__main__":
    {"prep": prep, "assemble": assemble}[sys.argv[1]]()
