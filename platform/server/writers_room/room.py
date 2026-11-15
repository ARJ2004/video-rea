"""Runs the writers' room: story -> reviewed storyboard (the platform's JSON schema).

  Showrunner ─┬─ Hook Doctor ─┐
              └─ Casting ─────┴─ Screenwriter ─ Storyboard Artist ─ Editor & Sound ─ lint/repair ─ Director Review
                                                                                       └── revise (<= max_revisions) ──┘
Every stage's output is kept in storyboard["preproduction"] so you can see at the Script gate why the draft is the way it
is (brief, the five hook candidates and their scores, review scores and notes, cost). The platform ignores that key.

Each agent is one Claude call. All calls share a cached system prefix (playbook + platform rules + language + the story),
so after the first call the story and rules are read from the prompt cache."""
import copy, json, re, time
from concurrent.futures import ThreadPoolExecutor

from . import lint as lint_mod
from . import roles
from .playbook import FORMATS, PLAYBOOK, PLATFORM_RULES, language_rules

MODEL = "claude-opus-5-5"
PRICE = {"in": 4.0, "out": 20.0, "cache_read": 0.20, "cache_write": 5.0}     # $ per 1M tokens (Opus 5.5)
FORMAT = {"aspect": "9:16", "final_resolution": "1080x1920", "fps": 30, "loudness_lufs": -14}


class Room:
    def __init__(self, client, story, title, language="en", target_s=None, ending=None, notes="", progress=None,
                 max_revisions=1, model=MODEL, kind="story"):
        self.client, self.story, self.title, self.lang = client, story, title, language
        self.target_s, self.ending, self.notes, self.model = target_s, ending, notes, model
        self.progress = progress or (lambda msg: None)
        self.max_revisions = max_revisions
        self.log, self.cost = [], 0.0
        brief = (f"\n\nOWNER'S DIRECTIONS: target length {target_s or '45-90'} s; ending: {ending or 'director decides'}."
                 + (f" Notes: {notes}" if notes else ""))
        # identical for every agent -> one cached prefix
        self.kind = kind if kind in FORMATS else "story"
        self.shared = (PLAYBOOK + "\n\n" + PLATFORM_RULES + "\n\n" + language_rules(language)
                       + ("\n\n" + FORMATS[self.kind] + "\nThis format overrides the general playbook where they differ."
                          if FORMATS[self.kind] else "")
                       + f"\n\nTHE STORY (title: {title}):\n<story>\n{story}\n</story>" + brief)

    # ------------------------------------------------------------------ one agent call
    def ask(self, role, task, inputs):
        system = [{"type": "text", "text": self.shared, "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": f"YOUR ROLE: {role.title}.\n{role.craft}"}]
        user = (f"{task}\n\nINPUTS:\n{json.dumps(inputs, ensure_ascii=False, indent=1)}\n\n"
                f"Return ONLY one JSON object, no prose, in this shape:\n{role.returns}")
        t0 = time.time()
        with self.client.beta.messages.stream(
                model=self.model, max_tokens=64000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                thinking={"type": "adaptive"}, output_config={"effort": role.effort},
                system=system, messages=[{"role": "user", "content": user}]) as stream:
            resp = stream.get_final_message()
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{role.title}: Claude declined this story.")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"{role.title}: reply was cut off (max_tokens).")
        self._account(role, resp, time.time() - t0)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return parse_json(text, role.title)

    def _account(self, role, resp, sec):
        u = resp.usage
        get = lambda k: getattr(u, k, 0) or 0
        usd = (get("input_tokens") * PRICE["in"] + get("output_tokens") * PRICE["out"]
               + get("cache_read_input_tokens") * PRICE["cache_read"]
               + get("cache_creation_input_tokens") * PRICE["cache_write"]) / 1e6
        self.cost += usd
        self.log.append({"role": role.key, "sec": round(sec, 1), "usd": round(usd, 4), "in": get("input_tokens"),
                         "out": get("output_tokens"), "cache_read": get("cache_read_input_tokens")})

    # ------------------------------------------------------------------ the stages
    def run(self):
        say = self.progress
        say("Showrunner: reading the story, choosing the through-line and beats")
        brief = self.ask(roles.SHOWRUNNER, "Write the creative brief for this episode.", {"title": self.title})

        say("Hook Doctor and Casting & Design: working in parallel")
        with ThreadPoolExecutor(2) as pool:
            fh = pool.submit(self.ask, roles.HOOK_DOCTOR, "Write and score five cold opens; pick the winner.", {"brief": brief})
            fc = pool.submit(self.ask, roles.CASTING, "Design the cast, locations and voices.",
                             {"cast": brief.get("cast"), "locations": brief.get("locations"), "visual": brief.get("visual")})
            hooks, cast = fh.result(), fc.result()
        hook = pick_hook(hooks)
        say(f"Hook locked: \"{hook.get('spoken_line', '')}\" ({hook.get('archetype', '')}, {hook.get('total', '?')}/50)")

        say("Screenwriter: writing narration and dialogue clip by clip")
        script = self.ask(roles.SCREENWRITER, "Write every spoken line. Clip 01 opens with the locked hook line word for word.",
                          {"brief": brief, "hook": hook, "hook_notes": hooks.get("notes_for_screenwriter"),
                           "speakers": speakers(brief, cast, self.lang)})

        sb = self.skeleton(brief, cast, script)
        say("Storyboard Artist: breaking every clip into shots")
        sb = self.merge_clips(sb, self.ask(
            roles.STORYBOARD, "Fill in the shots of every clip. Shot 01-A is the locked hook frame.",
            {"storyboard": sb, "brief_beats": brief.get("beats"), "camera_grammar": (brief.get("visual") or {}).get("camera_grammar"),
             "hook": hook, "notes_from_screenwriter": script.get("notes_for_storyboard"), "risks": brief.get("risks")}))

        say("Editor & Sound Designer: ambience, sound hits, on-screen text, end card")
        edit = self.ask(roles.EDITOR, "Add the sound and overlay pass.",
                        {"storyboard": strip_for_editor(sb), "hook": hook, "sound_concept": brief.get("sound")})
        sb = apply_edit(sb, edit)
        sb = self.repair(sb)

        reviews = []
        for rnd in range(self.max_revisions + 1):
            report = lint_mod.lint(sb)
            say(f"Director Review (round {rnd + 1}): scoring hook, pacing, clarity, feasibility")
            review = self.ask(roles.REVIEWER, "Review this storyboard before any GPU time is spent.",
                              {"brief": brief, "hook": hook, "storyboard": sb, "lint": report})
            reviews.append(review)
            say(f"Director Review: {review.get('verdict', '?')} (overall {review.get('overall', '?')})")
            if review.get("verdict") == "approve" or rnd == self.max_revisions:
                break
            say(f"Revising: {len(review.get('notes', []))} notes from the director")
            sb = self.merge_clips(sb, self.ask(
                roles.STORYBOARD, "Apply every note from the director's review. You may rewrite lines (keep the hook line), "
                                  "shots, sfx and overlays. Return the complete storyboard.",
                {"storyboard": sb, "review": review, "lint": report}))
            sb = self.repair(sb)

        sb["preproduction"] = {"agent": "writers_room", "brief": brief, "hooks": hooks, "hook": hook,
                               "design_notes": cast.get("design_notes"), "edit_notes": edit.get("edit_notes"),
                               "reviews": reviews, "lint": lint_mod.lint(sb), "calls": self.log, "cost_usd": round(self.cost, 3)}
        say(f"Writers' room done: {len(sb['clips'])} clips, {sum(len(c['shots']) for c in sb['clips'])} shots, "
            f"Claude cost ${self.cost:.2f}")
        return sb

    def repair(self, sb, tries=2):
        """Fix hard lint errors (things the platform would reject) with the Storyboard Artist."""
        for _ in range(tries):
            errs = lint_mod.lint(sb)["errors"]
            if not errs:
                return sb
            self.progress(f"Fixing {len(errs)} structural problems")
            sb = self.merge_clips(sb, self.ask(roles.STORYBOARD, "Fix ONLY these errors; change nothing else. Return the "
                                                                "complete storyboard.", {"storyboard": sb, "errors": errs}))
        errs = lint_mod.lint(sb)["errors"]
        if errs:
            raise ValueError("draft still has errors after repair: " + "; ".join(errs[:5]))
        return sb

    # ------------------------------------------------------------------ assembling the JSON
    def skeleton(self, brief, cast, script):
        vis = brief.get("visual") or {}
        sb = {"series": brief.get("series") or self.title, "episode": brief.get("episode", 1), "title": self.title,
              "language": self.lang, "source": "Drafted by the writers' room (Claude) for review",
              "status": "draft-for-review",
              "format": {**FORMAT, "kind": self.kind, "target_duration_s": brief.get("target_duration_s") or self.target_s},
              "style": {"look": vis.get("look", ""), "look_scene": vis.get("look_scene", ""), "negative": vis.get("negative", ""),
                        "captions": "punch", "accent": "amber"},
              "characters": cast.get("characters", {}), "sets": cast.get("sets", {}), "clips": []}
        if self.lang == "en":
            sb["voices"] = cast.get("voices", {})
        per_clip = ((brief.get("sound") or {}).get("per_clip")) or {}
        for c in script.get("clips", []):
            snd = per_clip.get(c["id"], {})
            clip = {"id": c["id"], "title": c.get("title", ""), "lines": [clean_line(l) for l in c.get("lines", [])], "shots": []}
            if snd.get("ambience") in ("storm", "rain", "room"):
                clip["ambience"] = snd["ambience"]
            if snd.get("music") == "drone":
                clip["music"] = "drone"
            sb["clips"].append(clip)
        return sb

    def merge_clips(self, sb, out):
        """The Storyboard Artist returns the full storyboard; take its clips (shots, line fixes) into ours."""
        new = copy.deepcopy(sb)
        got = out.get("clips") if isinstance(out, dict) else None
        if not got:
            raise RuntimeError("Storyboard Artist returned no clips")
        new["clips"] = []
        for c in got:
            old = next((o for o in sb["clips"] if o["id"] == c.get("id")), {})
            merged = {**old, **{k: v for k, v in c.items() if v not in (None, "")}}
            merged["lines"] = [clean_line(l) for l in merged.get("lines", [])]
            prev = {x["id"]: x for x in old.get("shots", [])}
            for sh in merged.get("shots", []):          # the editor's pass survives a revision that leaves it out
                for k in ("sfx", "overlays", "end_card"):
                    if k not in sh and k in prev.get(sh.get("id"), {}):
                        sh[k] = prev[sh["id"]][k]
            new["clips"].append(merged)
        for k in ("characters", "sets", "voices", "style"):        # allowed to refine designs, never to drop them
            if isinstance(out.get(k), dict) and out[k]:
                new[k] = {**sb.get(k, {}), **out[k]}
        return new


# ---------------------------------------------------------------------- helpers
def parse_json(text, who):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"{who}: no JSON in the reply")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{who}: reply is not valid JSON ({e})")


def pick_hook(hooks):
    cands = hooks.get("candidates") or []
    if not cands:
        raise RuntimeError("Hook Doctor returned no candidates")
    w = hooks.get("winner")
    if isinstance(w, int) and 0 <= w < len(cands):
        return cands[w]
    return max(cands, key=lambda c: (c.get("total") or sum((c.get("scores") or {}).values()), (c.get("scores") or {}).get("scroll_stop", 0)))


def speakers(brief, cast, lang):
    if lang == "hi":
        return ["dadi (narrator / storyteller)", "tara"]
    return sorted((cast.get("voices") or {}).keys()) or [c["name"] for c in brief.get("cast", []) if c.get("speaks")]


def clean_line(l):
    keep = {k: l[k] for k in ("id", "speaker", "emotion", "tts", "caption", "fx") if l.get(k) not in (None, "")}
    if keep.get("fx") not in (None, "radio", "stranger"):
        keep.pop("fx")
    return keep


def strip_for_editor(sb):
    """The editor needs timing, framing and words, not the full prompts."""
    return {"clips": [{"id": c["id"], "title": c.get("title"), "lines": c.get("lines"),
                       "shots": [{k: s.get(k) for k in ("id", "tech", "dur_s", "framing", "beat", "keyframe_prompt", "vo")
                                  if s.get(k) is not None} for s in c["shots"]]} for c in sb["clips"]],
            "series": sb.get("series"), "episode": sb.get("episode")}


def apply_edit(sb, edit):
    """Merge the editor's patch, keeping only values the platform can render."""
    sb = copy.deepcopy(sb)
    patch = (edit or {}).get("clips") or {}
    last_shot = sb["clips"][-1]["shots"][-1]["id"] if sb["clips"] and sb["clips"][-1]["shots"] else None
    for c in sb["clips"]:
        p = patch.get(c["id"]) or {}
        if p.get("ambience") in ("storm", "rain", "room"):
            c["ambience"] = p["ambience"]
        if p.get("music") == "drone":
            c["music"] = "drone"
        for s in c["shots"]:
            sp = (p.get("shots") or {}).get(s["id"]) or {}
            dur = lint_mod.shot_seconds(s) or 99
            sfx = [e for e in sp.get("sfx", []) if e.get("type") in lint_mod.SFX and float(e.get("at", 0)) <= dur]
            ovs = [o for o in sp.get("overlays", []) if o.get("text") and o.get("style", "label") in lint_mod.OVERLAY_STYLES]
            if sfx:
                s["sfx"] = sfx
            if ovs:
                s["overlays"] = ovs
            if sp.get("end_card") and s["id"] == last_shot:
                s["end_card"] = {"dur_s": float(sp["end_card"].get("dur_s", 2)), "text": str(sp["end_card"].get("text", ""))}
    return sb


def draft(api_key, story, title, progress=None, **opts):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key, timeout=900.0, max_retries=2)
    return Room(client, story, title, progress=progress, **opts).run()
