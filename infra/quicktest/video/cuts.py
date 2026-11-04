"""Find visual jumps: per-frame mean abs difference on a small grey copy; a jump is a frame whose difference is far above
its local neighbourhood (so slow motion and steady dissolves don't count). usage: cuts.py video.mp4 [--json]"""
import json, subprocess, sys
import numpy as np

def frames(path, w=72, h=128):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)

def fps(path):
    r = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path]).decode().strip()
    a, b = r.split("/"); return float(a) / float(b)

def jumps(path, k=4.0, floor=6.0):
    f = frames(path); d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)); r = fps(path); out = []
    for i in range(len(d)):
        nb = np.concatenate([d[max(0, i - 8):i], d[i + 1:i + 9]])
        base = np.median(nb) if len(nb) else 0
        if d[i] > floor and d[i] > k * max(base, 1.0):
            out.append({"t": round((i + 1) / r, 2), "diff": round(float(d[i]), 1), "local": round(float(base), 1)})
    return out, d, r

if __name__ == "__main__":
    j, d, r = jumps(sys.argv[1])
    print(json.dumps(j) if "--json" in sys.argv else "\n".join(f"{x['t']:7.2f}s  diff {x['diff']:5.1f}  (local {x['local']})" for x in j) or "no jumps")
