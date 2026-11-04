"""Stitch the Episode 1 clips into one video with designed joins (CPU only).

Each clip contributes an [in, out] window (dead air at the edges trimmed), and consecutive clips OVERLAP by the
transition length:
  dissolve : plain cross-dissolve (void -> void, outro -> end card)
  flare    : cross-dissolve under a warm golden light bloom that peaks mid-transition (divine-light joins)
Audio is not crossfaded: every clip's own track is placed at its timeline offset and mixed, so a word that starts
inside a transition is never faded out; only trimmed edges get a short fade. Final loudness -14 LUFS.

usage: python episode.py <clips_dir> <out.mp4>   (reads clip_1.1.mp4 ... clip_1.5.mp4 from clips_dir)"""
import json, subprocess, sys
from pathlib import Path

D = Path(sys.argv[1]); OUT = Path(sys.argv[2])
# (clip, in, out, transition INTO this segment, transition length)  - times in the clip's own seconds
PLAN = [
    ("1.1", 0.0, 19.3, None, 0),
    ("1.2", 1.5, 17.6, "dissolve", 1.0),   # void -> void; skip 1.5 s of extra darkness; end on the burst (not the shrink)
    ("1.3", 0.0, None, "flare", 1.0),      # the burst blooms into the Om over the field
    ("1.4", 0.0, None, "flare", 0.8),      # Shiva's gold halo -> Brahma's gold halo
    ("1.5", 1.0, 22.5, "flare", 1.2),      # storyboard: golden light flare dissolve from 1.4-F; shorter silent outro
    ("1.5", 25.9, None, "dissolve", 1.0),  # end card
]
GOLD = "0xFFD27A"


def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode())


def main():
    segs, t, offs = [], 0.0, []
    for k, (cid, a, b, tr, d) in enumerate(PLAN):
        f = D / f"clip_{cid}.mp4"; b = b if b is not None else dur(f); L = b - a
        start = t - d if k else 0.0
        segs.append(dict(f=f, a=a, L=L, tr=tr, d=d, start=start)); t = start + L
    total = t
    inputs, fc = [], []
    for k, s in enumerate(segs):
        inputs += ["-ss", f"{s['a']:.3f}", "-t", f"{s['L']:.3f}", "-i", str(s["f"])]
        fc.append(f"[{k}:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{k}]")
        fi = 0.25 if (s["a"] > 0 and not s["tr"]) else 0.0
        fo = 0.3 if k < len(segs) - 1 else 1.0
        af = f"aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS"
        if s["a"] > 0: af += ",afade=t=in:d=0.25"
        af += f",afade=t=out:st={s['L'] - fo:.3f}:d={fo},adelay={int(s['start'] * 1000)}:all=1"
        fc.append(f"[{k}:a]{af}[a{k}]")
    last, acc = "v0", segs[0]["L"]
    flares = []
    for k in range(1, len(segs)):
        s = segs[k]; off = acc - s["d"]
        fc.append(f"[{last}][v{k}]xfade=transition=fade:duration={s['d']}:offset={off:.3f}[x{k}]")
        last = f"x{k}"; acc = off + s["L"]
        if s["tr"] == "flare":
            flares.append((off, s["d"]))
    for j, (off, d) in enumerate(flares):               # golden bloom: rises to 70 % over the first half, falls in the second
        fc.append(f"color=c={GOLD}:s=1080x1920:r=30:d={d},format=rgba,fade=t=in:st=0:d={d / 2:.3f}:alpha=1,"
                  f"fade=t=out:st={d / 2:.3f}:d={d / 2:.3f}:alpha=1,colorchannelmixer=aa=0.7,setpts=PTS+{off:.3f}/TB[g{j}]")
        fc.append(f"[{last}][g{j}]overlay=0:0:eof_action=pass[f{j}]"); last = f"f{j}"
    fc.append("".join(f"[a{k}]" for k in range(len(segs))) + f"amix=inputs={len(segs)}:normalize=0:duration=longest,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.3f}[a]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", "[a]",
                    "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT)], check=True)
    joins = [dict(into=PLAN[k][0] + ("-endcard" if k == len(PLAN) - 1 else ""), type=s["tr"], at=round(s["start"], 2), dur=s["d"])
             for k, s in enumerate(segs) if k]
    json.dump(dict(total=round(total, 2), segments=[dict(clip=p[0], **{x: round(s[x], 2) for x in ("a", "L", "start")})
                                                  for p, s in zip(PLAN, segs)], joins=joins),
              open(OUT.with_suffix(".json"), "w"), indent=2)
    print(f"wrote {OUT} {dur(OUT):.1f}s", json.dumps(joins))


if __name__ == "__main__":
    main()
