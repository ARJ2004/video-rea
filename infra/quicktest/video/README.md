# Srishti ep1 video pipeline (headless ComfyUI)

Runs on the GPU box. Copy this folder plus `stories/srishti-ep1/storyboard.json`, `pipeline/comp/void.sh` and the locked voice takes (`voices/`) to `/mnt/nvme/jobs3/`. Everything uses the ComfyUI venv.

| Stage | Command | What it does |
|---|---|---|
| Master keyframes | `make_clips.py keyframes --only 1.1-A` | Qwen-Image-Edit-2509 + Lightning 8-step, using the locked sheets `refs/{tara,dadi,living_room}` |
| Coverage | `make_clips.py coverage` | **Continuity rule:** every closer shot is *cropped* from the scene's master shot (`reframe.py`, OWLv2), then re-rendered at full detail. Image 1 is the crop, which fixes framing and seating; image 2 is the character sheet, which fixes identity. Dadi is LEFT and Tara RIGHT on the sofa; both stay seated. |
| Pick | `consistency.py pick` | Face similarity (OWLv2 → DINOv2) against the sheets, plus scene similarity against the crop. Insert shots (paper, hand) are judged on the scene only. |
| Motion | `make_clips.py shots` | Wan 2.2 I2V A14B + LightX2V 4-step, 480×832 |
| Talking heads | `make_clips.py talk` | Native InfiniteTalk (Wan 2.1 480p + patch + LightX2V), one pass sized to the audio at 25 fps |
| Drift | `consistency.py videos` | Face similarity at the first, middle and last frame of each shot |
| Assembly | `assemble.py prep` / `assemble.py assemble` | Splits 1.1-L2 after "ओम्" (on camera vs voice-over), then cuts each clip at 1080×1920/30 with captions and −14 LUFS. The 1.1-D push-in dissolves into the void. |
| Clip 1.2 | `scene2.py` | Composited void and ॐ pulses with a synthesized heartbeat, then two Wan 2.2 shots at 720×1280, each chained from the previous shot's last frame, with Dadi's voice-over |

Lessons from the first run (2026-11-03):
- **Generating close-ups from scratch breaks continuity.** Characters stood up, Dadi "emerged from the table", and positions swapped. Prompting the edit model to "reframe" image 1 also failed, because it copies image 1's framing. Crop first, then re-render. That fixed both problems.
- **Tara picked up Dadi's glasses** from a generic "keep the glasses" sentence. Each character now gets her own keep-list, and Tara's says "Tara does NOT wear glasses".
- **`WanImageToVideo.ref_pad_image` (SVI anti-drift) gave Wan 2.2 I2V a red cast and grain.** Don't use it.
- **API changes in this ComfyUI build:**
  - `ImageScaleToTotalPixels` needs `resolution_steps`.
  - The core `SaveVideo` uses dynamic combos, so we save with `VHS_VideoCombine` instead.
  - OWLv2 post-processing now lives in `processor.image_processor`.
- **Timings on a g6e.2xlarge (L40S):**
  - keyframe: 15–25 s
  - Wan 2.2 I2V at 480×832: 81 frames in about 25 s, 129 frames in about 90 s
  - InfiniteTalk: about 80–130 s for a 4–6 s line
