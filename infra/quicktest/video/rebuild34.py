"""Re-cut clips 1.3 and 1.4 from the rendered shots, CPU only (no new generation).

Why: chained first/last-frame (FLF) shots were TRIMMED to their slots. Each render is ~0.15 s longer than its slot, so
the trim dropped the frames where the shot reaches its end keyframe, while the next shot starts exactly on that
keyframe -> a visible jump at every seam. And in 1.4 the slots came from a fixed 3.4 s grid, so each element finished
forming at the grid time rather than when Dadi names it (earth finished ~5 s after "धरती").

Now: every chained shot is RETIMED (all frames kept, played slightly faster/slower) to fit its slot, the duplicate
first frame of each chained shot is dropped, and in 1.4 the slots are derived from the voice: each element finishes
forming 0.2 s after its word starts. After earth forms, the last frame holds with a slow push-in under the closing line.
Outputs have no baked fade-in/out; the episode assembler does the transitions between clips.

usage: python rebuild34.py <src_dir> <out_dir> [1.3] [1.4]
  src_dir layout: out_s3/, out_s4/ (ComfyUI shot renders), work3_s3/, work3_s4/ (labels, VO, parts)"""
import json, subprocess, sys, types
from pathlib import Path

sys.modules.setdefault("comfy", types.ModuleType("comfy"))         # s34 imports comfy; not needed for assembly
sys.path.insert(0, str(Path(__file__).parent))
import s34

SRC, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(); OUT.mkdir(parents=True, exist_ok=True)
FPS_IN = 16


def nframes(v):
    return int(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v", "-count_frames", "-show_entries",
                                        "stream=nb_read_frames", "-of", "csv=p=0", str(v)]).decode().strip())


def retime(src, out, L, drop_first=False):
    """Fit ALL frames of a 16 fps shot into exactly L seconds (speed change, not trim)."""
    n = nframes(src) - (1 if drop_first else 0); f = L / (n / FPS_IN)
    vf = (("trim=start_frame=1," if drop_first else "") + f"setpts=(PTS-STARTPTS)*{f:.5f},fps={s34.FPS},"
          f"scale={s34.WD}:{s34.HT}:flags=lanczos,tpad=stop_mode=clone:stop_duration=0.5,format=yuv420p")
    s34.sh("ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-t", f"{L:.3f}", "-an", "-c:v", "libx264", "-crf", "16", out)
    print(f"  {Path(src).name}: {n} frames -> {L:.2f}s (speed x{1 / f:.2f})", flush=True)
    return out


def hold(src_video, out, L, zoom=0.05):
    """Hold the last frame with a slow push-in (keeps the picture alive while the closing line plays)."""
    last = OUT / "hold_src.png"; s34.last_frame(src_video, last, s34.WD, s34.HT)
    n = int(round(L * s34.FPS))
    s34.sh("ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", last, "-vf",
           f"scale={s34.WD * 2}:{s34.HT * 2},zoompan=z='1+{zoom}*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:"
           f"s={s34.WD}x{s34.HT}:fps={s34.FPS},format=yuv420p", "-frames:v", n, "-c:v", "libx264", "-crf", "16", out)
    return out


def mix_vo(chunk_dir, starts, total, out, sr=24000):
    import numpy as np, wave
    mix = np.zeros(int(sr * (total + 1)), dtype=np.float32)
    for i, s0 in starts.items():
        with wave.open(str(chunk_dir / f"c{i}.wav")) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16 if w.getsampwidth() == 2 else np.int32).astype(np.float32)
            x /= 32768.0 if w.getsampwidth() == 2 else 2 ** 31
        k = int(s0 * sr); mix[k:k + len(x)] += x[: len(mix) - k]
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    return out


# element shot lengths on screen: the four short morphs play at ~1.17x, the earth finale (7 s render) at ~1.46x
ELEM_LEN = [3.0, 3.0, 3.0, 3.0, 4.8]


def clip14():
    W, R = SRC / "work3_s4", SRC / "out_s4"; C = s34.clip("1.4"); LINE = C["lines"][0]; SH = {s["id"]: s for s in C["shots"]}
    ch = json.load(open(W / "vo" / "chunks.json")); L = [c["sec"] for c in ch]
    words = ["आकाश", "हवा", "आग", "पानी", "धरती"]
    off = []                                                    # where the element word starts inside its phrase
    for i, w in enumerate(words):
        wt, _ = s34.word_times(ch[i + 1]["text"], W / "vo" / f"c{i + 1}.wav", [w]); off.append(wt[w])
    # layout driven by the pictures: element i is fully formed at done[i]; its name starts 0.2 s before that
    A_LEN = 3.6                                                 # Brahma raising his palm, near natural speed (render 4.06 s)
    first_word = max(0.6 + L[0] + 0.45, A_LEN + ELEM_LEN[0] - 0.2)  # intro phrase, a breath, then "आकाश"
    done = [first_word + 0.2]
    for d in ELEM_LEN[1:]:
        done.append(done[-1] + d)
    start = {0: 0.6}
    for i in range(5):
        start[i + 1] = done[i] - 0.2 - off[i]
    start[6] = max(start[5] + L[5] + 0.5, done[4] + 0.4)
    total = start[6] + L[6] + 1.4
    a_end = done[0] - ELEM_LEN[0]
    onset = {w: start[i + 1] + off[i] for i, w in enumerate(words)}
    vo = mix_vo(W / "vo", start, total, OUT / "vo_mix_14.wav")
    print("1.4 layout: A 0-%.2f" % a_end, "done", [round(x, 2) for x in done], "phrases", {k: round(v, 2) for k, v in start.items()},
          "total", round(total, 2), flush=True)
    parts = [retime(R / "A_00001.mp4", OUT / "14_A.mp4", a_end)]
    seams = [a_end] + done
    for i, sid in enumerate(["1.4-B", "1.4-C", "1.4-D", "1.4-E", "1.4-F"]):
        parts.append(retime(R / f"{sid}_00001.mp4", OUT / f"14_{sid}.mp4", seams[i + 1] - seams[i], drop_first=True))
    parts.append(hold(R / "1.4-F_00001.mp4", OUT / "14_hold.mp4", total - done[-1]))
    labels = []
    for i, w in enumerate(words):
        nxt = done[i + 1] if i < 4 else total
        sk = SH[f"1.4-{'BCDEF'[i]}"]["overlay"]["text"]          # storyboard's Sanskrit name (वायु, अग्नि, ...)
        lab = s34.label2_png(w, sk, OUT / f"label2_1.4-{'BCDEF'[i]}.png")  # big = the word Dadi says
        labels.append((lab, onset[w] - 0.1, min(nxt - 0.1, onset[w] + 2.0)))
    s34.finish(parts, labels, vo, 0.0, LINE["caption"], OUT / "clip_1.4.mp4", OUT,
               cap_span=(0.6, total - 0.4), cap_starts=[0.6, start[1] - 0.2, start[6] - 0.2])
    json.dump({"onsets": onset, "done": done, "a_end": a_end, "total": total, "phrase_starts": start},
              open(OUT / "timing_1.4.json", "w"), ensure_ascii=False, indent=2)


def clip13():
    W, R = SRC / "work3_s3", SRC / "out_s3"; C = s34.clip("1.3"); LINE = C["lines"][0]
    VO = Path(__file__).parent / "voices" / "1.3-L1_f5_t1.wav"
    words, vo_len = s34.word_times(LINE["tts"], VO, ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    vo_start = max(1.0, 9.0 - words["अ से ब्रह्मा"])
    tD, tE, tF = (vo_start + words[w] - 0.15 for w in ["अ से ब्रह्मा", "उ से विष्णु", "म से शिव"])
    end = vo_start + vo_len + 0.8
    la, lb = tD * 4 / 15, tD * 5 / 15; lc = tD - la - lb
    # A is the composited Om (already 30 fps, exact length); B and C are a chained FLF pair -> retime, keep every frame
    a = OUT / "13_A.mp4"
    s34.sh("ffmpeg", "-loglevel", "error", "-y", "-i", W / "1.3-A.mp4", "-vf", f"scale={s34.WD}:{s34.HT},fps={s34.FPS},format=yuv420p",
           "-t", f"{la:.3f}", "-an", "-c:v", "libx264", "-crf", "16", a)
    parts = [a, retime(R / "B_00002.mp4", OUT / "13_B.mp4", lb, drop_first=True),
             retime(R / "C_00001.mp4", OUT / "13_C.mp4", lc, drop_first=True)]
    seg = {"1.3-D": (tD, tE), "1.3-E": (tE, tF), "1.3-F": (tF, end)}
    for sid, (x, y) in seg.items():                            # hard cuts on the names: keep the trim (no chaining)
        parts.append(s34.norm(R / f"{sid}_00001.mp4", OUT / f"13_{sid}.mp4", y - x))
    labels = [(W / f"label_{sid}.png", x + 0.25, min(y, x + 2.6)) for sid, (x, y) in seg.items()]
    s34.finish(parts, labels, VO, vo_start, LINE["caption"], OUT / "clip_1.3.mp4", OUT)


if __name__ == "__main__":
    for c in sys.argv[3:]:
        {"1.3": clip13, "1.4": clip14}[c]()
