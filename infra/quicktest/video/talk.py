"""Talking head: native ComfyUI InfiniteTalk (Wan 2.1 I2V 480p + InfiniteTalk patch + LightX2V 4-step),
one pass sized to the line's audio (InfiniteTalk runs at 25 fps; audio features are interpolated 50->25)."""
import math, subprocess
import comfy


def audio_seconds(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode())


def g_talk(image, audio_name, prompt, prefix, frames, seed=900, w=480, h=832):
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_i2v_480p_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "strength_model": 1.0}},
        "ms": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lora", 0], "shift": 5.0}},
        "mp": {"class_type": "ModelPatchLoader", "inputs": {"name": "wan2.1_infiniteTalk_single_fp16.safetensors"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "cvl": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "cve": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["cvl", 0], "image": ["img", 0], "crop": "none"}},
        "ael": {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": "wav2vec2-chinese-base_fp16.safetensors"}},
        "la": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "aee": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["ael", 0], "audio": ["la", 0]}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt + " The person speaks naturally with accurate lip movements."}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": comfy.NEG_VIDEO}},
        "it": {"class_type": "WanInfiniteTalkToVideo", "inputs": {
            "mode": "single_speaker", "model": ["ms", 0], "model_patch": ["mp", 0], "positive": ["pos", 0], "negative": ["neg", 0],
            "vae": ["vae", 0], "width": w, "height": h, "length": frames, "clip_vision_output": ["cve", 0], "start_image": ["img", 0],
            "audio_encoder_output_1": ["aee", 0], "motion_frame_count": 9, "audio_scale": 1.0}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["it", 0], "positive": ["it", 1], "negative": ["it", 2], "latent_image": ["it", 3],
                                                     "seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
        "save": comfy.vhs_save(["dec", 0], prefix, 25, audio=["la", 0]),
    }


def run(image, audio_path, prompt, prefix):
    name = comfy.to_input(audio_path)
    n = math.ceil(audio_seconds(audio_path) * 25) + 4
    frames = n + (4 - (n - 1) % 4) % 4
    return comfy.run(g_talk(image, name, prompt, prefix, frames))
