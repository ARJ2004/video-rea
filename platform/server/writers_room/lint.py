"""Deterministic checks on a storyboard, run between agents. Errors must be fixed before the draft reaches you (the
platform would reject or mis-render them); warnings go to the Director Review as evidence.
Pacing numbers follow the playbook: hook shot 2-3.5 s, average shot 1.5-3 s, voice covers 70-85 % of a clip."""
import re

SFX = ("knock", "static", "thunder", "heartbeat", "impact", "creak", "silence")
OVERLAY_STYLES = ("hud", "notebook", "title", "choice", "label")
TECHS = ("I2V", "TALK", "FLF", "I2V+COMP")
WPS = {"en": 2.5, "hi": 2.2}          # comfortable spoken words per second (upper bound before it sounds rushed)
HARD_FOR_MODELS = re.compile(r"\b(fight|fighting|punch|sword ?fight|crowd|typing|writes?|writing|reads? the|letters?|"
                             r"sign that says|text reading|morphs? into|turns into|transforms? into)\b", re.I)


def shot_seconds(s):
    return float(s.get("dur_s") or (3.0 if s.get("tech") == "TALK" else 0) or 0)


def lint(sb):
    """-> {"errors": [...], "warnings": [...], "stats": {...}}"""
    errors, warns = [], []
    lang = sb.get("language", "hi")
    chars, sets = set(sb.get("characters", {})), set(sb.get("sets", {}))
    names = chars | sets
    clips = sb.get("clips") or []
    if not clips:
        return {"errors": ["storyboard has no clips"], "warnings": [], "stats": {}}
    seen_shots, seen_lines, all_shots = set(), set(), []
    for c in clips:
        lines = {l.get("id"): l for l in c.get("lines", [])}
        for lid, l in lines.items():
            if lid in seen_lines:
                errors.append(f"line {lid}: duplicate id")
            seen_lines.add(lid)
            for k in ("id", "speaker", "caption", "tts"):
                if not l.get(k):
                    errors.append(f"line {lid}: missing '{k}'")
            if l.get("fx") not in (None, "radio", "stranger"):
                errors.append(f"line {lid}: fx must be radio or stranger")
            if lang == "en" and not (sb.get("voices", {}).get(l.get("speaker")) or {}).get("description"):
                errors.append(f"line {lid}: speaker '{l.get('speaker')}' has no voices.{l.get('speaker')}.description")
            if lang == "hi" and l.get("speaker") not in ("tara", "dadi"):
                errors.append(f"line {lid}: Hindi speakers must be tara or dadi (got '{l.get('speaker')}')")
        if not c.get("shots"):
            errors.append(f"clip {c.get('id')}: no shots")
        for s in c.get("shots", []):
            sid = s.get("id")
            all_shots.append((c, s))
            if sid in seen_shots:
                errors.append(f"shot {sid}: duplicate id")
            seen_shots.add(sid)
            if s.get("tech") not in TECHS:
                errors.append(f"shot {sid}: tech must be one of {', '.join(TECHS)}")
                continue
            if s["tech"] == "TALK" and s.get("line") not in lines:
                errors.append(f"shot {sid}: TALK needs a 'line' id from clip {c.get('id')}")
            if s["tech"] != "TALK" and not s.get("dur_s"):
                errors.append(f"shot {sid}: needs dur_s")
            if not (s.get("keyframe_prompt") or s.get("last_frame_prompt")):
                errors.append(f"shot {sid}: needs keyframe_prompt")
            for r in s.get("refs", []):
                if r not in names:
                    errors.append(f"shot {sid}: unknown ref '{r}' (not in characters/sets)")
            for lid in s.get("vo_lines", []):
                if lid not in lines:
                    errors.append(f"shot {sid}: vo_lines '{lid}' is not a line of clip {c.get('id')}")
            if s.get("vo") and not any(s["vo"] in (l.get("tts") or "") for l in lines.values()):
                errors.append(f"shot {sid}: 'vo' must be an exact part of one of its clip's lines")
            for e in s.get("sfx", []):
                if e.get("type") not in SFX:
                    errors.append(f"shot {sid}: unknown sfx type '{e.get('type')}'")
                elif float(e.get("at", 0)) > shot_seconds(s) + 0.01 and shot_seconds(s):
                    warns.append(f"shot {sid}: sfx '{e['type']}' at {e.get('at')} s is after the shot ends ({shot_seconds(s)} s)")
            for o in s.get("overlays", []):
                if o.get("style", "label") not in OVERLAY_STYLES or not o.get("text"):
                    errors.append(f"shot {sid}: overlay needs text and a style of {'/'.join(OVERLAY_STYLES)}")
                elif len(o["text"]) > 70 and o.get("style", "label") in ("title", "label", "hud"):
                    warns.append(f"shot {sid}: overlay text is {len(o['text'])} chars; keep it under 70 to read at phone size")
            base = (s.get("cover") or {}).get("base")
            if base and base not in seen_shots:
                errors.append(f"shot {sid}: cover.base '{base}' must be an earlier shot")
            ff = s.get("first_frame", "")
            if ff.startswith("last frame of") and ff.replace("last frame of", "").strip() not in seen_shots:
                errors.append(f"shot {sid}: first_frame refers to a shot that is not earlier")
            d = shot_seconds(s)
            if d and d > 6.5:
                warns.append(f"shot {sid}: {d} s is long for a video model and for the cut cadence (keep shots 2-6 s)")
            txt = " ".join(str(s.get(k, "")) for k in ("keyframe_prompt", "motion_prompt"))
            m = HARD_FOR_MODELS.search(txt)
            if m:
                warns.append(f"shot {sid}: '{m.group(0)}' is hard for the image/video models; show it another way")
            if re.search(r"[\"“][^\"”]{3,}[\"”]", s.get("keyframe_prompt", "")):
                warns.append(f"shot {sid}: keyframe_prompt quotes text; text in the image is unreadable - use an overlay")
    # pacing / hook
    durs = [shot_seconds(s) for _, s in all_shots]
    total = sum(durs)
    first_c, first = all_shots[0]
    stats = {"shots": len(all_shots), "clips": len(clips), "picture_s": round(total, 1),
             "avg_shot_s": round(total / max(1, len(durs)), 2)}
    if shot_seconds(first) > 3.5:
        warns.append(f"hook: first shot {first.get('id')} is {shot_seconds(first)} s; the hook frame should cut by 3 s")
    if not any(o.get("at", 0) <= 1.0 for o in first.get("overlays", [])):
        warns.append("hook: no on-screen text in the first second (muted viewers see only the picture)")
    if not first.get("sfx"):
        warns.append("hook: no sound hit on the first shot")
    if stats["avg_shot_s"] > 3.5:
        warns.append(f"pacing: average shot is {stats['avg_shot_s']} s; aim for 1.5-3 s")
    for a, b in zip(all_shots, all_shots[1:]):
        fa, fb = a[1].get("framing"), b[1].get("framing")
        if fa and fa == fb and a[1].get("refs") == b[1].get("refs"):
            warns.append(f"pacing: {a[1]['id']} -> {b[1]['id']} repeat the same framing on the same subject (jump-cut feel)")
    wps = WPS.get(lang, 2.4)
    clip_stats = {}
    for c in clips:
        pic = sum(shot_seconds(s) for s in c.get("shots", []))
        words = sum(len((l.get("tts") or "").split()) for l in c.get("lines", []))
        voice = words / wps
        clip_stats[c.get("id")] = {"picture_s": round(pic, 1), "voice_s_est": round(voice, 1)}
        if pic and voice > pic * 1.15:
            warns.append(f"clip {c.get('id')}: ~{voice:.0f} s of voice over {pic:.0f} s of pictures; the clip will stretch "
                         f"(assembly times shots to the voice) - cut words or add shots")
        if pic and voice < pic * 0.35 and c.get("lines"):
            warns.append(f"clip {c.get('id')}: voice covers only ~{100 * voice / pic:.0f} % of the clip; risk of dead air")
    stats["clips_detail"] = clip_stats
    target = (sb.get("format") or {}).get("target_duration_s")
    if isinstance(target, (int, float)) and total and abs(total - target) / target > 0.35:
        warns.append(f"length: {total:.0f} s of pictures vs a {target} s target")
    return {"errors": errors, "warnings": warns, "stats": stats}
