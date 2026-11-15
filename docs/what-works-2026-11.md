# What actually works in AI story Shorts: scan of 2026-11-15

**Method:**
- Logged-out Instagram exposes only follower and post counts, and scraping with a logged-in account breaks Instagram's
  terms. So this scan uses the YouTube Shorts versions of the same formats: Indian AI-story pages cross-post, and view
  counts are public there.
- 16 discovery searches (sorted by views) found the channels. Up to the last 120 Shorts of each were then compared
  against **that channel's own median**: "x45" means 45 times the channel's typical Short. This controls for channel size.
- 499 Shorts across 8 channels.
- I looked at the top 6 and 6 typical thumbnails of each channel; for Shorts the thumbnail is usually the hook frame.
- Data: [`infra/research/data/yt-shorts-scan-2026-11-15.json`](../infra/research/data/yt-shorts-scan-2026-11-15.json).
  Rerun with [`infra/research/yt_scan.py`](../infra/research/yt_scan.py).

**Not measured yet:** cuts, pacing and sound. Video files can't be downloaded from a cloud machine (YouTube asks it to
sign in), so those need a download on your own machine (see the end).

## The channels

| Channel | Subs | Median Short | Best Short | Format |
|---|---|---|---|---|
| Bandar Apna Dost | 4.0M | 5.7M | 144M (x26) | Recurring AI cast (Hulk-like soldier Halku, monkey soldier, Tuntun mausi): patriotic or family melodrama and slapstick |
| Horror Skunx | 9.9M | 4.8M | 197M (x41) | CGI creature horror in real locations (Siren Head, clown faces, a train-spider) |
| Toon Stories | 1.6M | 222K | 20M (x90) | Photoreal AI: a grandmother hand-builds an impossible vehicle or object for a young woman |
| Payal AI Story | 104K | 46K | 21M (x457) | Illustrated 90s Hindi stories: night train journeys, storms, danger, kids saving the day |
| basit sonde | 28K | 39K | 7.4M (x190) | Illustrated 90s nostalgia: village kids, danger at the river or jungle, mischief with grandma |
| The Blue Horizon AI | 112K | 10K | 8.5M (x829) | Live-action-style AI fan films of famous IP (One Piece, Baki, footballers) |
| Cosmic Moksh, Ghantee Media, MythoAI | 13 – 66K | 1–5K | 0.2M | AI mythology (Shiva, Ganga, Devi): **no breakout found** |

The pure AI-mythology channels found here are small. The Indian AI formats that break out are **family emotion and
everyday 90s nostalgia with sudden danger**. Srishti's Tara-and-Dadi framing is close to that winning formula (compare
Toon Stories' grandmother and girl). The Third Knock's night-and-storm danger is close to Payal's night-train hits.

## Findings (outlier vs typical, same channel)

1. **The hook frame shows the threat and someone reacting to it.**
   - Payal's 21M hit: a ghost child stands in the storm outside the train window, lightning behind, and the family
     inside points and gasps.
   - basit sonde's 7.4M hit: a crocodile glides toward children swimming. Another: a lion stands behind children in the
     jungle.
   - Their median videos are calm scenes with no visible stake: a bus on a road, a ship at the dock, a smiling child's
     portrait.
2. **Readable beats dark.**
   - Horror Skunx's outliers are bright, close, uncanny faces filling the frame and staring at you.
   - Its median videos are dark silhouettes against a purple night sky.
   - This applies directly to The Third Knock's dark navy palette: light the first frame, and save the darkness for
     later shots.
3. **One formula, repeated, with a fixed recurring cast.**
   - Toon Stories' top 6 are all one idea, the same two women in the same clothes, photoreal: "grandmother's hard work
     for the girl's smile".
   - Its median videos are where it drifted: a topiary dragon, a giant brinjal, a 3D-cartoon monkey, golden eggs.
4. **High-arousal family emotion beats gags.**
   - Bandar Apna Dost's outliers (50–90M) are a mother in hospital, a soldier's sacrifice, grief ("Maa").
   - Its comedy food and airplane gags sit at the median, around 5M.
5. **Nostalgic Indian everyday settings plus sudden danger.**
   - A 90s night train, a village river, a flooded school, a lantern.
   - This is the strongest Hindi AI-story pattern in the data.
6. **Titles: an unfinished sentence and a fear emoji.**
   - Titles with 😱/😳 reached 5× or more of the channel median 33% of the time.
   - Titles with "…" did so 30% of the time; all other titles, 19%.
   - Example: "When the Train Suddenly Stopped in the Middle of the Night… 😱" (21M).
7. **Two-part cliffhangers.**
   - Part 2 beat Part 1 in 5 of 8 matched pairs, sometimes by 5–8×.
   - Payal's Part 2 got 21M where its Part 1 got 2.5M; Blue Horizon's got 8.5M against 1.6M.
   - Part 1 ends at maximum danger and sends people to Part 2.
8. **Weaker signals (small samples):**
   - basit sonde's thumbnails with big Hindi title text all sit at the median.
   - A single-character portrait does worse than a scene with a situation in it.

**Caveats:**
- About 500 Shorts across 8 channels is enough to see patterns, but not to prove causes.
- Thumbnails stand in for first frames.
- Treat findings 6–8 as directional.

## What changed in the pipeline because of this

- `platform/server/writers_room/playbook.py` has a **MEASURED EVIDENCE** section (rules A–G) that every agent reads,
  and it overrides the generic rules where they conflict.
- The Hook Doctor now:
  - scores scroll-stop against it: the threat plus a reaction in one frame, lit and readable at thumbnail size;
  - caps calm establishing shots, dark silhouettes and lone portraits at 4/10;
  - proposes a posting title in the unfinished-sentence form, which is shown at the Script gate.

## Next: measure cuts and sound (needs your machine)

YouTube serves video to home connections. On your laptop:

```bash
pip install yt-dlp
```

```bash
yt-dlp -o "reels/%(channel)s_%(id)s.%(ext)s" -f "best[height<=1280][ext=mp4]" $(python3 -c "import json;d=json.load(open('infra/research/data/yt-shorts-scan-2026-11-15.json'));print(' '.join('https://www.youtube.com/shorts/'+s['id'] for c in d['channels'] for s in sorted(c['shorts'],key=lambda s:-s['x_median'])[:4]+sorted(c['shorts'],key=lambda s:abs(s['x_median']-1))[:4]))")
```

```bash
python3 infra/research/reel_autopsy.py reels --out reels/autopsy
```

Commit `reels/autopsy/autopsy.json` (not the videos). Then the autopsy can compare outliers with typical Shorts on
first-cut time, cut cadence, the opening sound hit, loudness and loop endings, and those numbers go into the playbook
and linter thresholds.

Sources for the channel discovery:
- [Business Standard on Bandar Apna Dost](https://www.business-standard.com/technology/tech-news/india-youtube-bandar-apna-dost-channel-global-ai-video-charts-slop-content-125123100396_1.html)
- [Medium: the 44 most-watched AI videos on YouTube](https://medium.com/@manqa06/i-ranked-the-44-most-watched-ai-videos-on-youtube-4eca0f9b187f)
- [MythoAI](https://www.youtube.com/@vidyoai)
- [Vedic Tribe Studios](https://www.youtube.com/@vedictribe/shorts)
