"""Clean golden light field for clip 1.3's opening AND the Tridev group background. The first field came out with a
man, a boy and a girl in it (the series LOOK says 'family film ... expressive faces'), so: no LOOK text, a people
negative, and an OWLv2 people check; first clean seed wins. Writes /mnt/nvme/work3/deities/field.png"""
import shutil, torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor
import comfy, s34

P = ("abstract soft swirling golden light ribbons and glowing mist on a deep indigo night sky, tiny luminous particles, "
     "an empty dreamlike space, nothing else, vertical, soft 3D render, warm and reverent")
NEG = "person, people, human, man, woman, boy, girl, child, family, face, figure, silhouette, character, animal, text, letters, symbol"
Q = ["a person", "a human face", "a child", "a man", "a woman"]
op = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
om = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").cuda().eval()


@torch.no_grad()
def people(path):
    im = Image.open(path).convert("RGB")
    out = om(**op(text=[Q], images=im, return_tensors="pt").to("cuda"))
    r = op.image_processor.post_process_object_detection(out, threshold=0.0, target_sizes=torch.tensor([im.size[::-1]]).cuda())[0]
    return float(r["scores"].max()) if len(r["scores"]) else 0.0


comfy.wait_up()
best = None
for i in range(5):
    g = s34.g_t2i(P, f"srishti/s3/field_clean_{i}", 1510 + i); g["7"]["inputs"]["text"] = NEG
    files, sec = comfy.run(g); p = people(files[0]); print("field", i, sec, "s people", round(p, 3), flush=True)
    if best is None or p < best[0]:
        best = (p, files[0])
    if p < 0.12:
        break
shutil.copy(best[1], s34.DW / "field.png"); print("FIELD DONE", best, flush=True)
