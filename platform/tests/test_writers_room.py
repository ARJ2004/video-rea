"""Offline test of the writers' room: a stub Claude client returns canned JSON per role, so the orchestration, merging,
editor patch, lint/repair loop, review/revise loop and the final schema check run without an API key.
Run: python3 platform/tests/test_writers_room.py"""
import json, sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from writers_room import Room, lint  # noqa: E402
from writers_room.roles import ALL  # noqa: E402

BRIEF = {"logline": "A keeper hears a knock from outside a locked lighthouse at sea.", "emotional_core": "dread",
         "central_question": "who is knocking?", "ending": "cliffhanger", "target_duration_s": 30, "series": "The Knock", "episode": 1,
         "beats": [{"id": "B1", "name": "HOOK", "start_s": 0, "end_s": 3}], "clips_plan": [{"id": "01"}, {"id": "02"}],
         "visual": {"look": "flat 2D illustrated, navy and amber", "look_scene": "flat 2D background art", "negative": "text, watermark"},
         "sound": {"per_clip": {"01": {"ambience": "storm", "music": "drone"}, "02": {"ambience": "bogus"}}},
         "cast": [{"name": "elias", "kind": "character", "speaks": True}, {"name": "narrator", "kind": "narrator", "speaks": True}],
         "locations": [{"name": "tower"}]}
HOOKS = {"candidates": [{"archetype": "question", "spoken_line": "Who knocks on a door in the middle of the sea?", "total": 38},
                        {"archetype": "forbidden rule", "spoken_line": "Rule one: never open the door after midnight.",
                         "on_screen_text": "NEVER OPEN IT", "first_frame": "a heavy door, rain on glass", "total": 44}],
         "winner": 1, "notes_for_screenwriter": "promise the rules"}
CAST = {"characters": {"elias": {"description": "young man, yellow raincoat"}},
        "sets": {"tower": {"description": "lighthouse control room, no people"}},
        "voices": {"narrator": {"description": "Will's voice is calm."}, "elias": {"description": "Will's voice is nervous."}}}
SCRIPT = {"clips": [
    {"id": "01", "title": "Rule one", "lines": [{"id": "01-L1", "speaker": "narrator", "emotion": "hushed",
                                                "tts": "Rule one: never open the door after midnight.", "caption": "Rule one: never open the door after midnight.", "on_camera": False}]},
    {"id": "02", "title": "The knock", "lines": [{"id": "02-L1", "speaker": "elias", "emotion": "afraid",
                                                  "tts": "Who's there?", "caption": "Who's there?", "on_camera": True}]}]}


def shots(bad):
    a = {"id": "01-A", "tech": "I2V", "dur_s": 2.5, "refs": ["tower"], "framing": "insert", "keyframe_prompt": "a heavy door",
         "motion_prompt": "rain streaks, slow push-in", "vo": "Rule one:"}
    b = {"id": "01-B", "tech": "I2V", "dur_s": 3, "refs": ["elias", "tower"] + (["ghost"] if bad else []), "framing": "wide",
         "keyframe_prompt": "Elias at the desk", "motion_prompt": "Elias looks up", "vo": "never open the door after midnight."}
    c = {"id": "02-A", "tech": "TALK", "line": "02-L1", "refs": ["elias", "tower"], "keyframe_prompt": "Elias close-up",
         "motion_prompt": "", "cover": {"base": "01-B", "crop": "mcu", "subject": "elias"}}
    sb = {"clips": [{"id": "01", "shots": [a, b], "lines": SCRIPT["clips"][0]["lines"]},
                    {"id": "02", "shots": [c], "lines": SCRIPT["clips"][1]["lines"]}]}
    return sb


EDIT = {"clips": {"01": {"music": "drone", "shots": {
    "01-A": {"sfx": [{"type": "impact", "at": 0}, {"type": "laser", "at": 0.5}, {"type": "knock", "at": 9}],
             "overlays": [{"text": "NEVER OPEN IT", "style": "title", "at": 0.2}, {"text": "x", "style": "comic"}]}}},
    "02": {"shots": {"02-A": {"end_card": {"dur_s": 2, "text": "The Knock - Episode 1"}}}}}, "edit_notes": "hit on 01-A"}


class Stub:
    """Plays the roles in order; the first storyboard pass contains an unknown ref so the repair loop must run."""
    def __init__(self):
        self.calls = []
        self.storyboard_passes = 0
        self.reviews = 0
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **kw):
        role = kw["system"][1]["text"].split("\n")[0]
        self.calls.append(role)
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
        if "Showrunner" in role: out = BRIEF
        elif "Hook Doctor" in role: out = HOOKS
        elif "Casting" in role: out = CAST
        elif "Screenwriter" in role: out = SCRIPT
        elif "Storyboard" in role:
            self.storyboard_passes += 1
            out = shots(bad=self.storyboard_passes == 1)
        elif "Editor" in role: out = EDIT
        elif "Director Review" in role:
            self.reviews += 1
            out = {"scores": {"hook": 8 if self.reviews > 1 else 6}, "overall": 7.5, "verdict": "approve" if self.reviews > 1 else "revise",
                   "notes": [] if self.reviews > 1 else [{"for": "storyboard", "where": "01-B", "problem": "flat", "fix": "low angle"}]}
        else: raise AssertionError(role)
        msg = NS(stop_reason="end_turn", content=[NS(type="text", text="Here:\n" + json.dumps(out))],
                 usage=NS(input_tokens=1000, output_tokens=500, cache_read_input_tokens=3000, cache_creation_input_tokens=0))
        return Ctx(msg)


class Ctx:
    def __init__(self, msg): self.msg = msg
    def __enter__(self): return NS(get_final_message=lambda: self.msg)
    def __exit__(self, *a): return False


def main():
    stub = Stub()
    log = []
    sb = Room(stub, "A lighthouse story...", "The Knock", language="en", target_s=30, progress=log.append).run()

    # the platform's own validator accepts it
    import importlib.util
    spec = importlib.util.spec_from_file_location("drafting_v", Path(__file__).resolve().parents[1] / "server" / "drafting.py")
    src = (Path(spec.origin).read_text().split("def validate(sb):", 1)[1]).split("\nJUDGE", 1)[0]
    ns = {}; exec("def validate(sb):" + src, ns); ns["validate"](sb)

    r = lint(sb)
    assert not r["errors"], r["errors"]
    c1 = sb["clips"][0]
    assert c1["ambience"] == "storm" and c1["music"] == "drone"
    assert "ambience" not in sb["clips"][1]                                   # 'bogus' dropped
    a = c1["shots"][0]
    assert [e["type"] for e in a["sfx"]] == ["impact"], a["sfx"]             # unknown type and out-of-shot time dropped
    assert [o["style"] for o in a["overlays"]] == ["title"]
    assert sb["clips"][1]["shots"][-1]["end_card"]["text"].startswith("The Knock")
    assert "on_camera" not in sb["clips"][0]["lines"][0]
    pp = sb["preproduction"]
    assert pp["hook"]["archetype"] == "forbidden rule" and len(pp["reviews"]) == 2 and pp["cost_usd"] > 0
    assert stub.storyboard_passes == 3, stub.storyboard_passes                # draft, repair of the bad ref, one revision
    assert sb["voices"]["narrator"]["description"]
    order = [c.split(".")[0] for c in stub.calls]
    assert order[0].startswith("YOUR ROLE: Showrunner") and "Review" in order[-1]
    print("ok:", len(stub.calls), "agent calls;", " | ".join(log[-3:]))


if __name__ == "__main__":
    main()
