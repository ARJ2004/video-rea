"""Draft a storyboard (the platform's JSON schema) from a pasted story with Claude. Needs an Anthropic API key in Settings.
The draft always lands at the Script gate for you to edit and approve; nothing is generated before that."""
import json, re
from pathlib import Path
import anthropic

MODEL = "claude-opus-5-5"
EXAMPLE = Path(__file__).resolve().parent / "storyboard_example.json"

SYSTEM = """You turn a story into a production storyboard for a vertical (9:16) animated short for children, voiced in Hindi.
Return ONLY one JSON object, no prose, with exactly this shape (see the example for field meanings):
{ "series", "episode", "format": {"aspect":"9:16","final_resolution":"1080x1920","fps":30,"loudness_lufs":-14},
  "style": {"look", "negative"},
  "characters": {name: {"description"}}, "sets": {name: {"description"}},
  "clips": [ {"id","title","lines":[{"id","speaker","emotion","caption","tts"}],
              "shots":[{"id","tech","dur_s","refs","keyframe_prompt","motion_prompt", ...}] } ] }
Rules:
- 4-6 clips, 15-30 s each, 2-5 shots per clip. Shot ids "<clip>-A", "<clip>-B"...; line ids "<clip>-L1"...
- tech is one of: I2V (still keyframe brought to life, needs dur_s), TALK (a character speaks a line on camera: give "line"),
  FLF (morph from a first frame to a last frame: give "first_frame_prompt" or "first_frame": "last frame of <shot id>",
  plus "last_frame_prompt"), I2V+COMP (I2V with a text "overlay": {"text"}).
- Close-ups of a scene already established by a wide shot use "cover": {"base": "<wide shot id>", "crop": "mcu"|"two"|"object"|null,
  "subject": "<character or object>"} so the room, seating and screen positions stay identical.
- Every shot lists in "refs" the characters and sets visible in it (names from characters/sets).
- Speakers must be "tara" (8-year-old girl) or "dadi" (her grandmother, the storyteller); narration is spoken by dadi.
  Other characters can appear but do not speak.
- "tts" is natural spoken Hindi in Devanagari; "caption" is the same line in Hinglish (Latin script).
- Keep devotional and cultural content accurate and respectful; put primary sources in a top-level "sources" list.
- The last shot of the last clip may carry "end_card": {"dur_s": 2, "text": "<series> · Episode <n>"}."""


def draft(api_key, story, title):
    client = anthropic.Anthropic(api_key=api_key, timeout=600.0, max_retries=2)
    example = EXAMPLE.read_text() if EXAMPLE.exists() else ""
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high"},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Example storyboard (shape and style reference):\n{example}\n\n"
                                               f"Title: {title}\n\nStory:\n{story}\n\nWrite the storyboard JSON."}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined to draft this story.")
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("No JSON in Claude's reply.")
    sb = json.loads(m.group(0))
    validate(sb)
    return sb


def validate(sb):
    """Minimal structural checks shared by drafted and pasted storyboards. Raises ValueError with a readable message."""
    if not isinstance(sb, dict) or not sb.get("clips"):
        raise ValueError("storyboard needs a non-empty 'clips' list")
    names = set(sb.get("characters", {})) | set(sb.get("sets", {}))
    ids = set()
    for c in sb["clips"]:
        lines = {l["id"] for l in c.get("lines", [])}
        for l in c.get("lines", []):
            for k in ("id", "speaker", "caption", "tts"):
                if k not in l:
                    raise ValueError(f"line {l.get('id')} missing '{k}'")
        for s in c.get("shots", []):
            if s.get("id") in ids:
                raise ValueError(f"duplicate shot id {s.get('id')}")
            ids.add(s.get("id"))
            if s.get("tech") not in ("I2V", "TALK", "FLF", "I2V+COMP"):
                raise ValueError(f"shot {s.get('id')}: tech must be I2V, TALK, FLF or I2V+COMP")
            if s["tech"] == "TALK" and s.get("line") not in lines:
                raise ValueError(f"shot {s['id']}: TALK needs a 'line' from its clip")
            for r in s.get("refs", []):
                if r not in names:
                    raise ValueError(f"shot {s['id']}: unknown ref '{r}' (not in characters/sets)")
            base = (s.get("cover") or {}).get("base")
            if base and base not in ids:
                raise ValueError(f"shot {s['id']}: cover.base '{base}' must be an earlier shot")
    return True
