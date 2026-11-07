"""vrea platform GPU worker. Runs on the GPU box next to ComfyUI (started by the autoscaler's user-data).

Two lanes pull tasks from the server over HTTPS:
  gpu   : image / edit / video / talk tasks through ComfyUI, preferring the model family already loaded
  voice : IndicF5 voice takes + ASR/speaker scoring (small models); only runs while the gpu lane is on an image family
          or idle, so the two never compete for VRAM with the 14B video models.
Inputs and outputs live in S3 (s5cmd); the server only exchanges small JSON."""
import glob, json, math, os, random, shutil, subprocess, sys, threading, time, traceback, urllib.request, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import comfy  # noqa: E402

SERVER, TOKEN, RUN = os.environ["SERVER_URL"].rstrip("/"), os.environ["WORKER_TOKEN"], int(os.environ["RUN_ID"])
BUCKET, ROOT = os.environ["BUCKET"], Path(os.environ.get("ROOT", "/mnt/nvme"))
WORK = ROOT / "wtasks"; WORK.mkdir(parents=True, exist_ok=True)
READY = ROOT / "models.ready"
MODELS = json.load(open(HERE / "models.json"))["families"]
REFS_JSON = ROOT / "ComfyUI/output/voice_v2/refs/refs.json"
STATE = {"gpu_family": None, "lock": threading.Lock()}
NEG_IMG = "photorealistic, text, watermark, logo, extra fingers, deformed face"
PEOPLE_NEG = "person, people, man, woman, boy, girl, child, family, face, figure, silhouette"


def api(path, body):
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Worker-Token": TOKEN})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:  # network blips: retry with backoff
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sh(*a, **kw):
    return subprocess.run([str(x) for x in a], check=True, **kw)


def s3get(key, dst):
    dst = Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    sh("s5cmd", "cp", f"s3://{BUCKET}/{key}", dst, stdout=subprocess.DEVNULL); return dst


def s3put(src, task, ext=None):
    ext = ext or Path(src).suffix
    key = f"projects/{task['project_id']}/{task['slot_key'].replace(':', '_')}/r{task['round']}_{uuid.uuid4().hex[:10]}{ext}"
    sh("s5cmd", "cp", src, f"s3://{BUCKET}/{key}", stdout=subprocess.DEVNULL); return key


def ready_families():
    return sorted(p.name for p in READY.iterdir()) if READY.exists() else list(MODELS)


def ensure_family(fam):
    """Copy a model family that the box was not launched with (rare: e.g. a regenerate needs a new family)."""
    if fam not in MODELS or not READY.exists() or (READY / fam).exists():
        return
    lines = [f"cp --concurrency 16 s3://{BUCKET}/models/{x} {ROOT}/ComfyUI/models/{x}" for x in MODELS[fam]["files"]
             if not (ROOT / "ComfyUI/models" / x).exists()]
    if lines:
        f = WORK / f"cp_{fam}.txt"; f.write_text("\n".join(lines) + "\n"); sh("s5cmd", "--numworkers", "32", "run", f)
    (READY / fam).touch()


# ------------------------------------------------------------------ graphs
def g_t2i(prompt, prefix, seed, w=720, h=1280, neg=NEG_IMG, batch=1):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors", "strength_model": 1.0}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4", 0], "shift": 3.1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": neg}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": batch}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
                                                    "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def g_flf(start, end, prompt, prefix, seed, frames, w=480, h=832):
    g = comfy.g_i2v(start, prompt, prefix, seed, frames, w, h)
    g["img2"] = {"class_type": "LoadImage", "inputs": {"image": end}}
    g["i2v"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": {
        "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["img", 0], "end_image": ["img2", 0],
        "width": w, "height": h, "length": frames, "batch_size": 1}}
    return g


def pngs(files):
    return [f for f in files if str(f).endswith(".png")]


# ------------------------------------------------------------------ scoring (DINOv2 vs the reference sheet)
_dino = {}


def sim(a, b):
    try:
        import torch
        from PIL import Image
        from transformers import AutoImageProcessor, AutoModel
        if not _dino:
            _dino["p"] = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
            _dino["m"] = AutoModel.from_pretrained("facebook/dinov2-base").to("cuda").eval()
        with torch.no_grad():
            e = [torch.nn.functional.normalize(_dino["m"](**_dino["p"](images=Image.open(x).convert("RGB"), return_tensors="pt").to("cuda"))
                                               .last_hidden_state[:, 0], dim=-1)[0] for x in (a, b)]
        return round(float(e[0] @ e[1]), 3)
    except Exception as e:
        log("score failed", e); return None


# ------------------------------------------------------------------ task handlers
def h_sheet(t):
    p = t["params"]; d = p["description"] + (f". {p['note']}" if p.get("note") else "")
    if p["type"] == "character":
        prompt = (f"full-body character reference sheet, front view, centred, plain warm cream background, {d}. Style: {p['look']}")
    else:
        prompt = f"establishing wide shot, {d}, no people. Style: {p['look']}"
    out = []
    files, _ = comfy.run(g_t2i(prompt, f"p{t['project_id']}/{p['name']}", 4000 + 97 * t["round"], batch=p.get("variants", 2)))
    for i, f in enumerate(pngs(files)):
        out.append({"s3_key": s3put(f, t), "kind": "image", "meta": {"prompt": prompt, "variant": i + 1}, "scores": {"rank": -i}})
    return out


def keyframe_prompt(p, s):
    note = f" {p['note']}." if p.get("note") else ""
    return s.get("keyframe_prompt", s.get("last_frame_prompt", "")) + "." + note


def h_keyframe(t):
    p = t["params"]; s = p["shot"]; look = p["look"]; d = WORK / f"t{t['id']}"; d.mkdir(exist_ok=True)
    refs = {k: s3get(v, d / f"ref_{k}.png") for k, v in p.get("refs", {}).items()}
    chars = list(p.get("characters", {}))
    base = s3get(p["base"]["s3"], d / "base.png") if p.get("base") else None
    prev = s3get(p["prev"]["s3"], d / "prev.png") if p.get("prev") else None
    cover = s.get("cover") or {}
    out = []
    for v in range(p.get("variants", 2)):
        seed = 5000 + 131 * v + 17 * t["round"]; meta = {"variant": v + 1}
        first = None
        if s["tech"] == "FLF":
            ensure_family("image")
            empty = not chars        # no characters: never the series LOOK (it draws people), and say so explicitly
            if s.get("first_frame_prompt"):
                fp = s["first_frame_prompt"] + (", no people, no text, vertical, soft 3D render" if empty else ". Style: " + look)
                files, _ = comfy.run(g_t2i(fp, f"p{t['project_id']}/{s['id']}_first", seed,
                                           neg=NEG_IMG + (", " + PEOPLE_NEG if empty else ""))); first = pngs(files)[0]
            else:
                first = prev or base
            imgs = [comfy.to_input(first, f"t{t['id']}_first.png")] + [comfy.to_input(refs[c], f"t{t['id']}_{c}.png") for c in chars[:1]]
            prompt = ("Keep EXACTLY this composition, camera, framing and lighting. Change only this: " + keyframe_prompt(p, s)
                      + (f" Image 2 is {chars[0]}'s reference: keep them exactly as in image 2. Style: {look}" if chars
                         else " No people, no figures, no faces anywhere in the frame. Soft 3D render."))
            files, _ = comfy.run(comfy.g_keyframe(prompt, imgs, f"p{t['project_id']}/{s['id']}_last", seed))
            kf = pngs(files)[0]; meta["first"] = s3put(first, t)
        elif base is not None and cover.get("crop") in ("mcu", "object", "two"):
            crop = d / f"crop_{v}.png"
            r = subprocess.run([sys.executable, str(HERE / "reframe.py"), base, cover["crop"],
                                cover.get("subject") or (",".join(chars[:2]) if len(chars) >= 2 else "dadi,tara"), crop],
                               capture_output=True, text=True)
            src = crop if r.returncode == 0 else base
            subj = cover.get("subject")
            imgs = [comfy.to_input(src, f"t{t['id']}_crop{v}.png")]
            if subj in refs:
                imgs.append(comfy.to_input(refs[subj], f"t{t['id']}_{subj}.png"))
            prompt = ("Image 1 is a cropped close shot from this scene. Re-render it as a sharp, detailed, full-resolution vertical 9:16 frame "
                      "with EXACTLY the same framing, pose, setting and lighting as image 1. "
                      + (f"Image 2 is {subj}'s character reference: keep their face, hair and clothing exactly as in image 2. " if subj in refs else "")
                      + keyframe_prompt(p, s) + " Style: " + look)
            files, _ = comfy.run(comfy.g_keyframe(prompt, imgs, f"p{t['project_id']}/{s['id']}", seed)); kf = pngs(files)[0]
            meta["crop_ok"] = r.returncode == 0
        elif base is not None:
            prompt = ("Keep EXACTLY this scene: same room, camera, framing, lighting and the same characters in the same places. "
                      "Change only this: " + keyframe_prompt(p, s) + " Style: " + look)
            files, _ = comfy.run(comfy.g_keyframe(prompt, [comfy.to_input(base, f"t{t['id']}_base.png")], f"p{t['project_id']}/{s['id']}", seed))
            kf = pngs(files)[0]
        elif refs:
            order = chars + [k for k in refs if k not in chars]
            imgs = [comfy.to_input(refs[k], f"t{t['id']}_{k}.png") for k in order[:3]]
            intro = " ".join(f"Image {i + 1} is {k}'s reference." for i, k in enumerate(order[:3]))
            prompt = (intro + " Create one vertical 9:16 frame: " + keyframe_prompt(p, s)
                      + " Keep every character's face, hair and clothing exactly as in their reference. Style: " + look)
            files, _ = comfy.run(comfy.g_keyframe(prompt, imgs, f"p{t['project_id']}/{s['id']}", seed)); kf = pngs(files)[0]
        else:   # no characters: never add the series LOOK (it pulls people into empty plates)
            ensure_family("image")
            prompt = keyframe_prompt(p, s) + ", no people, no text, vertical, soft 3D render"
            files, _ = comfy.run(g_t2i(prompt, f"p{t['project_id']}/{s['id']}", seed,
                                       neg=NEG_IMG + ", " + PEOPLE_NEG))
            kf = pngs(files)[0]
        score = sim(kf, refs[chars[0]]) if chars and chars[0] in refs else None
        meta["prompt"] = prompt
        out.append({"s3_key": s3put(kf, t), "kind": "image", "meta": meta, "scores": {"ref_sim": score, "rank": score or -v}})
    return out


def last_frame(video, out):
    sh("ffmpeg", "-loglevel", "error", "-y", "-sseof", "-0.1", "-i", video, "-frames:v", "1", out); return out


IDENTITY_LOCK = ("Every person and animal keeps exactly its own species, body, face and colours from the first frame to the last; "
                 "nothing turns into anything else; gentle natural motion.")
NEG_DRIFT = ", transforming, shape-shifting, one animal turning into another, merging bodies, extra trunk, extra limbs, extra heads"
DRIFT_TRIES = 3


def judge(t, kf, rep, subjects):
    """Upload the keyframe + the screen's frames and ask the server (Claude vision, if a key is configured)."""
    try:
        keys = [s3put(kf, t, ".png")] + [s3put(f, t, ".png") for f in rep.get("frame_paths", [])[1:]]
        return api("/api/w/judge", {"run_id": RUN, "images": keys, "subjects": sorted(set(subjects))})
    except Exception as e:
        log("judge call failed", e); return {"drift": None, "problem": str(e)[:200]}


def h_video(t):
    """I2V / I2V+COMP / FLF. I2V shots are checked for subject drift (drift.py: a subject that stops looking like itself,
    e.g. Ep2 2.3-D's cow growing a trunk); a drifting render is redone with a new seed, up to DRIFT_TRIES renders, and the
    most consistent one is kept. If every try drifts the shot goes to your review instead of being approved silently."""
    p = t["params"]; s = p["shot"]; d = WORK / f"t{t['id']}"; d.mkdir(exist_ok=True)
    kf = s3get(p["kf"]["s3"], d / "kf.png")
    prompt = s.get("motion_prompt", "") + ". " + IDENTITY_LOCK + " " + p["look"]
    tries = 1 if s["tech"] == "FLF" else DRIFT_TRIES          # a morph is meant to change; nothing to check
    best = None
    for k in range(tries):
        seed = 7000 + 7 * t["round"] + 1009 * k
        if s["tech"] == "FLF":
            if p.get("prev_video"):
                start = last_frame(s3get(p["prev_video"]["s3"], d / "prev.mp4"), d / "start.png")
            else:
                start = s3get(p["kf"]["meta"]["first"], d / "first.png")
            g = g_flf(comfy.to_input(start, f"t{t['id']}_s.png"), comfy.to_input(kf, f"t{t['id']}_e.png"), prompt,
                      f"p{t['project_id']}/{s['id']}", seed, p["frames"])
        else:
            g = comfy.g_i2v(comfy.to_input(kf, f"t{t['id']}_kf.png"), prompt, f"p{t['project_id']}/{s['id']}", seed, p["frames"])
        for n in g.values():                                 # stronger negative for every video graph
            if n.get("class_type") == "CLIPTextEncode" and n["inputs"].get("text") == comfy.NEG_VIDEO:
                n["inputs"]["text"] = comfy.NEG_VIDEO + NEG_DRIFT
        files, sec = comfy.run(g)
        vid = [f for f in files if str(f).endswith(".mp4")][0]
        if tries == 1:
            best = (None, vid, sec, None); break
        try:
            import drift
            rep = drift.check(kf, vid, s.get("keyframe_prompt", ""), "cuda", extra_labels=list(p.get("characters", {})) or [])
        except Exception as e:                               # never fail a shot because the checker failed
            log("drift check failed", e); rep = {"ok": True, "worst_decay": None, "subjects": [], "error": str(e)[:200]}
        if not rep["ok"]:                                    # screen flagged it: ask the server's vision judge
            rep["judge"] = judge(t, kf, rep, [r["label"] for r in rep["subjects"]])
            if rep["judge"].get("drift") is False:
                rep["ok"] = True                             # e.g. a zoom or a gesture, not a transformation
        log(s["id"], "try", k + 1, "drift ok" if rep["ok"] else "DRIFT", rep.get("worst_decay"), rep.get("judge"))
        key = (rep["ok"], -(rep.get("worst_decay") or 0))
        if best is None or key > best[0]:
            best = (key, vid, sec, rep)
        if rep["ok"]:
            break
    _, vid, sec, rep = best
    scores = {"rank": 1}
    meta = {"render_s": sec}
    if rep is not None:
        scores.update({"drift_ok": rep["ok"], "worst_decay": rep.get("worst_decay"), "tries": k + 1})
        meta["drift"] = [{x: r.get(x) for x in ("label", "decay", "skipped", "drift")} for r in rep["subjects"]]
        if rep.get("face_appeared"):
            meta["face_appeared"] = rep["face_appeared"]
        if rep.get("judge"):
            meta["judge"] = rep["judge"]
        if not rep["ok"]:
            scores["needs_review"] = True
    return [{"s3_key": s3put(vid, t), "kind": "video", "meta": meta, "scores": scores}]


def h_talk(t):
    import talk
    p = t["params"]; s = p["shot"]; d = WORK / f"t{t['id']}"; d.mkdir(exist_ok=True)
    kf = s3get(p["kf"]["s3"], d / "kf.png"); wav = s3get(p["audio"]["s3"], d / "line.wav")
    n = math.ceil(talk.audio_seconds(str(wav)) * 25) + 4
    n += (4 - (n - 1) % 4) % 4          # Wan/InfiniteTalk need 4k+1 frames (else an einops shape error), as in talk.run
    g = talk.g_talk(comfy.to_input(kf, f"t{t['id']}_kf.png"), comfy.to_input(wav, f"t{t['id']}_line.wav"),
                    s.get("motion_prompt", "") + ". " + p["look"], f"p{t['project_id']}/{s['id']}", n, seed=900 + t["round"])
    files, sec = comfy.run(g)
    vids = [f for f in files if str(f).endswith(".mp4")]
    vid = next((f for f in vids if "-audio" in str(f)), vids[0])
    return [{"s3_key": s3put(vid, t), "kind": "video", "meta": {"render_s": sec, "has_audio": True}, "scores": {"rank": 1}}]


def voice_env():
    if not (ROOT / "f5/bin/python").exists():
        log("restoring voice environment"); sh("bash", HERE / "voice_env.sh", "restore", cwd=ROOT)
    if not os.environ.get("HF_TOKEN"):
        r = subprocess.run(["aws", "ssm", "get-parameter", "--name", "/vrea/hf_token", "--with-decryption", "--query", "Parameter.Value",
                            "--output", "text"], capture_output=True, text=True)
        if r.returncode == 0:
            os.environ["HF_TOKEN"] = r.stdout.strip()


def h_voice(t):
    p = t["params"]; voice_env(); d = WORK / f"t{t['id']}"; out = d / "takes"; out.mkdir(parents=True, exist_ok=True)
    line = dict(p["line"], speaker=p["speaker"])
    (d / "sb.json").write_text(json.dumps({"clips": [{"lines": [line]}]}, ensure_ascii=False))
    env = dict(os.environ, PYTHONPATH=f"{HERE}/pipeline")
    sh(ROOT / "f5/bin/python", HERE / "f5_lines.py", d / "sb.json", REFS_JSON, out, env=env)
    scores = {}
    r = subprocess.run([str(ROOT / "asr/bin/python"), str(HERE / "voice_score.py"), str(out), "--ref-json", str(REFS_JSON)], env=env)
    if r.returncode == 0 and (out / "voice_scores.json").exists():
        scores = {x["take"]: x for x in json.load(open(out / "voice_scores.json"))}
    res = []
    for f in sorted(out.glob("*.wav")):
        sc = scores.get(f.name, {})
        keep = {k: sc.get(k) for k in ("n_issues", "cer", "spk_sim", "pace_ok", "f0_std_st", "transcript", "issues") if k in sc}
        rank = (-(sc.get("n_issues") or 0) * 10 - (sc.get("cer") or 0) * 10 + (sc.get("spk_sim") or 0)) if sc else 0
        res.append({"s3_key": s3put(f, t), "kind": "audio", "meta": {"take": f.name}, "scores": {**keep, "rank": round(rank, 3)}})
    return res


HANDLERS = {"sheet": h_sheet, "keyframe": h_keyframe, "video": h_video, "talk": h_talk, "voice": h_voice}


def lane(name):
    while True:
        try:
            if name == "voice" and STATE["gpu_family"] in ("video", "talk"):
                time.sleep(10); continue
            t = api("/api/w/claim", {"run_id": RUN, "lane": name, "ready": ready_families(), "last": STATE["gpu_family"]}).get("task")
            if not t:
                if name == "gpu":
                    STATE["gpu_family"] = None
                time.sleep(5); continue
            if name == "gpu":
                STATE["gpu_family"] = t["family"]; ensure_family(t["family"])
            log(name, "task", t["id"], t["type"], t["slot_key"])
            stop = threading.Event()

            def beat():
                while not stop.wait(30):
                    api("/api/w/heartbeat", {"run_id": RUN, "task_id": t["id"]})
            threading.Thread(target=beat, daemon=True).start()
            try:
                out = HANDLERS[t["type"]](t)
                api("/api/w/complete", {"run_id": RUN, "task_id": t["id"], "outputs": out})
            except Exception:
                err = traceback.format_exc()[-3000:]; log(err)
                api("/api/w/fail", {"run_id": RUN, "task_id": t["id"], "error": err})
            finally:
                stop.set(); shutil.rmtree(WORK / f"t{t['id']}", ignore_errors=True)
        except Exception as e:
            log(name, "loop error", e); time.sleep(10)


if __name__ == "__main__":
    comfy.wait_up()
    api("/api/w/heartbeat", {"run_id": RUN, "ready": True})
    threading.Thread(target=lane, args=("voice",), daemon=True).start()
    threading.Thread(target=lambda: [time.sleep(30) or api("/api/w/heartbeat", {"run_id": RUN}) for _ in iter(int, 1)], daemon=True).start()
    lane("gpu")
