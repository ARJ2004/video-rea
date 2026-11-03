"""Tiny ComfyUI API client + the three graphs used for Srishti clips (keyframe, I2V, talking head)."""
import json, time, urllib.request, uuid, shutil
from pathlib import Path

B = "http://127.0.0.1:8188"
ROOT = Path("/mnt/nvme/ComfyUI")
INP, OUT = ROOT / "input", ROOT / "output"


def call(p, data=None):
    req = urllib.request.Request(B + p, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def wait_up():
    for _ in range(240):
        try:
            call("/system_stats"); return
        except Exception:
            time.sleep(5)
    raise RuntimeError("ComfyUI not up")


def object_info(names):
    return {n: call(f"/object_info/{n}").get(n) for n in names}


def run(graph, timeout=3600):
    """Queue a graph, wait, return list of output file paths (images/videos/audio)."""
    pid = call("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = call(f"/history/{pid}").get(pid)
        if h and h.get("status", {}).get("completed") is not None or (h and h.get("outputs")):
            st = h.get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(json.dumps(st.get("messages", []))[-3000:])
            files = []
            for o in h.get("outputs", {}).values():
                for k in ("images", "gifs", "videos", "audio"):
                    for f in o.get(k, []):
                        files.append(OUT / f.get("subfolder", "") / f["filename"])
            return files, round(time.time() - t0, 1)
        time.sleep(3)
    raise TimeoutError(pid)


def to_input(path, name=None):
    name = name or Path(path).name
    shutil.copy(path, INP / name)
    return name


# ---------------------------------------------------------------- keyframe: Qwen-Image-Edit-2509, multi-reference
def g_keyframe(prompt, refs, prefix, seed, w=720, h=1280):
    g = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2509_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors", "strength_model": 1.0}},
        "ms": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["lora", 0], "shift": 3.0}},
        "lat": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
    }
    pos = {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": prompt}
    neg = {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": ""}
    for i, r in enumerate(refs[:3], 1):
        g[f"li{i}"] = {"class_type": "LoadImage", "inputs": {"image": r}}
        g[f"sc{i}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [f"li{i}", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 1}}
        pos[f"image{i}"] = [f"sc{i}", 0]; neg[f"image{i}"] = [f"sc{i}", 0]
    g["pos"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": pos}
    g["neg"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": neg}
    g["ks"] = {"class_type": "KSampler", "inputs": {"model": ["ms", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
                                                     "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    g["dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}}
    g["save"] = {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": prefix}}
    return g


def vhs_save(images, prefix, fps, audio=None):
    i = {"images": images, "frame_rate": fps, "loop_count": 0, "filename_prefix": prefix, "format": "video/h264-mp4",
         "pingpong": False, "save_output": True, "pix_fmt": "yuv420p", "crf": 17, "save_metadata": True, "trim_to_audio": False}
    if audio is not None:
        i["audio"] = audio
    return {"class_type": "VHS_VideoCombine", "inputs": i}


NEG_VIDEO = ("blurry, low quality, distorted face, deformed hands, extra fingers, flicker, jitter, morphing, "
             "text, watermark, static frozen frame, overexposed")


# ---------------------------------------------------------------- shot: Wan 2.2 I2V A14B + LightX2V 4-step (high/low)
def g_i2v(image, prompt, prefix, seed, frames=81, w=480, h=832, fps=16):
    g = {
        "uh": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "ul": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "lh": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["uh", 0], "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "strength_model": 1.0}},
        "ll": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ul", 0], "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "strength_model": 1.0}},
        "mh": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lh", 0], "shift": 5.0}},
        "ml": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["ll", 0], "shift": 5.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": NEG_VIDEO}},
        "i2v": {"class_type": "WanImageToVideo", "inputs": {"positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "start_image": ["img", 0],
                                                            "width": w, "height": h, "length": frames, "batch_size": 1}},  # note: ref_pad_image (SVI anti-drift) caused a red cast + grain with Wan 2.2 I2V; not used
        "k1": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["mh", 0], "add_noise": "enable", "noise_seed": seed, "steps": 4, "cfg": 1.0,
                                                            "sampler_name": "euler", "scheduler": "simple", "positive": ["i2v", 0], "negative": ["i2v", 1],
                                                            "latent_image": ["i2v", 2], "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}},
        "k2": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["ml", 0], "add_noise": "disable", "noise_seed": seed, "steps": 4, "cfg": 1.0,
                                                            "sampler_name": "euler", "scheduler": "simple", "positive": ["i2v", 0], "negative": ["i2v", 1],
                                                            "latent_image": ["k1", 0], "start_at_step": 2, "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["k2", 0], "vae": ["vae", 0]}},
        "save": vhs_save(["dec", 0], prefix, fps),
    }
    return g
