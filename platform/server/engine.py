"""Pipeline engine: storyboard -> slots (one per thing you might review) with dependencies -> tasks.

Slot kinds, in phase order:
  script            the storyboard itself                      gate (you approve)
  ref:<name>        character / set reference sheet            gate (you pick a variant) unless imported as locked
  voice:<line>      the line's voice takes                     gate (you pick a take)
  kf:<shot>         the shot's keyframe(s)                     gate (you pick)  <- before any video is spent
  video:<shot>      the shot's video                           auto (optional gate skipped)
  clip:<clip>       assembled clip                             auto
  episode           stitched episode + QA report               gate (final approval)

A slot is waiting until every dependency is approved, then its tasks are queued; when they finish it goes to review
(gate) or is approved automatically (best-scored variant). Regenerate-with-note starts a new round of the same slot;
reopening an approved slot sends everything downstream back to waiting."""
import math
from db import J, conn, event, ex, one, q, tx

PHASES = ["Script", "Designs", "Voices", "Keyframes", "Videos", "Clips", "Episode"]
VARIANTS = {"ref": 2, "kf": 2}
GPU_FAMILIES = ("image", "edit", "video", "talk", "voice")
VOICE_REFS = ("tara", "dadi")                      # locked voices available on the GPU box (voice_v2/refs)


def shots(sb):
    for c in sb["clips"]:
        for s in c["shots"]:
            yield c, s


def build_slots(project_id, sb, locked=None, script_approved=False):
    """Create every slot for a storyboard. locked: {ref_name: s3_key} imported as already approved."""
    locked = locked or {}
    rows, ordn = [], 0

    def add(key, kind, phase, label, gate, deps, params=None):
        nonlocal ordn
        ordn += 1
        rows.append((project_id, key, kind, phase, label, gate, list(deps), J(params or {}), ordn))

    add("script", "script", "Script", "Storyboard", True, [])
    refs = {**{k: ("character", v) for k, v in sb.get("characters", {}).items()},
            **{k: ("set", v) for k, v in sb.get("sets", {}).items()}}
    for name, (typ, d) in refs.items():
        add(f"ref:{name}", "ref", "Designs", f"{name} ({typ})", True, ["script"],
            {"name": name, "type": typ, "description": d.get("description", ""), "derive_from": d.get("derive_from")})
    for c in sb["clips"]:
        for l in c.get("lines", []):
            add(f"voice:{l['id']}", "voice", "Voices", f"{l['id']} · {l['speaker']}", True, ["script"], {"line": l})
    for c, s in shots(sb):
        deps = ["script"] + [f"ref:{r}" for r in s.get("refs", []) if r in refs]
        base = (s.get("cover") or {}).get("base")
        if base:
            deps.append(f"kf:{base}")
        ff = s.get("first_frame", "")
        prev = ff.replace("last frame of", "").strip() if ff.startswith("last frame of") else None
        if prev:
            deps.append(f"kf:{prev}")
        add(f"kf:{s['id']}", "kf", "Keyframes", f"{s['id']} · {s['tech']}", True, dict.fromkeys(deps), {"shot": s, "clip": c["id"], "prev": prev})
    for c, s in shots(sb):
        deps = [f"kf:{s['id']}"]
        if s["tech"] == "TALK":
            deps.append(f"voice:{s['line']}")
        ff = s.get("first_frame", "")
        if ff.startswith("last frame of"):
            deps.append(f"video:{ff.replace('last frame of', '').strip()}")
        add(f"video:{s['id']}", "video", "Videos", f"{s['id']} · {s['tech']}", False, deps, {"shot": s, "clip": c["id"]})
    for c in sb["clips"]:
        deps = [f"video:{s['id']}" for s in c["shots"]] + [f"voice:{l['id']}" for l in c.get("lines", [])]
        add(f"clip:{c['id']}", "clip", "Clips", f"{c['id']} · {c.get('title', '')}", False, deps, {"clip_id": c["id"]})
    add("episode", "episode", "Episode", "Episode + QA report", True, [f"clip:{c['id']}" for c in sb["clips"]])
    with tx() as cx:
        cx.cursor().executemany(
            "INSERT INTO slots (project_id, key, kind, phase, label, gate, deps, params, ord) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    if script_approved:
        ex("UPDATE slots SET state='approved' WHERE project_id=%s AND key='script'", project_id)
    for name, key in locked.items():
        a = one("INSERT INTO assets (project_id, slot_key, kind, s3_key, meta) VALUES (%s,%s,'image',%s,%s) RETURNING id",
                project_id, f"ref:{name}", key, J({"locked": True}))
        ex("UPDATE slots SET state='approved', chosen_asset=%s, gate=false, label=label || ' · locked' WHERE project_id=%s AND key=%s",
           a["id"], project_id, f"ref:{name}")


def slot_map(pid):
    return {s["key"]: s for s in q("SELECT * FROM slots WHERE project_id=%s", pid)}


def chosen_key(slots, key):
    s = slots.get(key)
    if not s or not s["chosen_asset"]:
        return None
    a = one("SELECT s3_key, meta FROM assets WHERE id=%s", s["chosen_asset"])
    return a and {"s3": a["s3_key"], "meta": a["meta"]}


def nframes(sec, fps=16, lo=33):
    n = max(lo, int(round(sec * fps)) + 1)
    return n + (4 - (n - 1) % 4) % 4


def task_specs(project, slot, slots):
    """What to run for a slot whose dependencies are approved: list of (type, family, params)."""
    sb, p, k = project["storyboard"], slot["params"], slot["kind"]
    style = sb.get("style", {})
    common = {"look": style.get("look", ""), "negative": style.get("negative", ""), "note": slot["note"], "round": slot["round"],
              "project": project["id"], "slot": slot["key"]}
    if k == "ref":
        return [("sheet", "image", {**common, **p, "variants": VARIANTS["ref"]})]
    if k == "voice":
        line = p["line"]; spk = line["speaker"] if line["speaker"] in VOICE_REFS else "dadi"
        return [("voice", "voice", {**common, "line": line, "speaker": spk, "takes": 4})]
    if k == "kf":
        s = p["shot"]; refs = {}
        for r in s.get("refs", []):
            c = chosen_key(slots, f"ref:{r}")
            if c:
                refs[r] = c["s3"]
        base = (s.get("cover") or {}).get("base")
        chars = [r for r in s.get("refs", []) if r in sb.get("characters", {})]
        par = {**common, "shot": s, "refs": refs, "characters": {r: sb["characters"][r].get("description", "") for r in chars},
               "base": chosen_key(slots, f"kf:{base}") if base else None,
               "prev": chosen_key(slots, f"kf:{p['prev']}") if p.get("prev") else None, "variants": VARIANTS["kf"]}
        fam = "edit" if (refs or par["base"] or par["prev"] or s["tech"] == "FLF") else "image"
        return [("keyframe", fam, par)]
    if k == "video":
        s = p["shot"]; kf = chosen_key(slots, f"kf:{s['id']}")
        par = {**common, "shot": s, "kf": kf,
               "characters": {r: sb["characters"][r].get("description", "") for r in s.get("refs", []) if r in sb.get("characters", {})}}
        if s["tech"] == "TALK":
            par["audio"] = chosen_key(slots, f"voice:{s['line']}")
            return [("talk", "talk", par)]
        ff = s.get("first_frame", "")
        if ff.startswith("last frame of"):
            par["prev_video"] = chosen_key(slots, f"video:{ff.replace('last frame of', '').strip()}")
        par["frames"] = nframes(float(s.get("dur_s", 3)))
        return [("video", "video", par)]
    if k == "clip":
        return [("clip", "cpu", {**common, "clip_id": p["clip_id"]})]
    if k == "episode":
        return [("episode", "cpu", common)]
    return []


def advance(pid):
    """One engine step for a project. Idempotent; called every few seconds."""
    project = one("SELECT * FROM projects WHERE id=%s", pid)
    if not project or project["status"] in ("done", "paused"):
        return
    slots = slot_map(pid)
    for s in sorted(slots.values(), key=lambda x: x["ord"]):
        if s["state"] == "waiting" and s["kind"] != "script" and all(slots[d]["state"] == "approved" for d in s["deps"] if d in slots):
            specs = task_specs(project, s, slots)
            with tx() as cx:
                for typ, fam, par in specs:
                    cx.execute("INSERT INTO tasks (project_id, slot_key, round, type, family, params) VALUES (%s,%s,%s,%s,%s,%s)",
                               (pid, s["key"], s["round"], typ, fam, J(par)))
                cx.execute("UPDATE slots SET state='generating', updated_at=now() WHERE id=%s", (s["id"],))
            s["state"] = "generating"
        elif s["state"] == "generating":
            ts = q("SELECT state FROM tasks WHERE project_id=%s AND slot_key=%s AND round=%s", pid, s["key"], s["round"])
            if ts and all(t["state"] == "done" for t in ts):
                assets = q("SELECT id, scores FROM assets WHERE project_id=%s AND slot_key=%s AND round=%s ORDER BY id", pid, s["key"], s["round"])
                if not assets:
                    ex("UPDATE slots SET state='failed', updated_at=now() WHERE id=%s", s["id"]); event(pid, f"{s['label']}: produced no output", "error")
                elif s["gate"]:
                    ex("UPDATE slots SET state='review', updated_at=now() WHERE id=%s", s["id"]); event(pid, f"{s['label']} is ready for your review")
                elif any((a["scores"] or {}).get("needs_review") for a in assets):
                    # an automatic check failed after retries (e.g. subject drift in a video): ask instead of approving
                    ex("UPDATE slots SET state='review', updated_at=now() WHERE id=%s", s["id"])
                    event(pid, f"{s['label']}: a subject still changes shape after 3 renders. Please review (pick it, or regenerate with a note)", "warn")
                else:
                    best = max(assets, key=lambda a: (a["scores"] or {}).get("rank", 0))
                    ex("UPDATE slots SET state='approved', chosen_asset=%s, updated_at=now() WHERE id=%s", best["id"], s["id"])
                    event(pid, f"{s['label']} done")
            elif any(t["state"] == "failed" for t in ts):
                ex("UPDATE slots SET state='failed', updated_at=now() WHERE id=%s", s["id"])
                err = one("SELECT error FROM tasks WHERE project_id=%s AND slot_key=%s AND round=%s AND state='failed' LIMIT 1", pid, s["key"], s["round"])
                event(pid, f"{s['label']} failed: {(err or {}).get('error', '')[:300]}", "error")
    ep = slots.get("episode")
    if ep and ep["state"] == "approved" and project["status"] != "done":
        ex("UPDATE projects SET status='done', updated_at=now() WHERE id=%s", pid); event(pid, "Episode approved. Finished.")


def approve(pid, key, asset_id=None):
    s = one("SELECT * FROM slots WHERE project_id=%s AND key=%s", pid, key)
    if key == "script":
        ex("UPDATE slots SET state='approved', updated_at=now() WHERE id=%s", s["id"]); event(pid, "Storyboard approved"); return
    if asset_id is None:
        return
    ex("UPDATE slots SET state='approved', chosen_asset=%s, updated_at=now() WHERE id=%s", int(asset_id), s["id"])
    event(pid, f"{s['label']}: you picked variant #{asset_id}")


def downstream(pid, key):
    slots = slot_map(pid); out, frontier = set(), {key}
    while frontier:
        nxt = {k for k, s in slots.items() if set(s["deps"]) & frontier} - out
        out |= nxt; frontier = nxt
    return out


def regenerate(pid, key, note):
    """New round for a slot (with your note added to the prompt). Downstream work is reset."""
    s = one("SELECT * FROM slots WHERE project_id=%s AND key=%s", pid, key)
    note = ((s["note"] + " | ") if s["note"] else "") + note if note else s["note"]
    with tx() as cx:
        cx.execute("UPDATE tasks SET state='cancelled' WHERE project_id=%s AND slot_key=%s AND state IN ('queued')", (pid, key))
        cx.execute("UPDATE slots SET state='waiting', round=round+1, note=%s, chosen_asset=NULL, updated_at=now() WHERE id=%s", (note, s["id"]))
    reset(pid, downstream(pid, key))
    event(pid, f"{s['label']}: regenerating" + (f" with note: {note}" if note else ""))


def reopen(pid, key):
    s = one("SELECT * FROM slots WHERE project_id=%s AND key=%s", pid, key)
    ex("UPDATE slots SET state='review', updated_at=now() WHERE id=%s", s["id"])
    reset(pid, downstream(pid, key)); event(pid, f"{s['label']} reopened")


def reset(pid, keys):
    for k in keys:
        s = one("SELECT * FROM slots WHERE project_id=%s AND key=%s", pid, k)
        if s and s["state"] != "waiting":
            ex("UPDATE tasks SET state='cancelled' WHERE project_id=%s AND slot_key=%s AND state='queued'", pid, k)
            ex("UPDATE slots SET state='waiting', round=round+1, chosen_asset=NULL, updated_at=now() WHERE id=%s", s["id"])


def retry_failed(pid, key):
    ex("UPDATE slots SET state='waiting', round=round+1, updated_at=now() WHERE project_id=%s AND key=%s", pid, key)


def gpu_work_remaining(pid):
    """Is there GPU work queued now, or GPU work that will start once a review is answered?"""
    queued = one("SELECT count(*) n FROM tasks WHERE project_id=%s AND state IN ('queued','running') AND family<>'cpu'", pid)["n"]
    future = one("SELECT count(*) n FROM slots WHERE project_id=%s AND kind IN ('ref','voice','kf','video') AND state<>'approved'", pid)["n"]
    return queued, future
