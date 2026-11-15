"""Shared knowledge for the writers' room: what hook-driven short-form AI video does (the research playbook) and what this
platform can actually render (the hard rules). Every agent gets PLAYBOOK + PLATFORM_RULES; each role adds its own brief.

The playbook is reverse-engineered from high-retention AI story pages on Instagram Reels / Shorts (mythology, horror,
micro-drama, "what happened next" history) and the multi-agent film papers (FilmAgent, MovieAgent). Sources are listed in
docs/writers-room.md. Edit the text here, not in the role prompts, so every agent stays in agreement."""

PLAYBOOK = """HOW HIGH-RETENTION AI SHORTS ARE BUILT (the house playbook; follow it unless the brief says otherwise)

1. The first 1.5-3 seconds decide everything. Open IN THE MIDDLE of the most arresting moment (cold open), never on a
   title, a slow establishing shot or "once upon a time". The first frame alone must stop the scroll with the sound off:
   one clear subject, high contrast, something wrong / impossible / beautiful / at stake.
2. Hook = three layers that land together in second 0-2:
   - VISUAL: the hook frame (a striking, readable image - not a wide, busy landscape).
   - SPOKEN: one line, 6-12 words, that opens a question the viewer needs answered (curiosity gap), states stakes, or
     contradicts an expectation. No greetings, no throat-clearing.
   - TEXT: 2-6 words of on-screen text (drawn as an overlay) that reinforce, not repeat, the spoken line - for muted viewers.
   Hook archetypes that work: in-media-res danger; forbidden rule / warning; impossible image; shocking fact or number;
   direct question to the viewer; "nobody tells you..." secret; flash-forward to the climax then rewind; POV.
3. Promise early, pay late. Within 3-8 s the viewer must know what the story is about and what is at stake. Then keep
   opening small loops (new questions) before closing old ones. Never resolve the main question before the last 15%.
4. Cut cadence: a new image every 1.5-3 s on average (vary it: quick cuts for tension, one longer held shot for awe or
   dread). Change shot size between consecutive shots (wide -> close -> insert -> medium). A pattern interrupt (sound hit,
   hard cut to black, sudden close-up, silence) every 8-12 s resets attention.
5. Beat sheet for a 45-90 s episode: HOOK (0-3 s) -> PROMISE/SETUP (3-10 s) -> ESCALATION 1 -> ESCALATION 2 -> TURN /
   REVEAL (around 70-80 %) -> PAYOFF or CLIFFHANGER (last 5 s). Series episodes end on an unresolved micro-cliffhanger;
   standalone pieces end on an image that loops cleanly back to the first frame (rewatch value).
6. Sound is half the hook: a hit (impact, knock, thunder, silence-then-sound) on the first cut, an ambience bed under every
   clip, a drone or music bed under tension. Narration is close, intimate, unhurried, with pauses before reveals.
7. Captions are part of the picture: short chunks timed to the voice. Overlays carry names, dates, rules, numbers - never
   rely on the video model to draw text.
8. Consistency sells "series": one locked look, one locked design per character (same outfit every shot), recurring
   locations, a recurring audio signature. Describe characters identically every time.
9. Write for what AI video does well: slow camera moves, atmospheric motion (rain, fog, fire, light, water, cloth),
   simple single actions, faces with one emotion, silhouettes, reveals by light. Avoid what it does badly: fights, hands
   manipulating small objects, many people interacting, fast complex choreography, readable text in the image, one
   creature changing into another.
10. Emotion over information. Every clip must make the viewer FEEL one thing (dread, awe, warmth, injustice, curiosity).
    Specific, concrete, sensory details beat summaries. Cut any line that only explains."""


PLATFORM_RULES = """WHAT THIS PLATFORM CAN RENDER (hard rules - output that breaks them is rejected)

Format: vertical 9:16, 1080x1920, 30 fps, -14 LUFS. Episode = clips (each 8-30 s) of shots; shots are 2-6 s.

Shot techniques ("tech"):
- I2V: a still keyframe brought to life by the video model. Needs "dur_s", "keyframe_prompt" (what the frame shows) and
  "motion_prompt" (gentle motion + camera move).
- TALK: a character speaks one line on camera, lip-synced. Needs "line" (a line id from the same clip) and a
  "keyframe_prompt" framing that character's face (medium close-up). Use for emotional on-camera lines, not narration.
- FLF: a morph from a first frame to a last frame. Give "first_frame_prompt" (or "first_frame": "last frame of <shot id>")
  and "last_frame_prompt" (also used as keyframe_prompt). Good for transformations of light/scenery, not of creatures.
- I2V+COMP: I2V with a text "overlay": {"text"} label.
- Optional "animate": "still" = no video model, a slow push-in on the keyframe (use for shots the video model cannot do,
  e.g. a starfield, a page, a symbol).
- Close-ups inside a scene already set up by a wide shot use "cover": {"base": "<earlier wide shot id>", "crop":
  "mcu" | "two" | "object" | null, "subject": "<character or object>"} so the room and positions stay identical.

Every shot lists in "refs" the characters and sets visible in it (keys of "characters" / "sets").
keyframe_prompt / motion_prompt: concrete, visual, present tense, no character backstory, no text/letters in the image,
one clearly named subject per action, gentle actions, camera move stated ("slow push-in", "slow pan left", "static").
Characters described once in "characters" (fixed outfit, age, hair, colours); prompts refer to them by name.

Lines: {"id": "<clip>-L<n>", "speaker", "emotion", "tts" (exactly what is spoken), "caption" (on-screen caption text)}.
Optional "fx": "radio" | "stranger". Narrated lines: give the shots of that clip either "vo_lines": [line ids] or "vo"
(an exact consecutive part of a line's tts spoken over that shot) + "vo_caption".

Sound (synthesized on the server - only these values exist):
- clip "ambience": "storm" | "rain" | "room";  clip "music": "drone"
- shot "sfx": [{"type": knock|static|thunder|heartbeat|impact|creak|silence, "at": seconds, optional "dur", "count", "gap"}]
Overlays (drawn on top, exact spelling): shot "overlays": [{"text", "style": hud|notebook|title|choice|label, "at", "until"}]
End card: the last shot of the last clip may carry "end_card": {"dur_s": 2, "text": "<series> - Episode <n>"}.

Ids: clips "01", "02", ...; shots "<clip>-A", "<clip>-B", ...; lines "<clip>-L1", ... (unique)."""


def language_rules(lang):
    """Voice constraints differ by language: Hindi uses two locked cloned voices, English uses described Parler voices."""
    if lang == "hi":
        return ("LANGUAGE: Hindi. Speakers must be \"tara\" (8-year-old girl) or \"dadi\" (her grandmother, the storyteller) - "
                "the only two locked voices; narration is spoken by dadi; other characters appear but do not speak. "
                "\"tts\" is natural spoken Hindi in Devanagari; \"caption\" is the same line in Hinglish (Latin script). "
                "Keep devotional and cultural content accurate and respectful; list primary sources in a top-level \"sources\".")
    return ("LANGUAGE: English. Every speaker needs a top-level \"voices\": {speaker: {\"description\"}} entry - a Parler-TTS "
            "voice description, e.g. \"Will's voice is a young adult man of about 25, natural, warm and intimate, speaking at a "
            "calm, measured pace with clear pauses between sentences. The recording is very clear and close-up, with almost "
            "no background noise.\" Use the named speakers Will (young man), Bruce (deep mature man), Laura or Jenna (women) "
            "at the start of the description. A narrator is a speaker too. \"caption\" is the same text as \"tts\".")
