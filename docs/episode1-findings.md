# Srishti Episode 1: findings and how we are addressing them

Status as of 2026-11-04. The final cut is `s3://vrea-686112930191-us-east-1/results/srishti_ep1.mp4`: 100.7 s,
1080×1920, 30 fps, −13.8 LUFS, five clips. The measured results are in
[`infra/quicktest/video/consistency-ep1-2026-11-04.json`](../infra/quicktest/video/consistency-ep1-2026-11-04.json).

## 1. What the final consistency test says

The test ran on the stitched episode. It sampled one frame per second, found each face or deity with OWLv2, embedded it
with DINOv2 and compared it with the locked reference sheet (1.0 = identical).

| Check | Result | Verdict |
|---|---|---|
| Voices vs locked references (WavLM speaker verification) | Dadi 0.979–0.991, Tara 0.969–0.988 | Consistent |
| Brahma (1.3 / 1.4) | mean 0.91 / 0.87, lowest 0.71 while elements form in his hands | Consistent |
| Vishnu, Shiva (1.3) | 0.88, 0.83 (Shiva's sheet is detected weakly, so his score reads low) | Consistent |
| Dadi (1.1 / 1.5) | mean 0.79 / 0.79 | Consistent |
| Tara (1.1 / 1.5) | mean 0.49 / 0.55, one real drift at 87.8 s | **Weak: open** |
| Room vs locked plate | Automatic score not meaningful (0.15–0.19); checked by eye: same room | Metric needs fixing |
| Joins between clips | largest frame jump inside a join 2.3–20.4, where an intended cut measures about 60 | Smooth |
| Hard cuts | 10 in the episode, all intended (dialogue, insert, name cuts) | Pass |
| 1.4 voice/picture sync | every element is formed 0.20 s after its name starts | In sync |

## 2. Findings and fixes

### Fixed

| # | Finding | Root cause | Fix (where) |
|---|---|---|---|
| 1 | Tridev group shot blended the gods (Brahma twice, a Vishnu/Shiva hybrid), yet the automatic check passed it | One edit call with three character references mixes identities. The OWLv2 name query "finds" any god. | Group frame is composed from each god's own sheet (cut-out, fixed slots), then a single-image lighting pass that is rejected if any god drifts from his sheet. `tridev_compose.py`, `deities2.py` |
| 2 | Hidden man, boy and girl in the "empty" gold field (a ghost face) | The series style text ("family film… expressive faces") was added to an empty-plate prompt | Empty plates leave out the series style, add a people negative, and an OWLv2 people gate rejects any person or face. `field.py` |
| 3 | Captions were one 8-line block for a whole clip | One drawtext per line | 2-line chunks timed to the voice (or to phrase starts), 0.15 s fades. `s34.finish`, `cap_chunks` |
| 4 | Sudden jumps between 1.4's element shots | First/last-frame shots were trimmed to their slot. Renders run about 0.15 s long, so the frames that reach the end keyframe were cut, while the next shot starts on that keyframe. | Shots are retimed to their slot, never trimmed. The duplicate first frame is dropped. `rebuild34.py`, verified by `cuts.py` |
| 5 | Voice and picture out of sync in 1.4 (earth formed about 5 s after "धरती") | Shot slots came from a fixed 3.4 s grid, not the voice | Phrases are laid out from the pictures: each element is formed 0.2 s after its name starts, and earth holds with a slow push-in. `rebuild34.py` |
| 6 | Label said वायु, अग्नि, जल, पृथ्वी while Dadi said हवा, आग, पानी, धरती | The storyboard overlay used Sanskrit names | The big label is the spoken word, with the Sanskrit name small beneath it. `s34.label2_png` |
| 7 | Clip joins dipped to black, with up to 11 s of dead air (1.1 void + 1.2 void, 1.5 silent outro) | Each clip was assembled alone, with its own fades | `episode.py` trims dead air and overlaps clips with designed joins: a void→void dissolve, golden-flare dissolves for the divine-light joins, and a fade to the end card. Audio is laid per clip and mixed, never crossfaded, so no word is faded out. |
| 8 | शतरूपा voiced as "shat-rūpā" (Ep2) | Schwa deletion | Lexicon entry शत-रूपा (`pipeline/vrea/pronounce/lexicon.tsv`) |
| 9 | 1.2 ends with the light shrinking back (it should expand) | 1.2-D render | Mitigated: the episode cuts on the burst's peak. A re-render is still open. |
| 10 | Scoring models could not be downloaded in the dev sandbox | huggingface.co blocked by the sandbox network | Mirrored to `s3://…/models/hf/` by a short-lived CPU instance |

### Open: planned fixes

| # | Finding | Plan |
|---|---|---|
| A | **Tara identity is weak** (0.49–0.55, while Dadi is 0.79) | 1) Train a small identity LoRA for Tara on her chosen sheet and approved keyframes (Qwen-Image-Edit and Wan). 2) Score every Tara keyframe and video shot, and regenerate below 0.60 before review. 3) For talking-head shots, prefer the keyframe with the highest Tara score as the InfiniteTalk source. |
| B | Brahma's 4 arms become 2 while fire, water and earth form (1.4) | Add "four arms" to the element keyframe prompts and check the arm count on each element keyframe before rendering. Reject morphs whose middle frame drops below the Brahma threshold (0.75). |
| C | Faint figure-like silhouettes inside the three light forms (1.3-B, about 5 s) | Run the people gate on the 1.3-B end keyframe, and add "no figures inside the light" to its prompt. |
| D | 1.2-D light shrinks instead of expanding | Re-render as a first/last-frame shot that ends on an expanded-light keyframe |
| E | Room consistency metric not meaningful | Score the background only: mask out the detected people and compare the rest with the plate. Or compare wide shots with each other (same set, same people). |
| F | Automatic checks can pass wrong images (finding 1) | A human review gate after keyframes, before any video is rendered. That gate is part of the orchestration platform below. |
| G | No music bed, so the cosmic stretches are quiet | Add a low devotional drone/tanpura bed with ducking under the voice at assembly |
| H | Shiva's eyes open in his close-up (closed on his sheet) | Accepted as a "reveal". Revisit if you prefer them closed. |

## 3. Process lessons (carried into the platform)

1. **Generate one identity per call.** Never ask an edit model to draw several distinct characters from several
   references at once. Compose, then harmonize.
2. **Empty plates never get the series style text.** Every plate gets a people gate.
3. **Chained shots are retimed, never trimmed.**
4. **Timing comes from the voice.** Lay out the shots from where the words land, then check sync automatically.
5. **Automatic scores rank variants. A person approves keyframes before video is spent on them.**
6. **Measure on the final cut.** Consistency, cuts, joins and loudness are all checked on the stitched episode.

See also: [`gpu-utilization.md`](gpu-utilization.md) (machine usage) and
[`orchestration-platform.md`](orchestration-platform.md) (the platform plan).
