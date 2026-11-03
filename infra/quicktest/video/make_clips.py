"""Srishti ep1, clips 1.1 and 1.5 (the Tara/Dadi scenes): keyframes -> shots -> talking heads.
usage: python make_clips.py keyframes|shots|talk  [--only 1.1-A,...]
State is kept in /mnt/nvme/work3/state.json so each stage can be re-run independently."""
import json, sys, math
from pathlib import Path
import comfy

J = Path(__file__).parent
W = Path("/mnt/nvme/work3"); W.mkdir(parents=True, exist_ok=True)
STATE = W / "state.json"
SB = json.load(open(J / "storyboard.json"))
CLIPS = ("1.1", "1.5")
REF_FILE = {"tara": "refs/tara_sheet.png", "dadi": "refs/dadi_sheet.png", "living_room": "refs/living_room_plate.png"}
REF_NAME = {"tara": "the little girl Tara (8 years old, two braids with red ribbons, yellow kurta)",
            "dadi": "the grandmother Dadi (silver hair bun, round gold glasses, cream saree with maroon border)",
            "living_room": "the cozy living room set"}
LOOK = SB["style"]["look"]
# Locked voice takes (best ranked IndicF5 take per line, voice_v2 run)
AUDIO = {"1.1-L1": "1.1-L1_f5_t3.wav", "1.1-L2": "1.1-L2_f5_t2.wav", "1.5-L1": "1.5-L1_f5_t1.wav", "1.5-L2": "1.5-L2_f5_t2.wav"}


def shots():
    for c in SB["clips"]:
        if c["id"] in CLIPS:
            for s in c["shots"]:
                yield c, s


def st():
    return json.load(open(STATE)) if STATE.exists() else {}


def save(s):
    json.dump(s, open(STATE, "w"), indent=2, ensure_ascii=False)


KEEP = {"tara": "Tara keeps exactly her face, two braids with red ribbons and yellow kurta from her reference; Tara does NOT wear glasses",
        "dadi": "Dadi keeps exactly her face, silver hair bun, round gold-rim glasses and cream saree with maroon border from her reference"}


def kf_prompt(s):
    refs = [r for r in s.get("refs", []) if r in REF_FILE]
    # characters first, set last (image order = refs order below)
    refs = sorted(refs, key=lambda r: r == "living_room")
    chars = [r for r in refs if r in KEEP]
    parts = [f"image {i} shows {REF_NAME[r]}" for i, r in enumerate(refs, 1)]
    who = " and ".join(r.capitalize() for r in chars) or "no people"
    p = (f"{s['keyframe_prompt']}. Vertical 9:16 frame; follow this framing exactly. "
         f"References: {'; '.join(parts)}. {'. '.join(KEEP[r] for r in chars)}. "
         f"Only {who} may appear in the frame; no other people or partial figures at the edges. Style: {LOOK}.")
    return p, [REF_FILE[r] for r in refs]


# Continuity coverage: every closer shot is CROPPED from the scene's master shot (reframe.py, OWLv2), then the
# crop is re-rendered at full detail by Qwen-Image-Edit (image 1 = crop, keeps its composition) with the
# character sheet (image 2) restoring identity. Screen geography is fixed: Dadi sits on the LEFT of the sofa,
# Tara on the RIGHT; Tara looks screen-left at Dadi, Dadi looks screen-right at Tara. Both stay seated.
# (base shot, characters, crop mode, crop subject, action/expression change)
COVER = {
    "1.1-B": ("1.1-A", ["tara"], "mcu", "tara", "Tara holds the plain black sheet of paper at chest height and looks toward screen-left with puzzled wide eyes"),
    "1.1-C": ("1.1-A", ["dadi"], "mcu", "dadi", "Dadi looks softly toward screen-right with a calm, gentle storytelling expression; warm diya light on her face"),
    "1.1-D": ("1.1-B", ["tara"], "object", "paper", "Tara's small hands hold the plain black sheet of paper; the paper is centred and fills the middle of the frame"),
    "1.5-A": ("1.1-A", ["dadi", "tara"], None, None, "Same wide shot, same seating: Tara now looks at Dadi with amazed wide eyes and a big smile"),
    "1.5-B": ("1.5-A", ["tara"], "mcu", "tara", "Tara, excited with bright eyes, places one hand flat on her chest and looks toward screen-left; no paper"),
    "1.5-C": ("1.5-B", ["tara"], "object", "hand", "Tara's small hand rests gently on her chest over the yellow kurta"),
    "1.5-D": ("1.5-A", ["dadi"], "mcu", "dadi", "Dadi smiles warmly with kind eyes, looking toward screen-right"),
    "1.5-E": ("1.5-A", ["dadi", "tara"], "two", None, "Dadi gently rests her hand on Tara's head; Tara smiles proudly; the diya glows"),
}


def do_coverage(only, variants=2):
    import subprocess
    S = st()
    for sid in ["1.1-B", "1.1-C", "1.1-D", "1.5-A", "1.5-B", "1.5-C", "1.5-D", "1.5-E"]:  # bases come first
        if only and sid not in only:
            continue
        base, chars, mode, subj, action = COVER[sid]
        src = S[base]["keyframe"]
        if mode:
            crop = W / f"crop_{sid}.png"
            subprocess.run([sys.executable, str(J / "reframe.py"), src, mode, subj or "-", str(crop)], check=True)
            src = str(crop)
            what = "Image 1 is a cropped close shot from this scene. Re-render it as a sharp, detailed, full-resolution vertical 9:16 frame with EXACTLY the same framing, camera angle, seating, pose, background and lighting as image 1"
        else:
            what = "Image 1 is the master shot of this scene. Keep EXACTLY its framing, camera angle, seating positions, background and lighting"
        refs = [comfy.to_input(src, f"cov_{sid}.png")] + [REF_FILE[c] for c in chars]
        p = (f"{what}. Change only this: {action}. Images {', '.join(str(i) for i in range(2, len(refs) + 1))} are the character "
             f"references: " + "; ".join(REF_NAME[c] for c in chars) + ". " + ". ".join(KEEP[c] for c in chars) +
             f". Characters stay seated. Only {' and '.join(c.capitalize() for c in chars)} may appear. Style: {LOOK}.")
        outs = []
        for v in range(variants):
            files, sec = comfy.run(comfy.g_keyframe(p, refs, f"srishti/kf3/{sid}_v{v+1}", seed=650 + v))
            outs += [str(f) for f in files]; print(sid, f"v{v+1}", sec, "s", flush=True)
        S.setdefault(sid, {}).update({"kf_prompt": p, "kf_refs": refs[1:], "keyframes": outs, "base": base, "crop": src})
        S[sid].pop("video", None)
        save(S)
        subprocess.run([sys.executable, str(J / "consistency.py"), "pick", sid], check=True)  # later shots build on it
        S = st()


def frames_for(sec, fps=16):
    n = int(round(sec * fps)) + 1
    return n + (4 - (n - 1) % 4) % 4  # Wan wants 4k+1


def do_keyframes(only, variants=2):
    S = st()
    for c, s in shots():
        if "keyframe_prompt" not in s or (only and s["id"] not in only):
            continue
        p, refs = kf_prompt(s)
        outs = []
        for v in range(variants):
            files, sec = comfy.run(comfy.g_keyframe(p, refs, f"srishti/kf/{s['id']}_v{v+1}", seed=500 + v))
            outs += [str(f) for f in files]
            print(s["id"], f"v{v+1}", sec, "s", flush=True)
        S.setdefault(s["id"], {}).update({"kf_prompt": p, "kf_refs": refs, "keyframes": outs})
        save(S)


def do_shots(only):
    S = st()
    for c, s in shots():
        if s["tech"] not in ("I2V", "COMP+I2V", "I2V+COMP") or (only and s["id"] not in only):
            continue
        kf = S[s["id"]]["keyframe"]  # chosen by consistency.py pick
        name = comfy.to_input(kf, f"kf_{s['id']}.png")
        dur = s.get("dur_s", 3)
        prompt = f"{s['motion_prompt']}. {LOOK}. Consistent character faces, smooth natural motion."
        files, sec = comfy.run(comfy.g_i2v(name, prompt, f"srishti/shot/{s['id']}", seed=700, frames=frames_for(dur)))
        S[s["id"]].update({"video": str(files[0]), "gen_s": sec, "motion_prompt": prompt})
        save(S); print(s["id"], "i2v", sec, "s", flush=True)


def do_talk(only):
    import talk
    S = st()
    for c, s in shots():
        if s["tech"] != "TALK" or (only and s["id"] not in only):
            continue
        kf = S[s["id"]]["keyframe"]
        name = comfy.to_input(kf, f"kf_{s['id']}.png")
        audio = S[s["id"]].get("audio") or str(J / "voices" / AUDIO[s["line"]])
        files, sec = talk.run(name, audio, f"{s['motion_prompt']}. {LOOK}.", f"srishti/talk/{s['id']}")
        S[s["id"]].update({"video": str(files[0]), "gen_s": sec, "audio_used": audio})
        save(S); print(s["id"], "talk", sec, "s", flush=True)


if __name__ == "__main__":
    comfy.wait_up()
    stage = sys.argv[1]
    only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[2] == "--only" else set()
    {"keyframes": do_keyframes, "coverage": do_coverage, "shots": do_shots, "talk": do_talk}[stage](only)
