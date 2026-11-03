"""Deterministic reframing for continuity: find a subject in the master shot (OWLv2) and crop a 9:16 window.
usage: python reframe.py <image> <mode> <subject> <out.png>
  mode mcu    : medium close-up, head to waist of the subject
  mode object : the object (paper, hand) and its surroundings
  mode two    : both characters, heads to waist
The crop is then re-rendered at full resolution by Qwen-Image-Edit, which keeps the crop's composition."""
import sys
import torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor

Q = {"tara": "a little girl in a yellow kurta with braids", "dadi": "an old woman in a white saree with grey hair",
     "paper": "a black sheet of paper held in hands", "hand": "a child's hand on a yellow kurta",
     "brahma": "a four-faced bearded deity seated on a pink lotus", "vishnu": "a blue-skinned four-armed deity with a crown",
     "shiva": "a meditating deity with ash-blue skin and matted hair"}
dev = "cuda"
op = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
om = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").to(dev).eval()


@torch.no_grad()
def box(img, q):
    out = om(**op(text=[[Q[q]]], images=img, return_tensors="pt").to(dev))
    s = max(img.size)
    r = op.image_processor.post_process_object_detection(out, threshold=0.05, target_sizes=torch.tensor([[s, s]]).to(dev))[0]
    if len(r["scores"]) == 0:
        raise SystemExit(f"no '{q}' found")
    i = int(r["scores"].argmax())
    return [float(v) for v in r["boxes"][i]], float(r["scores"][i])


def window(cx, top, H, img):
    """9:16 window of height H, top edge at `top`, centred on cx, clamped inside the image."""
    W_, H_ = img.size
    H = min(H, H_, W_ * 16 / 9); w = H * 9 / 16
    x0 = min(max(0, cx - w / 2), W_ - w); y0 = min(max(0, top), H_ - H)
    return (int(x0), int(y0), int(x0 + w), int(y0 + H))


def main(path, mode, subj, out):
    img = Image.open(path).convert("RGB")
    if mode == "two":
        (a, sa), (b, sb) = box(img, "dadi"), box(img, "tara")
        x0, y0, x1, y1 = min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])
        h = y1 - y0
        win = window((x0 + x1) / 2, y0 - 0.08 * h, max(0.75 * h, (x1 - x0) * 1.08 * 16 / 9), img)
    else:
        (x0, y0, x1, y1), sc = box(img, subj)
        w, h = x1 - x0, y1 - y0
        if mode == "mcu":   # head to waist; wide enough for the shoulders
            win = window((x0 + x1) / 2, y0 - 0.06 * h, max(0.62 * h, w * 1.25 * 16 / 9), img)
        else:               # object: keep it about 45% of the frame height
            m = 1.25 * max(h, w * 16 / 9)  # object fills most of the frame width; room around it
            win = window((x0 + x1) / 2, (y0 + y1) / 2 - m / 2, m, img)
    img.crop(win).save(out)
    print(f"{mode} {subj}: crop {win} of {img.size}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:5])
