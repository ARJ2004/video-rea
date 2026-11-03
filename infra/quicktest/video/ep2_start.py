"""Episode 2 (draft) prep on the shared box: Manu/Shatarupa sheets + night living-room master from ep1's master shot."""
import json
from pathlib import Path
import comfy, s34

E = json.load(open(s34.J / "ep2" / "storyboard.json")); LOOK = E["style"]["look"]
SHEET = "full-body character reference sheet, front view, centred, plain warm cream background, {d}. Style: {look}"
NIGHT = ("Keep EXACTLY this room, camera, framing, sofa, and both characters with their seating (Dadi on the left, Tara on the right, "
         "both seated), faces and clothes. Change only the time and props: it is now night - the window shows a deep blue sky with "
         "stars, warm lamp light, the brass diya is lit, and a small tulsi plant in a clay pot stands on the windowsill; Tara is "
         "looking at the tulsi plant. Style: {look}")
comfy.wait_up(); out = {}
for k in ("manu", "shatarupa"):
    out[k] = []
    for v in range(2):
        f, s = comfy.run(s34.g_t2i(SHEET.format(d=E["characters"][k]["description"], look=LOOK), f"ep2/sheets/{k}_v{v+1}", 2100 + v))
        out[k].append(str(f[0])); print(k, v + 1, s, "s", flush=True)
master = comfy.to_input("/mnt/nvme/ComfyUI/output/srishti/kf/1.1-A_v1_00001_.png", "ep2_ep1_master.png")
out["living_room_night"] = []
for v in range(2):
    f, s = comfy.run(comfy.g_keyframe(NIGHT.format(look=LOOK), [master, "refs/tara_sheet.png", "refs/dadi_sheet.png"], f"ep2/sheets/night_master_v{v+1}", 2200 + v))
    out["living_room_night"].append(str(f[0])); print("night master", v + 1, s, "s", flush=True)
json.dump(out, open("/mnt/nvme/ComfyUI/output/ep2/sheets.json", "w"), indent=2)
print("EP2 SHEETS DONE", flush=True)
