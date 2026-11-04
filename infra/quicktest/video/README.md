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

### Lesson: never generate several distinct deities from several references in one edit (2026-11-03)
Qwen-Image-Edit with three character references in one call blended them: both group variants had Brahma twice and a
Vishnu/Shiva hybrid, and OWLv2 name queries still "found" all three, so the automatic check passed. `deities2.py` composes
the group deterministically from cut-outs of each deity's own sheet (`tridev_compose.py`: GrabCut on the plain sheet
background, fixed slots: Shiva top centre, Brahma lower left, Vishnu lower right), then runs a single-image lighting
harmonize pass that is accepted only if each deity's crop still matches his sheet (DINOv2). Close frames come from the
exact composition windows, so they are guaranteed to show the right deity.

### Lesson: keep the series LOOK out of "empty" plates (2026-11-03)
The clip 1.3 field was prompted "no people" but also carried the series LOOK ("family film ... expressive faces"), and
Qwen-Image drew a man, a boy and a girl into it; they then ghosted through 1.3-A/B and the harmonized Tridev frame.
`field.py` drops LOOK, adds a people negative and rejects any candidate where OWLv2 finds a person/face (score >= 0.12).

### Captions
`s34.finish` now shows the caption as timed 2-line chunks (`cap_chunks`, split at punctuation) instead of one block for
the whole clip; chunk times follow character share, or explicit `cap_starts` for phrase-voiced clips (1.4).
`reassemble.py` re-runs only the final assembly from the rendered parts (no GPU).

### Episode assembly (2026-11-04)
- `cuts.py` finds visual jumps (frame difference far above its neighbourhood). Big ones (>30) should only be intended cuts.
- Chained first/last-frame shots must be RETIMED to their slot, never trimmed: renders run ~0.15 s long, and trimming
  dropped the frames that reach the end keyframe, so every 1.4 seam jumped. `rebuild34.py` keeps all frames, drops the
  duplicate first frame of each chained shot, and (1.4) lays Dadi's phrases so each element finishes forming 0.2 s after
  its name starts; the element label shows the spoken word large with the Sanskrit name beneath.
- `episode.py` trims dead air at clip edges and overlaps clips with designed joins (void->void dissolve, golden-flare
  dissolves for the divine-light joins, fade to the end card). Audio is laid per clip at its offset and mixed, never
  crossfaded, so no word inside a transition is faded out. Captions fade in/out over 0.15 s.
- `ep_consistency.py` scores the final episode: characters/deities vs locked sheets (OWLv2 + DINOv2), set vs the
  living-room plate, voices vs locked references (WavLM-SV), every hard cut, the largest jump inside each join, 1.4 sync.
