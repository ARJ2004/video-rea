"""Tridev group + close frames, v2. v1 asked the edit model to draw all three deities from three references at once and
it blended them (Brahma twice, Vishnu/Shiva merged). v2 composes the group from cut-outs of each deity's own sheet
(tridev_compose.py), then only HARMONIZES lighting with a single-image edit, accepted only if every deity still matches
his sheet. Close frames = exact crop windows of the group, re-rendered with that one deity's sheet.
usage: python deities2.py [--sheets brahma=2,vishnu=1,shiva=1]"""
import glob, json, sys, time
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
import comfy, s34, tridev_compose as tc

DW = s34.DW; ST = DW / "state.json"; LOOK = s34.LOOK
HARMONIZE = ("Keep the three figures EXACTLY as they are: same positions, sizes, poses, faces, skin colours, number of arms, held "
             "objects and clothing - do not redraw or change any figure. Only: replace the plain backdrop with a glowing golden "
             "cosmic light field with soft stars, make each ring a soft glowing golden aura behind its figure, remove the grey "
             "floor slabs under them so each rests on soft golden light-mist, and unify the warm lighting. Style: {look}")
CLOSE = ("Image 1 is a cropped close shot of {name} from this scene. Re-render it as a sharp, detailed, full-resolution vertical 9:16 "
         "frame with EXACTLY the same framing, pose, aura and golden cosmic background as image 1. Image 2 is {name}'s character "
         "reference: keep his faces, skin colour, arms, attributes and clothing exactly as in image 2. Only {name} appears; nobody "
         "else, no other figure's hands or objects. Style: {look}")
dp = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
dm = AutoModel.from_pretrained("facebook/dinov2-base").cuda().eval()


@torch.no_grad()
def emb(im):
    im = Image.open(im) if isinstance(im, (str, Path)) else im
    e = dm(**dp(images=im.convert("RGB"), return_tensors="pt").to("cuda")).last_hidden_state[:, 0]
    return torch.nn.functional.normalize(e, dim=-1)[0]


def crop_scores(group, wins, sheets):
    g = Image.open(group).convert("RGB")
    return {k: round(float(emb(g.crop(w)) @ emb(sheets[k])), 3) for k, w in wins.items()}


def main(choice):
    comfy.wait_up(); S = json.load(open(ST))
    S["chosen"] = {k: S["sheets"][k][choice.get(k, 1) - 1] for k in s34.DEITY}
    while not (DW / "field.png").exists():                                     # same clean gold field as clip 1.3's opening
        time.sleep(5)
    field = [str(DW / "field.png")]
    raw = DW / "group_raw.png"
    wins = tc.compose(S["chosen"], field[0] if field else None, raw)
    cands = [(str(raw), crop_scores(raw, wins, S["chosen"]))]
    print("group raw", cands[0][1], flush=True)
    rin = comfy.to_input(raw, "tridev_raw.png")
    for v in range(2):
        files, sec = comfy.run(comfy.g_keyframe(HARMONIZE.format(look=LOOK), [rin], f"srishti/deity/group2_v{v+1}", 1350 + v))
        sc = crop_scores(files[0], wins, S["chosen"]); cands.append((str(files[0]), sc))
        print(f"group harmonized v{v+1}", sec, "s", sc, flush=True)
    raw_min = min(cands[0][1].values())
    ok = [c for c in cands[1:] if min(c[1].values()) >= raw_min - 0.03]
    best = max(ok, key=lambda c: min(c[1].values())) if ok else cands[0]
    S["group"] = best[0]; S["group_windows"] = wins; S["group_scores"] = best[1]
    print("group chosen", Path(best[0]).name, best[1], flush=True)
    g = Image.open(S["group"]).convert("RGB"); S["group_crops"] = {}; S["close"] = {}; S["close_scores"] = {}
    for k, w in wins.items():
        c = DW / f"crop2_{k}.png"; g.crop(w).resize((720, 1280), Image.LANCZOS).save(c); S["group_crops"][k] = str(c)
        cin, sin = comfy.to_input(c, f"tridev_crop_{k}.png"), comfy.to_input(S["chosen"][k], f"tridev_sheet_{k}.png")
        files, sec = comfy.run(comfy.g_keyframe(CLOSE.format(name=k.capitalize(), look=LOOK), [cin, sin], f"srishti/deity/close2_{k}", 1450))
        S["close"][k] = str(files[0]); S["close_scores"][k] = round(float(emb(files[0]) @ emb(S["chosen"][k])), 3)
        print("close", k, sec, "s", "sim", S["close_scores"][k], flush=True)
    json.dump(S, open(ST, "w"), indent=2); print("DEITIES DONE", flush=True)


if __name__ == "__main__":
    choice = {"brahma": 2}                       # brahma v1 sheet has a stray "Reference" caption baked in
    if len(sys.argv) > 2 and sys.argv[1] == "--sheets":
        choice.update({a.split("=")[0]: int(a.split("=")[1]) for a in sys.argv[2].split(",")})
    main(choice)
