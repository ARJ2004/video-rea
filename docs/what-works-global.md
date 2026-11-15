# What works: reference reel teardown (global formats)

Status: 2026-11-15. The tool is [`infra/research/ig_reels.py`](../infra/research/ig_reels.py). Give it any public reel
URL and it fetches:
- the stats and caption, from Instagram's official embed page, which works logged out;
- the video;
- measurements, from [`reel_autopsy.py`](../infra/research/reel_autopsy.py);
- frame sheets: every 0.5 s for the first 8 s, then every 3 s.

The raw numbers are in [`infra/research/data/ig-reels-2026-11-15.json`](../infra/research/data/ig-reels-2026-11-15.json).

```bash
python3 infra/research/ig_reels.py --out research/ig https://www.instagram.com/<user>/reel/<code>/ ...
```

## 1. oddhourtales: interactive lighthouse horror ("Night 6")

[Reel](https://www.instagram.com/oddhourtales/reel/DfcVM8lxlKk/). 47K followers, 11 posts.
**445K views, 44.4K likes (10.0 % of views), 2,240 comments (0.5 %).** 79 s.

| Time | What happens |
|---|---|
| 0.0 s | Fades up from black on a **loud sound hit** (+17.7 dB over the median level). Mid-scene: the keeper at the lamp switch. A HUD is already there: `NIGHT 5/7`, a big `2:17 AM`, `GREYWICK ROCK · LIGHTHOUSE`, and pills `LIGHT: OFF` / `SHIPS SAVED: 1` / `SHIPS LOST: 1`. |
| 0.5–3 s | **"YOU CHOSE TO / LIGHT THE LAMP."** (LAMP in amber). The hook pays off *your* vote from the last episode. |
| 4.5–7 s | Slow push-in. **"YOU DIDN'T OPEN / THE DOOR."** (DIDN'T and DOOR in red). |
| 3–9 s | The lamp lights, then **"GONE."**: the door is gone. A consequence, and a new open question. |
| 9–21 s | Radio (`CH 16`, MOSS · RADIO) and the handwritten keeper's log: "Day 6. Moss called at noon. Generator parts: loaded. Day 8. First light. **Two honks. Never at night.**" A rule is planted. |
| 24–33 s | Clock jumps (6:12 PM → 1:44 AM → 2:30 AM) are the scene changes. Lighthouse exterior, the beam sweeps. |
| 33–39 s | A green light on the water through the window. Caption **(HONK… HONK)**. The rule is broken. |
| 42–60 s | Radio: **"KID!" "LAST ONE!"**. A boat at the jetty in the rain. **"PASSED…"** **"SAID."** |
| 63–79 s | **The vote card, held about 16 s (the longest shot):** "2:31 AM. TWO HONKS. DO YOU GO DOWN TO THE BOAT?", `[GO DOWN]` `[STAY]`, "COMMENT YOUR CHOICE · MAJORITY DECIDES WHAT HAPPENS NEXT", and a yellow pill "FOLLOW TO SEE THE FINAL NIGHT". |

**Measured:**
- 12 shots. **First cut at 10.5 s.** Median shot 5.7 s, longest 21 s (the vote card).
- First frame is black (brightness 0.01). Loudness −13.5 LUFS. Last frame is 0.73 similar to the first.
- Little hard cutting: the motion comes from the push-ins, the captions changing every 0.5–1 s, the HUD and the clock.

**Why it works:**
1. **The audience is a character.** "You chose…" opens on a consequence of the viewer's own vote.
2. **The vote at the end** turns viewers into commenters (2,240 comments), and comments drive ranking. "Follow to see
   the final night" turns them into followers. The 7-night arc gives the series an end in sight.
3. **Game state on screen:** night X/7, the clock, ships saved/lost. Stakes the viewer can track.
4. **Plant a rule, then break it.** "Two honks. Never at night." Then at 2:31 AM, two honks. You know before he does.
5. **Diegetic exposition:** radio, logbook and clock replace talking heads. A minimal flat 2D style with one simple
   character design (yellow sou'wester) is cheap to keep consistent and reads on a phone.
6. **Captions are the spine:** 2–4 words, uppercase, the key word coloured; sound effects are captioned too.

## 2. _behindthebuild._: PM / startup explainer

[Reel](https://www.instagram.com/_behindthebuild._/reel/DfwEiPJh7jD/). 230 followers, 18 posts. 817 views, 35 likes
(4.3 %), 1 comment. 73 s. Small account: these are craft notes, not proof that it performs.

**The hook (0–6 s):** "EVERY PRODUCT COMPANY HAS ONE / CHAIR NOBODY CAN EXPLAIN. / IT COSTS ABOUT TWENTY LAKH / A YEAR."
- It's a riddle about a concrete object, plus a number.
- The picture is one symbolic image: five people at a table, one empty chair, an arrow and a tag "ONE CHAIR NOBODY CAN
  EXPLAIN". The tag "~20 LAKH A YEAR" pops in as the words land.

**The body:**
- Parchment background, label tags pop in one at a time in sync with the voice, red key words.
- **No cuts at all** in 73 s. A series header ("THE PM ROADMAP · TECHNICAL OR NOT · 2026") sits at the top throughout.
- Structure: riddle, then "take it away, nothing breaks", then the twist ("ships the wrong thing"), then the answer
  (three questions), then a 3-step plan.

**The CTA:** "COMMENT ROADMAP and I will send the full plan to your DMs", then "FOLLOW BEHIND THE BUILD". This
comment-a-keyword pattern is the explainer version of the vote.

## 3. What both share

1. **Hook = a sentence with a gap**, spoken from frame 0, drawn as 2–4 word captions. Neither reel uses a cold visual
   shock or fast cutting.
2. **A persistent header or HUD** frames every reel as part of a series or system.
3. **One key word per chunk in an accent colour.**
4. **The ending asks for a comment** (a vote or a keyword) and then a follow.
5. **Minimal, consistent flat style:** cheap, readable, recognisable in the feed.

Instagram's own ranking guidance agrees with these ([how Instagram ranks](https://about.instagram.com/blog/announcements/instagram-ranking-explained),
[what kinds of reels are shown less](https://help.instagram.com/1525585517644948/)):
- The predictions that matter most are reshares, watching to the end, likes and visits to the audio page.
- Reels that are mostly text, low-resolution, watermarked or framed with borders are shown less.
- So text cards should be short beats inside motion; the vote card at the very end is the exception.

## 4. Your *The Third Knock* Ep1 against oddhourtales

The Third Knock is nearly the same premise: a lighthouse, rules, a radio, a notebook, choices. The gaps:

| | oddhourtales | The Third Knock ep1 now | Change |
|---|---|---|---|
| Second 0 | Mid-scene, with a sentence about **you** and a consequence | 4 s wide establishing shot of the lighthouse in a storm, with "Nobody wanted the night shift…" | Open on the moment, and give the first words a question or a stake |
| HUD | Night X/7, big clock, ships saved/lost, changing as the story moves | One line, "NIGHT 01 \| 11:42 PM \| BLACKWATER LIGHTHOUSE", once | A persistent game-state HUD on every shot (the `hud` style, repeated and updated) |
| Captions | 2–4 words, uppercase, key word coloured | 2-line blocks | `"style": {"captions": "punch"}` (now built) |
| Rule → payoff | Rule planted in the log, broken at the climax | Rules shown as a notebook card | Make one rule the climax: its violation is the cliffhanger |
| Ending | Vote card held about 16 s, "comment your choice · majority decides", "follow to see the final night" | Choice overlay ("ACCEPT THE SHIFT / NEVER RETURN") over 5 s, no comment or follow ask | A `vote` card held 8–16 s (now built) |
| Arc | "Night 6/7": a visible end | Night 01, no arc shown | Announce the arc in the HUD ("NIGHT 1/7") |

## 5. What changed in the pipeline

- **Rendering:**
  - Punch captions: 2–4 word uppercase chunks, with the `*marked*` word drawn in the accent colour (`overlays.py`,
    `assemble.py`).
  - A `vote` overlay style: the moment, the question, two coloured buttons, the comment line and a follow pill.
- **Writers' room:**
  - The playbook's evidence section is now these global findings (A–I); the India-specific notes are gone.
  - Drafts default to punch captions.
  - The Screenwriter marks one key word per sentence, and opens later episodes on "You chose…".
  - The Editor adds a persistent HUD, and a held vote card for cliffhangers.
  - The linter wants words from second 0 and a vote or end card on the last shot. It no longer demands a cut by 3 s.

## 6. To make this statistically solid

Two reels show craft, not what separates hits from misses. Paste **15–30 more reel URLs** into a text file: several from
each account you rate, including their weaker posts, plus similar series and explainer accounts. Then run:

```bash
python3 infra/research/ig_reels.py --out research/ig --list urls.txt
```

The autopsy then compares the top third against the bottom third by views on every metric, and the hook sheets show
what the winners do in their first 3 seconds.
