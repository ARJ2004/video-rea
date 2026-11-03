"""Stage 0 for clips 1.3/1.4: Tridev reference sheets -> group keyframe -> close keyframes cropped from the group.
Writes /mnt/nvme/work3/deities/state.json. Sheet choice can be overridden: python deities.py --sheets brahma=2,vishnu=1"""
import json, subprocess, sys
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
import comfy, s34

DW = s34.DW; DW.mkdir(parents=True, exist_ok=True); ST = DW / "state.json"
LOOK = s34.LOOK
SHEET = ("full-body character reference sheet, front view, centred, plain warm cream background, "
         "Indian devotional animation for children, gentle and benevolent, {d}. Style: {look}")
GROUP = ("image 1 shows Brahma, image 2 shows Vishnu, image 3 shows Shiva. Create one vertical 9:16 frame: Shiva seated in meditation "
         "at the top centre, Brahma seated on a pink lotus at the lower left, Vishnu standing at the lower right; each surrounded by a "
         "golden halo; cosmic golden light background; all three fully visible, clearly separated. Keep each deity's faces, skin colour, "
         "number of arms, attributes and clothing exactly as in their reference image. Style: {look}")
CLOSE = ("Image 1 is a cropped close shot of {name} from this scene. Re-render it as a sharp, detailed, full-resolution vertical 9:16 "
         "frame with EXACTLY the same framing, pose, halo and golden cosmic background as image 1. Image 2 is {name}'s character "
         "reference: keep his faces, skin colour, arms, attributes and clothing exactly as in image 2. Only {name} appears. Style: {look}")
dp = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
dm = AutoModel.from_pretrained("facebook/dinov2-base").cuda().eval()


@torch.no_grad()
def emb(p):
    e = dm(**dp(images=Image.open(p).convert("RGB"), return_tensors="pt").to("cuda")).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(e, dim=-1)[0]


def st():
    return json.load(open(ST)) if ST.exists() else {}


def save(S):
    json.dump(S, open(ST, "w"), indent=2)


def main(choice):
    comfy.wait_up(); S = st()
    if "sheets" not in S:
        S["sheets"] = {}
        for k, d in s34.DEITY.items():
            outs = []
            for v in range(2):
                files, sec = comfy.run(s34.g_t2i(SHEET.format(d=d, look=LOOK), f"srishti/deity/{k}_v{v+1}", 1200 + v))
                outs.append(str(files[0])); print(k, f"v{v+1}", sec, "s", flush=True)
            S["sheets"][k] = outs
        save(S)
    S["chosen"] = {k: S["sheets"][k][choice.get(k, 1) - 1] for k in s34.DEITY}
    names = {k: comfy.to_input(p, f"deity_{k}.png") for k, p in S["chosen"].items()}
    # group frame: pick the variant whose deity crops look most like the sheets
    best = None
    for v in range(2):
        files, sec = comfy.run(comfy.g_keyframe(GROUP.format(look=LOOK), [names["brahma"], names["vishnu"], names["shiva"]],
                                                f"srishti/deity/group_v{v+1}", 1300 + v))
        g = str(files[0]); score = 0.0; crops = {}
        for k in s34.DEITY:
            c = DW / f"crop_{k}_v{v+1}.png"
            r = subprocess.run([sys.executable, str(s34.J / "reframe.py"), g, "mcu", k, str(c)], capture_output=True, text=True)
            if r.returncode == 0:
                crops[k] = str(c); score += float(emb(c) @ emb(S["chosen"][k]))
        print("group", v + 1, sec, "s", "score", round(score / 3, 3), sorted(crops), flush=True)
        if len(crops) == 3 and (best is None or score > best[0]):
            best = (score, g, crops)
    if best is None:
        raise SystemExit("no group frame with all three deities detected")
    S["group"], S["group_crops"] = best[1], best[2]
    S["close"] = {}
    for k in s34.DEITY:
        crop = comfy.to_input(S["group_crops"][k], f"deity_crop_{k}.png")
        files, sec = comfy.run(comfy.g_keyframe(CLOSE.format(name=k.capitalize(), look=LOOK), [crop, names[k]], f"srishti/deity/close_{k}", 1400))
        S["close"][k] = str(files[0]); print("close", k, sec, "s", flush=True)
    save(S); print("DEITIES DONE", flush=True)


if __name__ == "__main__":
    choice = {}
    if len(sys.argv) > 2 and sys.argv[1] == "--sheets":
        choice = {a.split("=")[0]: int(a.split("=")[1]) for a in sys.argv[2].split(",")}
    main(choice)
