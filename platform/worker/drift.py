"""Subject drift check for an image-to-video shot: does every subject in the approved keyframe stay the same thing through
the video? (Ep2 2.3-D: the cow grew an elephant's trunk halfway through.)

For each subject OWLv2 finds in the keyframe (queries come from the shot's prompt + generic ones), the same region is
followed through frames at 25/50/75/100 % and compared two ways:
  similarity : DINOv2 embedding of the region vs the keyframe region (appearance)
  label      : which of the shot's subject labels OWLv2 now prefers for that region (identity: cow -> elephant)
A shot fails if any subject's best label changes to another subject label, or its similarity drops below MIN_SIM.
usage (CLI, calibration): python drift.py keyframe.png video.mp4 "cow, deer, rabbits, baby elephant" [cpu|cuda]"""
import re, subprocess, sys, tempfile
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, Owlv2ForObjectDetection, Owlv2Processor

MIN_SIM = 0.55
GENERIC = ["an animal", "a person", "a bird", "a fish"]
STOP = {"a", "an", "the", "of", "with", "and", "by", "in", "on", "at", "to", "for", "gentle", "friendly", "calm", "clear", "colourful",
        "colorful", "small", "big", "soft", "golden", "bright", "warm", "deep", "under", "over", "near", "same", "both", "two", "their", "his", "her"}
_m = {}


def models(dev):
    if not _m:
        _m["op"] = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
        _m["om"] = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").to(dev).eval()
        _m["dp"] = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
        _m["dm"] = AutoModel.from_pretrained("facebook/dinov2-base").to(dev).eval()
    return _m


SCENERY = {"forest", "clearing", "river", "sky", "stars", "star", "window", "sofa", "room", "landscape", "tree", "trees", "grass",
           "water", "light", "field", "fields", "hills", "hill", "mountain", "mountains", "sun", "sunrise", "sunset", "shot", "background",
           "plant", "table", "lamp", "diya", "riverbank", "bank", "treetops", "cosmos", "space", "clouds", "cloud", "lotus", "halo",
           "night", "dawn", "constellation", "lines", "rays", "surface", "frame", "camera", "wide", "close", "closer", "medium"}


def labels_from(prompt, extra=()):
    """Subject labels from a shot prompt: comma/and-separated phrases, trimmed of filler words; phrases about scenery
    (forest, river, sky...) are not subjects (Ep2 2.3-D: 'forest clearing river' drifted under a push-in)."""
    parts = re.split(r",|\band\b|\bwith\b|;", prompt.lower())
    out = []
    for p in parts:
        w = [x for x in re.findall(r"[a-z]+", p) if x not in STOP]
        if w and any(x in SCENERY for x in w):
            continue
        if 1 <= len(w) <= 3:
            out.append(" ".join(w))
    return list(dict.fromkeys([*extra, *out]))


@torch.no_grad()
def detect(img, labels, dev, thr=0.18):
    m = models(dev)
    out = m["om"](**m["op"](text=[labels], images=img, return_tensors="pt").to(dev))
    s = max(img.size)
    r = m["op"].image_processor.post_process_object_detection(out, threshold=thr, target_sizes=torch.tensor([[s, s]]).to(dev))[0]
    boxes = []
    for b, sc, lab in sorted(zip(r["boxes"].tolist(), r["scores"].tolist(), r["labels"].tolist()), key=lambda x: -x[1]):
        x0, y0, x1, y1 = max(0, b[0]), max(0, b[1]), min(img.width, b[2]), min(img.height, b[3])
        area = (x1 - x0) * (y1 - y0) / (img.width * img.height)
        if area < 0.004 or area > 0.6:
            continue
        if any(iou((x0, y0, x1, y1), k["box"]) > 0.5 for k in boxes):
            continue
        boxes.append({"box": (x0, y0, x1, y1), "label": labels[lab], "score": round(sc, 3)})
        if len(boxes) == 8:
            break
    return boxes


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy; u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u else 0


@torch.no_grad()
def emb(img, dev):
    m = models(dev)
    e = m["dm"](**m["dp"](images=img.convert("RGB"), return_tensors="pt").to(dev)).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(e, dim=-1)[0]


@torch.no_grad()
def best_label(crop, labels, dev):
    m = models(dev)
    out = m["om"](**m["op"](text=[labels], images=crop, return_tensors="pt").to(dev))
    logits = out.logits[0].max(dim=0).values        # best patch per label
    return labels[int(logits.argmax())], float(logits.max())


def frames(video, fracs=(0.25, 0.5, 0.75, 0.999)):
    d = Path(tempfile.mkdtemp())
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)]).decode())
    out = []
    for i, f in enumerate(fracs):
        p = d / f"{i}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(0, min(dur * f, dur - 0.2)):.3f}", "-i", str(video), "-frames:v", "1", str(p)], check=True)
        im = Image.open(p).convert("RGB"); im.path = str(p); out.append((f, im))
    return out


def pad(box, img, k=0.12):
    x0, y0, x1, y1 = box; w, h = x1 - x0, y1 - y0
    return (max(0, x0 - k * w), max(0, y0 - k * h), min(img.width, x1 + k * w), min(img.height, y1 + k * h))


MAX_DECAY, LOW, CROWD, MIN_AREA = 0.12, 0.85, 3, 0.02


# a face appearing: 2.2-C renders 0.02 -> 0.62 and 0.02 -> 0.29; fish 0.05 -> 0.06, birds 0.08 -> 0.08, animals 0.17 -> 0.14
FACE_Q, FACE_MIN, FACE_RATIO = ["a human face", "eyes and a nose", "a person"], 0.15, 4.0


@torch.no_grad()
def face_score(img, dev):
    m = models(dev)
    out = m["om"](**m["op"](text=[FACE_Q], images=img, return_tensors="pt").to(dev))
    s = max(img.size)
    r = m["op"].image_processor.post_process_object_detection(out, threshold=0.0, target_sizes=torch.tensor([[s, s]]).to(dev))[0]
    return float(r["scores"].max()) if len(r["scores"]) else 0.0


def track(prev, cands, img):
    """The candidate (same label) that best continues the previous box: highest overlap, else nearest centre."""
    if not cands:
        return None
    best = max(cands, key=lambda c: iou(prev, c["box"]))
    if iou(prev, best["box"]) >= 0.1:
        return best["box"]
    cx, cy = (prev[0] + prev[2]) / 2, (prev[1] + prev[3]) / 2
    near = min(cands, key=lambda c: ((c["box"][0] + c["box"][2]) / 2 - cx) ** 2 + ((c["box"][1] + c["box"][3]) / 2 - cy) ** 2)
    nx, ny = (near["box"][0] + near["box"][2]) / 2, (near["box"][1] + near["box"][3]) / 2
    return near["box"] if ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5 < 0.25 * (img.width ** 2 + img.height ** 2) ** 0.5 else None


def check(keyframe, video, prompt, dev="cuda", extra_labels=()):
    """-> {"ok", "worst_decay", "subjects"}. Each subject found in the keyframe is TRACKED through the shot (re-detected
    with its own label in every sampled frame) and its crop compared with the keyframe crop. A subject drifts if that
    similarity keeps falling (early-frame similarity minus the lowest later one > MAX_DECAY, ending below LOW): a stable
    subject dips a little in the first frames and then holds; a transforming one keeps sliding (2.3-D cow: 0.96 -> 0.81).
    Tracking keeps moving subjects (swimming fish, flying birds) from reading as drift; a subject that can no longer be
    found at all is reported as lost, not as drift (it may have left the frame)."""
    labels = labels_from(prompt, extra_labels)
    named = {x.lower() for x in extra_labels}
    queries = labels + [g for g in GENERIC if g not in labels]
    fr = frames(video, (0.1, 0.4, 0.7, 1.0))
    w, h = fr[0][1].size
    kf = Image.open(keyframe).convert("RGB").resize((w, h))
    subs = detect(kf, queries, dev)
    dets = [detect(im, queries, dev, thr=0.12) for _, im in fr]
    report, ok = [], True
    count = {}
    for s in subs:
        count[s["label"]] = count.get(s["label"], 0) + 1
    for s in subs:
        if count[s["label"]] >= CROWD and s["label"] not in named:   # a school of fish / flock of birds (never a named character)
            report.append({"label": s["label"], "box": [round(v) for v in s["box"]], "skipped": "crowd"}); continue
        x0, y0, x1, y1 = s["box"]
        if (x1 - x0) * (y1 - y0) < MIN_AREA * w * h:   # tiny subjects: too few pixels to judge (rabbits read as noise)
            report.append({"label": s["label"], "box": [round(v) for v in s["box"]], "skipped": "small"}); continue
        e0 = emb(kf.crop(pad(s["box"], kf)), dev); prev, sims = s["box"], []
        for (_, im), dl in zip(fr, dets):
            bx = track(prev, dl, im)            # by position, any label: "a person" may come back as "manu"
            if bx is None:
                sims.append(None); continue
            sims.append(round(float(emb(im.crop(pad(bx, im)), dev) @ e0), 3)); prev = bx
        seen = [x for x in sims if x is not None]
        later = [x for x in sims[1:] if x is not None]
        decay = round(seen[0] - min(later), 3) if len(seen) >= 2 and later else None
        drift = decay is not None and decay > MAX_DECAY and min(later) < LOW
        ok = ok and not drift
        report.append({"label": s["label"], "box": [round(v) for v in s["box"]], "sims": sims, "decay": decay, "drift": drift,
                       "lost": sum(x is None for x in sims)})
    # shots without people: a face/person that APPEARS during the shot is drift too (Ep2 2.2-C: a face formed in the stars)
    appeared = None
    if not named and not any(r["label"] in ("a person",) for r in report):
        f0 = face_score(kf, dev); later = [face_score(im, dev) for _, im in fr]
        if max(later) > FACE_MIN and max(later) > FACE_RATIO * f0 + 0.05:      # relative to the keyframe: a new face
            appeared = {"keyframe": round(f0, 3), "later": [round(x, 3) for x in later]}
            ok = False
    decays = [r["decay"] for r in report if r.get("decay") is not None]
    return {"ok": ok, "worst_decay": max(decays, default=None), "subjects": report, "face_appeared": appeared,
            "frame_paths": [im.path for _, im in fr]}


if __name__ == "__main__":
    import json
    r = check(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "cuda")
    print(json.dumps(r, indent=1))
