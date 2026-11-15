# Handoff: writers' room, reference-reel research, new render features

For the next agent working on this repo. Read this first, then the linked docs for detail.

- **Repo:** `arj2004/video-rea`
- **Branch:** `claude/compassionate-newton-gbsmhr`, five commits on top of `6389314`, not merged
- **Date:** 2026-11-15

## 0. One-paragraph summary

The platform (`platform/`) turns a story into a vertical 9:16 episode: storyboard, character and set designs, voices,
keyframes, video shots, clips, then the episode. You review the output at gates. This work did three things:
1. Replaced the single Claude call that drafted the storyboard with a **multi-agent "writers' room"**.
2. **Researched what actually performs** in short-form AI video, from real Instagram reels and YouTube Shorts, and
   wrote the findings into the agents' shared playbook.
3. Added **render features** the research showed were missing: punch captions, a vote card, a music bed, and story
   formats.

None of this has run against the real Claude API or on the deployed server yet (see §6).

## 1. The owner's goals, in their own direction

- Split video generation into specialist agents (director, storyboard, dialogue, and so on).
- Learn hooks and craft from real reels and reverse-engineer them. The owner rejected India-specific findings for story
  hooks: **story hooks should be global**. For **Indian mythology**, the owner supplied specific reels to learn from.
- The owner's reference accounts and reels:
  - Story and hook: [oddhourtales](https://www.instagram.com/oddhourtales/) ([reel](https://www.instagram.com/oddhourtales/reel/DfcVM8lxlKk/)),
    [_behindthebuild._](https://www.instagram.com/_behindthebuild._/) ([reel](https://www.instagram.com/_behindthebuild._/reel/DfwEiPJh7jD/))
  - Mythology: [Dfv19G6o5cK](https://www.instagram.com/reel/Dfv19G6o5cK/), [DdNzdISy_fO](https://www.instagram.com/reel/DdNzdISy_fO/),
    [DfUAr5JhqC8](https://www.instagram.com/reel/DfUAr5JhqC8/)
- Existing stories: `stories/srishti-ep1`, `srishti-ep2` (Hindi; Dadi narrates to Tara; scripture) and
  `stories/the-third-knock-ep1` (English lighthouse horror, nearly the same premise as oddhourtales).

## 2. What was built (file map)

### 2.1 Writers' room: `platform/server/writers_room/`

| File | What it is |
|---|---|
| `playbook.py` | Knowledge shared by every agent. `PLAYBOOK` holds the general retention rules plus **MEASURED EVIDENCE A–I**, which override the general rules. `PLATFORM_RULES` says exactly what the renderer supports. `language_rules()` covers Hindi (only the locked tara/dadi voices) and English (Parler voice descriptions). `FORMATS` holds the story, spectacle and meme guides. **Edit the research here, not in the role prompts.** |
| `roles.py` | Seven roles, each with its craft and its JSON output contract: Showrunner/Director, Hook Doctor, Casting & Design, Screenwriter, Storyboard Artist/Cinematographer, Editor & Sound, Director Review. |
| `room.py` | The orchestrator. The order of calls is below. Every stage's output is saved in `storyboard["preproduction"]`, which the platform ignores and the Script gate displays. `Room(..., kind="story"|"spectacle"|"meme")`. |
| `lint.py` | Deterministic checks. **Errors** are things the platform would reject. **Warnings** go to the reviewer: hook words from second 0, average shot length, voice coverage, models' weak spots, a vote or end card on story endings. |

**Order of calls in `room.py`:**
1. The Showrunner writes the brief.
2. The Hook Doctor (5 scored cold opens) and Casting run in parallel.
3. The Screenwriter writes the lines.
4. The Storyboard Artist writes the shots.
5. The Editor writes a patch of sound, overlays, HUD, vote card or end card. Values the platform can't render are
   dropped.
6. Lint and repair: up to 2 Storyboard passes to fix hard errors. If errors remain, the draft fails with the reason.
7. Director Review, then at most one revision round.

**How it calls Claude:**
- Model `claude-opus-5-5`, streaming.
- `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"` (same as the existing `drafting.py`).
- Adaptive thinking, with effort set per role.
- The shared system prefix (playbook, rules, language, story) has `cache_control`.
- Cost and time per call are recorded in `preproduction.calls` and `cost_usd`. Estimated $1–3 and 5–10 min per draft;
  **not measured**.

**App integration (`platform/server/app.py`, templates):**
- New story → "Draft with Claude" runs the room in a **background thread** (`start_room`). Project status is
  `drafting`, then `running` with the Script gate open, or `draft_failed` with a **Redraft** button
  (`POST /p/{pid}/redraft`).
- A restart while drafting marks the project `draft_failed`.
- The New story form has fields for mode (room or the old "quick" single call), format (story, spectacle or meme),
  language, length, ending (cliffhanger, loop or payoff) and directions.
- The Script gate (`templates/slot.html`) shows the brief, the locked hook, a post title, the review scores and notes,
  the lint warnings, all hook candidates and the beats.

### 2.2 Render features: `platform/server/overlays.py`, `assemble.py`, `drafting.py`

- **Punch captions:** set `"style": {"captions": "punch", "accent": "amber|red|green|cyan"}`.
  - Draws 2–4 word uppercase chunks with a dark outline. The word wrapped in `*asterisks*` in a line's `caption` gets
    the accent colour; with no marker, the longest non-filler word does.
  - Rendered as PNG layers (`overlays.punch_chunks`, `punch_png`, `assemble.punch_layers`) with 0.06 s fades.
  - Block captions strip the `*` markers. Writers' room drafts default to punch.
- **`vote` overlay style:** the end-of-episode audience vote card. Text format, one item per line:

  ```
  <moment, drawn red>
  <question>
  [OPTION A] [OPTION B]
  ~small footer (e.g. COMMENT YOUR CHOICE - MAJORITY DECIDES WHAT HAPPENS NEXT)
  >yellow pill (e.g. FOLLOW TO SEE THE FINAL NIGHT)
  ```

  `drafting.validate` and `lint` accept `vote`.
- **Music bed:** set `"music_bed": {"s3": "<key in the project bucket>", "gain_db": -14, "duck": true}`.
  - `assemble.bed_graph()` loops the track under the whole episode, fades it in and out, ducks it under the voice
    (sidechain compression), and normalizes to −14 LUFS.
  - Before this the only music was the synthesized `drone`.
  - The owner must upload a licensed track.
- Clips with no lines (spectacle and meme formats) already work: `mix()` falls back to silence plus ambience and music.

### 2.3 Research tools: `infra/research/`

| Tool | Use |
|---|---|
| `ig_reels.py` | Takes public Instagram reel URLs (or `--list urls.txt`). Pulls stats and caption from Instagram's **official embed page** (`/reel/<code>/embed/captioned/`, works logged out), downloads the video, runs the autopsy, and writes hook and body frame sheets plus `reels.json`. |
| `reel_autopsy.py` | Any mp4s → first cut, cuts in the first 3 s, shot lengths, cut cadence by quarter, hook motion, first-frame contrast, opening sound hit, LUFS, silence share, loop similarity, and a contact sheet. With `--meta` views, it compares the top third against the bottom third. |
| `yt_scan.py` | YouTube Shorts channels or searches → each Short's views against **its own channel's median** (`x_median`), plus top-versus-typical thumbnail sheets. Metadata only. |
| `data/*.json` | Raw results: `ig-reels-2026-11-15.json` (story reels), `ig-mythology-2026-11-15.json`, `yt-shorts-scan-2026-11-15.json` (499 Shorts). |

### 2.4 Tests

- `platform/tests/test_writers_room.py` runs offline with no API key. A stub client plays every role.
- It checks: orchestration, the parallel stage, the editor patch filtering, the lint/repair loop (an injected bad ref),
  the review/revise loop, that editor fields survive revision, and that the result passes the platform's own
  `validate()`.
- Run it with `python3 platform/tests/test_writers_room.py`. It passes.

## 3. Research findings (the parts that matter)

### 3.1 Global story hooks: oddhourtales "Night 6"

445K views, 10% like rate, 2,240 comments. Detail in `docs/what-works-global.md`.

1. **The hook is a consequence, not a setting.**
   - It starts mid-scene from black on a loud sound hit (+17.7 dB).
   - The first words pay off the audience's last vote: "YOU CHOSE TO LIGHT THE LAMP. YOU DIDN'T OPEN THE DOOR."
   - **The first cut is at 10.5 s; median shot 5.7 s.** The words, captions, HUD and push-ins carry the pace, not
     cutting. The generic "cut every 1.5–3 s" advice was retuned because of this.
2. **Persistent game-state HUD:** `NIGHT 5/7`, a big clock, location, and `LIGHT: OFF` / `SHIPS SAVED: 1` /
   `SHIPS LOST: 1`. Clock jumps are the scene changes.
3. **Plant a rule, then break it:** "Two honks. Never at night.", then two honks at 2:31 AM.
4. **The ending is a vote, held ~16 s (the longest shot):** "DO YOU GO DOWN TO THE BOAT? [GO DOWN] [STAY] · COMMENT YOUR
   CHOICE · MAJORITY DECIDES · FOLLOW TO SEE THE FINAL NIGHT". This is where the comments come from.
5. **Captions:** 2–4 uppercase words, the key word coloured; sound effects are captioned too, e.g. "(HONK… HONK)".
6. Exposition comes from in-world devices (radio, handwritten log, clock), with one minimal 2D style and a simple fixed
   character.

**_behindthebuild._** (an explainer; small, 817 views):
- Opens on a riddle about a concrete object plus a number: "one chair nobody can explain… 20 lakh a year", drawn as one
  symbolic image.
- Labels pop in time with the voice; no cuts in 73 s.
- The ask is "COMMENT ROADMAP for the plan in DMs", the explainer version of the vote.

**Instagram's own ranking guidance:** the predictions that matter most are reshares, watching to the end, likes and
visits to the audio page. Reels that are mostly text, watermarked or framed with borders are shown less.

**The Third Knock ep1 against oddhourtales** (table in `what-works-global.md` §4):
- It opens on a 4 s establishing shot.
- Its HUD appears once and never updates.
- It uses 2-line block captions.
- It ends on a 5 s choice overlay with no comment or follow ask.

**It has not been redrafted yet.**

### 3.2 Indian mythology: the owner's 3 reels

Detail in `docs/what-works-mythology.md`.

- **Spectacle (2.13M views / 26.7% likes; 596K / 22.1%):**
  - One iconic scripture moment as darshan: Hanuman rises to a mountain's size behind Rama, or the leap to Lanka.
  - Scale contrast in the first frame (tiny Rama, an army of specks).
  - A power-up arc: scale, then a glow rising through him, then the act, then the wake.
  - Photoreal, music only, no narration or captions, 20–30 s, 5–6 shots (one cut every ~3.8 s), loops.
- **The 2.1M creator's posted prompt** (cut at the 2,200-character caption limit):
  - An identity master per character, ending "**One Rama exists in this film.**"
  - A **scale/location guide image, never used as a keyframe**: "hold exactly that proportion from shot 3 onward".
  - "**Every shot has background life**."
  - Timed shots with beat names and camera angles in degrees.
- **Meme (1.15M / 11.1%):** a 14 s static chibi 2D scene. Krishna spins a galaxy like a ball beside a modern boy, with a
  Hinglish punchline bubble ("Me toh sirf party le raha tha 😭") and a trending dialogue audio. The joke is on the human.
- **Like rates are 2–3× the story reels'** (devotional likes). Comments are low.
- **For Srishti:** keep the narrated 85–100 s episodes for depth, and add 20–30 s spectacle shorts and optional
  Tara-and-chibi-deity memes.

### 3.3 YouTube Shorts scan

Mostly Indian channels; the owner found this less relevant, but it still feeds evidence rule H.

- Outliers show **the threat and someone reacting to it in one frame**.
- Bright, close, uncanny frames beat dark silhouettes.
- Outliers repeat one formula with a fixed cast.
- Titles that stop mid-sentence plus 😱 hit 5× the channel median about 1.7× as often.
- Part 2 beat Part 1 in 5 of 8 pairs.

Detail in `docs/what-works-2026-11.md`.

## 4. Environment and access (important)

- **Cloud environment "video-rea"** (personal; this session uses it). It allows:
  - `www.instagram.com`, `i.instagram.com`
  - `scontent.cdninstagram.com`, `scontent-ord5-1/2/3.cdninstagram.com` (the reel video CDN for this region)
  - YouTube hosts, `i.ytimg.com`, `www.tiktok.com`, `arxiv.org`
  - package registries
- **Instagram:**
  - Logged-out profile pages show only follower and post counts.
  - **Use the official embed page per reel.** It gives views, likes, comments, caption, duration and usually the video
    URL.
  - Some reels expose only a cover image in the embed (probably licensed music), so there's no video.
  - Profile embeds don't list posts, so **the owner has to supply reel URLs**.
  - Do **not** use Instagram's private API, spoofed app-id headers or a logged-in account. A safety check blocked the
    private-API attempt, and logged-in scraping breaks Instagram's terms.
- **YouTube:** `yt-dlp --flat-playlist` metadata works. **Video download is blocked from cloud IPs** ("sign in to
  confirm you're not a bot"). Don't bypass it with cookies; the owner downloads videos on their own machine instead
  (command in `docs/what-works-2026-11.md`).
- If the Instagram CDN host changes region (anything other than `scontent-ord5-*`), `ig_reels.py` prints the refused
  host. Add that exact host to the environment.
- Not available in this container: the AWS CLI, `boto3`, the `anthropic` SDK, Noto fonts (previews used DejaVu; the
  server has Noto). Server code was tested here by stubbing `boto3` and `db` in `sys.modules`.

## 5. How to run things

```bash
python3 platform/tests/test_writers_room.py
```

```bash
python3 infra/research/ig_reels.py --out research/ig --list urls.txt
```

```bash
python3 infra/research/yt_scan.py --out research/yt "Name=https://www.youtube.com/@handle/shorts"
```

```bash
python3 infra/research/reel_autopsy.py <folder of mp4> --out <dir>
```

```bash
platform/deploy/deploy.sh update
```

The last one deploys to the platform server and is run by the owner; it needs AWS credentials.

## 6. Verified versus not verified

**Verified here:**
- The offline writers' room test.
- The Script-gate template rendering real `preproduction` data.
- The linter on both existing storyboards (0 errors).
- Punch captions through the real `assemble.burn()` on a synthetic clip.
- The vote card render; the music-bed filter graph on synthetic audio.
- The research tools on real reels and channels.

**Not verified:**
- **No real Claude API run of the writers' room**: no key or SDK in the container. The prompts, the JSON parsing on real
  replies, cost and time are all unmeasured.
- Not deployed. Punch captions, the vote card and the music bed haven't run in a real episode on the server, which uses
  Noto fonts.
- With many punch-caption chunks, each chunk is a full-frame PNG input to ffmpeg. Watch the memory and time of clip
  assembly on long clips; consolidate into one overlay video if it's slow.

## 7. Open next steps (suggested order)

1. **Run the writers' room for real** on The Third Knock ep2 (or redraft ep1) with format `story`, ending
   `cliffhanger`, `language: en`. Check the JSON parse rate, cost and time, and that the Script gate looks right.
2. **Redraft The Third Knock ep1** against the gap table in `what-works-global.md` §4: a "You…" consequence hook, a
   persistent `NIGHT 1/7` HUD that updates, punch captions, one rule planted and broken, a held `vote` card.
3. **A Srishti spectacle short** (format `spectacle`), e.g. Brahma's four faces opening, with a licensed `music_bed`.
4. **More reference reels:** the owner pastes 15–30 URLs per domain, including weaker posts from the same accounts.
   `ig_reels.py` then gives the top-versus-bottom comparison, and the thresholds in `lint.py` and the evidence in
   `playbook.py` get updated from it.
5. Downstream ideas, not built (from `docs/writers-room.md` §3):
   - Render 4 hook-frame variants for the first shot and rank them with a Claude vision judge.
   - Have Claude review the final cut for retention.
   - Word-timed (karaoke) captions.
   - Loop endings: render the last shot as first-frame/last-frame back to the first keyframe.
   - An identity LoRA per main character.
   - A series bible carried across episodes.

## 8. Doc index

- `docs/writers-room.md`: agent design, flow diagram, first-round research sources, downstream ideas
- `docs/what-works-global.md`: story/hook teardown (oddhourtales, _behindthebuild._), The Third Knock gap analysis
- `docs/what-works-mythology.md`: mythology teardown (spectacle, meme), the creator's prompt, Srishti implications
- `docs/what-works-2026-11.md`: YouTube Shorts outlier scan
- Earlier, pre-existing: `docs/orchestration-platform.md` (platform design), `docs/episode1-findings.md` (Ep1 QA and
  fixes)
