"""Character consistency, measured: find each character's face with OWLv2 (open-vocabulary detector),
embed the crop with DINOv2, compare with the same crop from the locked reference sheet.
  pick    : choose the most on-model keyframe variant per shot
  videos  : score first/middle/last frame of every generated shot (drift inside a shot)
Writes /mnt/nvme/work3/consistency.json. Both models are Apache-2.0 and run on the GPU in seconds."""
import json, subprocess, sys, tempfile
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, Owlv2ForObjectDetection, Owlv2Processor

W = Path("/mnt/nvme/work3"); STATE = W / "state.json"; OUT = W / "consistency.json"
REF = {"tara": "/mnt/nvme/ComfyUI/input/refs/tara_sheet.png", "dadi": "/mnt/nvme/ComfyUI/input/refs/dadi_sheet.png"}
QUERY = {"tara": "the face of a little girl with braids", "dadi": "the face of an old grandmother with glasses and grey hair"}
dev = "cuda"
op = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
om = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").to(dev).eval()
dp = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
dm = AutoModel.from_pretrained("facebook/dinov2-base").to(dev).eval()


@torch.no_grad()
def face(img, who):
    inp = op(text=[[QUERY[who]]], images=img, return_tensors="pt").to(dev)
    out = om(**inp)
    W_, H_ = img.size; s = max(W_, H_)  # OWLv2 pads to square
    r = op.image_processor.post_process_object_detection(out, threshold=0.15, target_sizes=torch.tensor([[s, s]]).to(dev))[0]
    if len(r["scores"]) == 0:
        return None, 0.0
    i = int(r["scores"].argmax()); x0, y0, x1, y1 = [float(v) for v in r["boxes"][i]]
    pad = 0.15 * max(x1 - x0, y1 - y0)
    box = (max(0, x0 - pad), max(0, y0 - pad), min(W_, x1 + pad), min(H_, y1 + pad))
    return img.crop(box), float(r["scores"][i])


@torch.no_grad()
def emb(img):
    e = dm(**dp(images=img, return_tensors="pt").to(dev)).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(e, dim=-1)[0]


REFE = {}
for k, p in REF.items():
    c, sc = face(Image.open(p).convert("RGB"), k)
    REFE[k] = emb(c); print(f"ref {k}: face found (score {sc:.2f})", flush=True)


def score(img, who):
    c, det = face(img, who)
    return (round(float(emb(c) @ REFE[who]), 3), round(det, 2)) if c is not None else (None, 0.0)


def chars(s):
    return [r for r in s.get("kf_refs", []) if "tara" in r or "dadi" in r]


def who_of(path):
    return "tara" if "tara" in path else "dadi"


def frames(video, n=3):
    d = Path(tempfile.mkdtemp())
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]).decode())
    out = []
    for i, t in enumerate([0.05, dur / 2, max(0, dur - 0.15)][:n]):
        f = d / f"{i}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", str(f)], check=True)
        out.append(Image.open(f).convert("RGB"))
    return out


def pick(only=()):
    S = json.load(open(STATE)); R = json.load(open(OUT)) if OUT.exists() else {}
    for sid, s in S.items():
        if not s.get("keyframes") or (only and sid not in only):
            continue
        whos = [who_of(r) for r in chars(s)]
        best, rows = None, []
        for kf in s["keyframes"]:
            img = Image.open(kf).convert("RGB")
            sc = {w: score(img, w) for w in whos}
            sims = [v[0] if v[0] is not None else 0.0 for v in sc.values()]
            m = sum(sims) / len(sims) if sims else 0.0
            scene = None
            if s.get("crop"):  # continuity: the frame must still look like the shot it was cropped from
                scene = round(float(emb(img) @ emb(Image.open(s["crop"]).convert("RGB"))), 3)
                # insert shots (paper, hand) often hide the face: judge them on scene continuity alone
                m = scene if sid in ("1.1-D", "1.5-C") else 0.5 * m + 0.5 * scene
            rows.append({"keyframe": kf, "scores": sc, "scene_sim": scene, "mean": round(m, 3)})
            if best is None or m > best[0]:
                best = (m, kf)
        s["keyframe"] = best[1] if best else s["keyframes"][0]
        R.setdefault(sid, {})["keyframes"] = rows
        print(sid, "->", Path(s["keyframe"]).name, rows, flush=True)
    json.dump(S, open(STATE, "w"), indent=2, ensure_ascii=False); json.dump(R, open(OUT, "w"), indent=2)


def videos():
    S = json.load(open(STATE)); R = json.load(open(OUT)) if OUT.exists() else {}
    for sid, s in S.items():
        if not s.get("video"):
            continue
        whos = [who_of(r) for r in chars(s)]
        fr = frames(s["video"])
        rows = {w: [score(f, w)[0] for f in fr] for w in whos}
        R.setdefault(sid, {})["video_first_mid_last"] = rows
        print(sid, rows, flush=True)
    json.dump(R, open(OUT, "w"), indent=2)


if __name__ == "__main__":
    if sys.argv[1] == "pick":
        pick(tuple(sys.argv[2:]))
    else:
        videos()
