# What works: Indian mythology reels

Status: 2026-11-15. These are the three reels you picked, pulled with
[`infra/research/ig_reels.py`](../infra/research/ig_reels.py) (official embed, no login). The data is in
[`infra/research/data/ig-mythology-2026-11-15.json`](../infra/research/data/ig-mythology-2026-11-15.json).

| Reel | Views | Likes (rate) | Comments | Length | Format |
|---|---|---|---|---|---|
| [chitti.ai2221134 / Dfv19G6o5cK](https://www.instagram.com/reel/Dfv19G6o5cK/) | **2.13M** | 569K (**26.7 %**) | 539 | 30 s | Photoreal spectacle: Hanuman rises to a mountain's size behind Rama |
| [realinsaanluvya / DdNzdISy_fO](https://www.instagram.com/reel/DdNzdISy_fO/) | 1.15M | 128K (11.1 %) | 194 | 14 s | Chibi 2D meme: Krishna spins a galaxy; "Me toh sirf party le raha tha 😭" |
| [rajiv_kumar06 / DfUAr5JhqC8](https://www.instagram.com/reel/DfUAr5JhqC8/) | 596K | 132K (**22.1 %**) | 266 | 20 s | Photoreal spectacle: Hanuman's power-up and leap to Lanka |

**Likes are 2–3× the story-reel rate.** The story reels were at 10% (oddhourtales) and 4%; these are at 11–27%. On
devotional reels a like is an act of devotion, and Instagram lists likes among its top ranking predictions.

**Comments are low** (0.02–0.05% of views, against 0.5% for the vote-driven story). These reels win on likes,
completion and shares, not on discussion.

## 1. Mythic spectacle (2.1M and 596K)

**The cover of the 2.1M reel is the whole idea.** It's a vertical frame:
- Rama stands tiny on the edge of a cliff, bow drawn.
- Hanuman rises from behind the forested ridge, his head as wide as the ridge and his golden gada above it.
- The vanara army with saffron banners is a sea of specks in the valley; birds are dots against his chest.

**The creator posted their own generation prompt in the caption.** It's cut at Instagram's 2,200-character limit, and
the rest is probably in a comment. It shows the process exactly:
- **REFERENCES:**
  - Image 1 is the *identity master* for Rama (skin, hair, tilak, dhoti, sash, armbands, quiver, golden bow) and says
    "**One Rama exists in this film.**"
  - Image 2 is the identity master for Hanuman (true vanara face, crown, tilak, gada) and says "**One Hanuman exists in
    this film.**"
  - Image 3 is "**the location, scale and viewing-angle guide only, never a keyframe**". It shows how big Hanuman is
    against the ridge, the spire and the army, and says "**hold exactly that proportion from shot 3 onward**".
- **WORLD AND SCALE:** "Hanuman is a living mountain… his head as wide as a full stretch of the forested ridge…
  everything below his chest stays behind the ridge for the whole film." "**Every shot has background life**: banners
  pulling in the wind, vanaras moving, trees swaying, fog sliding."
- **SHOTS:** "30 seconds, 6 shots, hard cuts". Each shot has a time range, a beat name and a camera spec, for example
  "SHOT 1, 0.0–4.0 s: the strike and the call. 47-degree view starting low at Rama's bare feet on the cliff rock…"

**The 596K reel** (measured):
- 5 shots, a hard cut every 3.8 s (perfectly regular).
- No voice and no captions: music only, steady (dynamic range 11.7 dB, no hit at the start).
- Last frame is 0.91 similar to the first, so it loops cleanly.
- The sequence:
  1. 0–3.8 s, wide: Hanuman and Rama on the shore, the vanara army in a line, a roaring sea.
  2. 3.8–7.5 s, medium: Hanuman powers up as a golden glow rises through his body.
  3. Wide: Hanuman, now giant, beside Rama.
  4. The leap: rock explodes.
  5. Flight over the ocean toward a light on the horizon.

**What makes spectacle work:**
1. **One iconic moment, not a story:** a darshan of the deity at full power, from a scene everyone already knows.
2. **Scale contrast in the first frame:** something tiny (Rama, an army, birds) against the colossal deity.
3. **A power-up arc:** scale, then presence (glow, eyes, wind), then the act (strike or leap), then the wake (flight,
   horizon light).
4. **Photoreal, cinematic, correct iconography**, stated identically for each character, one instance each.
5. **Music carries it.** No narration, no captions, a short devotional caption ("Jay Shri Ram 🚩🔱🚩").
6. **Short:** 20–30 s, 5–6 shots, and it loops.

## 2. Deity × modern meme (1.15M)

**The scene:**
- A single static 2D scene, 14 s, chibi style, sky-blue background.
- A cute Krishna (peacock feather, flute colours) lounges on a rock and casually spins a **galaxy** on his fingertip
  like a basketball, next to an ordinary modern boy.
- The text bubble at the top: "**Me toh sirf party le raha tha 😭**".

**Technique:**
- Audio is dialogue (28% silence, 47 dB dynamic range), almost certainly a trending sound lip-synced. Only the
  expressions and the prop move.
- There's one cut, at 13.4 s.
- The joke is the gap between the cosmic and the trivial, and it's on the human, never on the deity.

## 3. What this means for Srishti

Srishti episodes are 85–100 s, narrated by Dadi to Tara, and explain the scripture. None of the three hits does that:
they are short, wordless or one-line, and built on one moment. That suggests:
- Keep the narrated episodes for depth.
- Cut **spectacle shorts** from them, or make them alongside: Brahma's four faces opening, Vishnu on Shesha, the
  cosmic egg. These are the shareable 20–30 s darshans.
- Optionally make **meme reels** with Tara as the modern kid next to a chibi deity. Dadi and Tara already are that
  pairing.

## 4. What changed in the pipeline

- **Writers' room formats** (the New story page has a "Format" choice):
  - `story` is the existing narrated format.
  - `spectacle`: 15–30 s, one iconic moment, the scale shot first, the power-up arc, no narration, a held peak shot
    that loops.
  - `meme`: one static chibi scene, a Hinglish punchline bubble, trending audio, respectful.
  - The format guide overrides the general playbook. The linter skips its spoken-hook and vote-card checks for these.
- **For every format, from the 2.1M creator's prompt:**
  - Casting ends each character with "One <name> exists in this film." This targets the identity blending we hit with
    the Tridev group shot in Ep1.
  - Sets where scale matters state the proportion as a rule.
  - Every `motion_prompt` carries one line of background life, so no frame is frozen.
- **Music bed:** `"music_bed": {"s3": "<key of a licensed track>", "gain_db": -14, "duck": true}` in the storyboard
  mixes a track under the whole episode, looped and faded, and drops it under the voice. Before this the platform had
  only a synthesized drone, and spectacle reels run on music. Upload the track to the project bucket and put its key in
  the storyboard at the Script gate.

## 5. Limits of this read

- The 2.1M reel's embed shows only its cover, not its video, so its cuts and sound weren't measured. Its shot plan comes
  from the creator's own prompt.
- The 2.1M reel carries another creator's watermark (krishna.banala), so it may be a repost.
- Three reels show formats and craft, not what separates hits from misses. Add 15–30 more (including weaker posts from
  the same accounts) to `urls.txt`, then run:

  ```bash
  python3 infra/research/ig_reels.py --out research/myth --list urls.txt
  ```

  The autopsy then compares the top third against the bottom third.
