"""Episode-level consistency test on the FINAL stitched video (CPU is fine).

  characters : every 0.5 s, find Tara / Dadi (room clips) or the deity on screen (1.3/1.4) with OWLv2, embed the crop with
               DINOv2, cosine vs the same crop from the locked reference sheet. Reported per clip: mean / min / drift.
  set        : frames where both Tara and Dadi are found: whole-frame DINOv2 vs the locked living-room plate.
  voices     : WavLM speaker-verification embedding of every line vs the character's locked reference voice.
  joins      : every hard visual cut (classified by where it falls) + the largest frame jump inside each transition.
  sync       : 1.4 element-formed time vs the time Dadi says the element's name.

usage: python ep_consistency.py <episode.mp4> <episode.json> <timing_1.4.json> <out.json>
Reference paths are set in REFS below (repo refs + chosen deity sheets)."""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf, torch
from PIL import Image
from transformers import (AutoFeatureExtractor, AutoImageProcessor, AutoModel, Owlv2ForObjectDetection, Owlv2Processor,
                          WavLMForXVector)

HERE = Path(__file__).parent; REPO = Path("/home/user/video-rea/stories/srishti-ep1/refs")
SCR = HERE.parent
EP, EPJ, T14, OUT = (Path(a) for a in sys.argv[1:5])
REFS = {"tara": REPO / "tara_sheet.png", "dadi": REPO / "dadi_sheet.png", "brahma": SCR / "deity/brahma_v2_00001_.png",
        "vishnu": SCR / "deity/vishnu_v1_00001_.png", "shiva": SCR / "deity/shiva_v1_00001_.png"}
QUERY = {"tara": "the face of a little girl with braids", "dadi": "the face of an old grandmother with glasses and grey hair",
         "brahma": "a bearded god with four heads", "vishnu": "a blue-skinned god wearing a golden crown",
         "shiva": "a blue-skinned god with a snake around his neck and a trident"}
SB = json.load(open(HERE / "storyboard.json"))
torch.set_grad_enabled(False)
op = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
om = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval()
dp = AutoImageProcessor.from_pretrained("facebook/dinov2-base"); dm = AutoModel.from_pretrained("facebook/dinov2-base").eval()


def find(img, who, thr=0.15):
    out = om(**op(text=[[QUERY[who]]], images=img, return_tensors="pt"))
    s = max(img.size)
    r = op.image_processor.post_process_object_detection(out, threshold=thr, target_sizes=torch.tensor([[s, s]]))[0]
    if len(r["scores"]) == 0:
        return None, 0.0
    i = int(r["scores"].argmax()); x0, y0, x1, y1 = [float(v) for v in r["boxes"][i]]
    pad = 0.15 * max(x1 - x0, y1 - y0)
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad))), float(r["scores"][i])


def emb(img):
    e = dm(**dp(images=img.convert("RGB"), return_tensors="pt")).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(e, dim=-1)[0]


def frame(t, tmp):
    f = tmp / "f.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(EP), "-frames:v", "1", "-vf", "scale=540:960", str(f)], check=True)
    return Image.open(f).convert("RGB")


def who_on_screen(clip, lt):
    if clip in ("1.1", "1.5"):
        return ["tara", "dadi"]
    if clip == "1.4":
        return ["brahma"]
    if clip == "1.3":                                   # name cuts (from rebuild34 timeline): D brahma, E vishnu, F shiva
        return ["brahma"] if 8.85 <= lt < 11.71 else ["vishnu"] if 11.71 <= lt < 14.7 else ["shiva"] if lt >= 14.7 else []
    return []


def visual():
    E = json.load(open(EPJ)); tmp = Path(tempfile.mkdtemp())
    ref = {}
    for k, p in REFS.items():
        c, sc = find(Image.open(p).convert("RGB"), k); ref[k] = emb(c if c is not None else Image.open(p)); print("ref", k, round(sc, 2), flush=True)
    plate = emb(Image.open(REPO / "living_room_plate.png"))
    rows = []
    for si, s in enumerate(E["segments"]):
        if s["clip"] == "1.5" and si == len(E["segments"]) - 1:
            continue                                     # end card
        nxt = E["segments"][si + 1]["start"] if si + 1 < len(E["segments"]) else E["total"]
        t = s["start"] + (0.6 if si else 0.2)
        while t < nxt - 0.3:
            lt = s["a"] + (t - s["start"]); img = frame(t, tmp); r = {"t": round(t, 2), "clip": s["clip"], "lt": round(lt, 2)}
            found = []
            for w in who_on_screen(s["clip"], lt):
                c, det = find(img, w, 0.2 if w in ("tara", "dadi") else 0.1)
                if c is not None:
                    r[w] = round(float(emb(c) @ ref[w]), 3); found.append(w)
            if "tara" in found and "dadi" in found:
                r["set"] = round(float(emb(img) @ plate), 3)
            rows.append(r); t += 0.5
        print("scored", s["clip"], flush=True)
    summ = {}
    for clip in ("1.1", "1.3", "1.4", "1.5"):
        for w in REFS:
            v = [r[w] for r in rows if r["clip"] == clip and w in r]
            if v:
                half = len(v) // 2
                summ.setdefault(clip, {})[w] = dict(n=len(v), mean=round(float(np.mean(v)), 3), min=round(float(np.min(v)), 3),
                                                   first_half=round(float(np.mean(v[:max(1, half)])), 3), second_half=round(float(np.mean(v[half:])), 3))
        sv = [r["set"] for r in rows if r["clip"] == clip and "set" in r]
        if sv:
            summ.setdefault(clip, {})["set"] = dict(n=len(sv), mean=round(float(np.mean(sv)), 3), min=round(float(np.min(sv)), 3))
    return summ, rows


def voices():
    fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv"); vm = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv").eval()

    def ve(path):
        a, sr = sf.read(str(path), dtype="float32"); a = a.mean(1) if a.ndim > 1 else a
        if sr != 16000:
            a = np.interp(np.arange(0, len(a), sr / 16000), np.arange(len(a)), a).astype(np.float32)
        e = vm(**fe(a, sampling_rate=16000, return_tensors="pt")).embeddings
        return torch.nn.functional.normalize(e, dim=-1)[0]
    ref = {"tara": ve(REPO / "voice_tara.wav"), "dadi": ve(REPO / "voice_dadi.wav")}
    files = {"1.1-L1": "1.1-L1_f5_t3.wav", "1.1-L2": "1.1-L2_f5_t2.wav", "1.2-L1": "1.2-L1_f5_t1.wav", "1.3-L1": "1.3-L1_f5_t1.wav",
             "1.5-L1": "1.5-L1_f5_t1.wav", "1.5-L2": "1.5-L2_f5_t2.wav"}
    spk = {l["id"]: l["speaker"] for c in SB["clips"] for l in c.get("lines", [])}
    out = {lid: dict(speaker=spk[lid], sim=round(float(ve(HERE / "voices" / f) @ ref[spk[lid]]), 3)) for lid, f in files.items()}
    out["1.4-L1 (re-voiced phrases)"] = dict(speaker="dadi", sim=round(float(ve(SCR / "ep/build/vo_mix_14.wav") @ ref["dadi"]), 3))
    return out


def joins():
    sys.path.insert(0, str(SCR / "ep")); import cuts
    E = json.load(open(EPJ)); j, d, fps = cuts.jumps(str(EP))
    hard = [x for x in j if x["diff"] > 30]
    seg_at = lambda t: max((s for s in E["segments"] if s["start"] <= t), key=lambda s: s["start"])
    for x in hard:
        s = seg_at(x["t"]); x["clip"] = s["clip"]; x["clip_t"] = round(s["a"] + x["t"] - s["start"], 2)
    tr = []
    for J in E["joins"]:
        a, b = int(J["at"] * fps), int((J["at"] + J["dur"]) * fps)
        tr.append(dict(J, max_frame_jump=round(float(d[max(0, a - 3):b + 3].max()), 1)))
    return hard, tr


def sync():
    T = json.load(open(T14)); words = list(T["onsets"])
    return [dict(element=w, word_starts=round(T["onsets"][w], 2), element_formed=round(T["done"][i], 2),
                 formed_minus_word=round(T["done"][i] - T["onsets"][w], 2)) for i, w in enumerate(words)]


if __name__ == "__main__":
    R = {}
    R["sync_1.4"] = sync(); R["hard_cuts"], R["transitions"] = joins(); print("joins done", flush=True)
    R["voices"] = voices(); print("voices", R["voices"], flush=True)
    R["visual"], rows = visual()
    json.dump(R, open(OUT, "w"), indent=2, ensure_ascii=False); json.dump(rows, open(OUT.with_name(OUT.stem + "_frames.json"), "w"), indent=1)
    print(json.dumps(R, indent=1, ensure_ascii=False))
