"""vrea platform web app: one owner, password login. Background threads: engine (advances every project), autoscaler
(GPU boxes + cap), CPU worker (clip/episode assembly). GPU workers talk to /api/w/* with a per-box token."""
import hashlib, hmac, json, os, secrets, threading, time, traceback
from pathlib import Path
import boto3
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

import db
from db import J, event, ex, one, q

HERE = Path(__file__).resolve().parent
BUCKET = os.environ.get("VREA_BUCKET", "vrea-686112930191-us-east-1")
REGION = os.environ.get("VREA_REGION", "us-east-1")
NO_BACKGROUND = os.environ.get("VREA_NO_BACKGROUND") == "1"   # tests
app = FastAPI(title="vrea")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")
s3 = boto3.client("s3", region_name=REGION)
STATE_LABEL = {"waiting": "waiting", "generating": "generating", "review": "needs you", "approved": "approved", "failed": "failed"}


# ------------------------------------------------------------------ auth
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + "$" + hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()


def check_pw(pw, stored):
    salt, h = stored.split("$", 1)
    return hmac.compare_digest(hash_pw(pw, salt).split("$", 1)[1], h)


def signer():
    return URLSafeTimedSerializer(db.setting("secret"), salt="session")


@app.middleware("http")
async def auth(request: Request, call_next):
    p = request.url.path
    if p.startswith(("/static", "/api/w/", "/login", "/healthz")):
        return await call_next(request)
    try:
        signer().loads(request.cookies.get("s", ""), max_age=14 * 86400)
    except BadSignature:
        return RedirectResponse("/login", 303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, err: str = ""):
    return tpl.TemplateResponse(request, "login.html", {"err": err})


@app.post("/login")
def login(password: str = Form(...)):
    stored = db.setting("pw_hash")
    if not stored or not check_pw(password, stored):
        time.sleep(1); return RedirectResponse("/login?err=1", 303)
    r = RedirectResponse("/", 303)
    r.set_cookie("s", signer().dumps("owner"), max_age=14 * 86400, httponly=True, samesite="lax",
                 secure=db.setting("public_url", "").startswith("https"))
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/login", 303); r.delete_cookie("s"); return r


@app.get("/healthz")
def health():
    one("SELECT 1"); return {"ok": True}


# ------------------------------------------------------------------ pages
def project_summary(p):
    import scaler
    counts = {r["state"]: r["n"] for r in q("SELECT state, count(*) n FROM slots WHERE project_id=%s GROUP BY state", p["id"])}
    total = sum(counts.values()) or 1
    return {**p, "counts": counts, "pct": int(100 * counts.get("approved", 0) / total), "review": counts.get("review", 0),
            "spent": scaler.spent(p["id"]), "cap": float(p["cap_usd"])}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    ps = [project_summary(p) for p in q("SELECT * FROM projects ORDER BY id DESC")]
    return tpl.TemplateResponse(request, "index.html", {"projects": ps})


@app.get("/new", response_class=HTMLResponse)
def new_page(request: Request, err: str = ""):
    return tpl.TemplateResponse(request, "new.html", {"err": err, "has_key": bool(db.setting("anthropic_key"))})


@app.post("/new")
def new_project(title: str = Form(...), story: str = Form(""), storyboard: str = Form(""), action: str = Form("create")):
    import drafting, engine
    try:
        if storyboard.strip():
            sb = json.loads(storyboard)
        elif action == "draft":
            key = db.setting("anthropic_key")
            if not key:
                raise ValueError("Add an Anthropic API key in Settings to draft from a story, or paste a storyboard JSON.")
            sb = drafting.draft(key, story, title)
        else:
            raise ValueError("Paste a storyboard JSON, or a story and press 'Draft with Claude'.")
        drafting.validate(sb)
    except Exception as e:
        return RedirectResponse(f"/new?err={str(e)[:300]}", 303)
    p = one("INSERT INTO projects (title, storyboard, story_text) VALUES (%s,%s,%s) RETURNING id", title, J(sb), story)
    engine.build_slots(p["id"], sb)
    event(p["id"], "Story created; storyboard waiting for your approval")
    return RedirectResponse(f"/p/{p['id']}/s/script", 303)


def board_ctx(pid):
    import engine, scaler
    p = one("SELECT * FROM projects WHERE id=%s", pid)
    slots = q("SELECT s.*, a.kind akind, a.id aid FROM slots s LEFT JOIN assets a ON a.id=s.chosen_asset WHERE s.project_id=%s ORDER BY ord", pid)
    for s in slots:
        if not s["aid"]:
            lat = one("SELECT id, kind FROM assets WHERE project_id=%s AND slot_key=%s ORDER BY id DESC LIMIT 1", pid, s["key"])
            if lat:
                s["aid"], s["akind"] = lat["id"], lat["kind"]
        t = one("SELECT state, progress, family FROM tasks WHERE project_id=%s AND slot_key=%s AND round=%s ORDER BY id DESC LIMIT 1", pid, s["key"], s["round"])
        s["task"] = t
    cols = [(ph, [s for s in slots if s["phase"] == ph]) for ph in engine.PHASES]
    run = q("SELECT * FROM runs WHERE project_id=%s ORDER BY id DESC LIMIT 1", pid)
    run = run[0] if run else None
    queued = q("SELECT family, count(*) n FROM tasks WHERE project_id=%s AND state='queued' GROUP BY family", pid)
    return {"p": project_summary(p), "cols": cols, "run": run, "queued": queued,
            "events": q("SELECT * FROM events WHERE project_id=%s ORDER BY id DESC LIMIT 25", pid), "labels": STATE_LABEL}


@app.get("/p/{pid}", response_class=HTMLResponse)
def board(request: Request, pid: int):
    return tpl.TemplateResponse(request, "project.html", board_ctx(pid))


@app.get("/p/{pid}/board", response_class=HTMLResponse)
def board_partial(request: Request, pid: int):
    return tpl.TemplateResponse(request, "_board.html", board_ctx(pid))


@app.get("/p/{pid}/review")
def next_review(pid: int):
    s = one("SELECT key FROM slots WHERE project_id=%s AND state='review' ORDER BY ord LIMIT 1", pid)
    return RedirectResponse(f"/p/{pid}/s/{s['key']}" if s else f"/p/{pid}", 303)


@app.get("/p/{pid}/s/{key}", response_class=HTMLResponse)
def slot_page(request: Request, pid: int, key: str):
    p = one("SELECT * FROM projects WHERE id=%s", pid)
    s = one("SELECT * FROM slots WHERE project_id=%s AND key=%s", pid, key)
    assets = q("SELECT * FROM assets WHERE project_id=%s AND slot_key=%s ORDER BY round DESC, (scores->>'rank')::float DESC NULLS LAST, id", pid, key)
    tasks = q("SELECT * FROM tasks WHERE project_id=%s AND slot_key=%s ORDER BY id DESC LIMIT 5", pid, key)
    nxt = one("SELECT key FROM slots WHERE project_id=%s AND state='review' AND key<>%s ORDER BY ord LIMIT 1", pid, key)
    sb_text = json.dumps(p["storyboard"], ensure_ascii=False, indent=2) if key == "script" else ""
    deps = q("SELECT key, label, state FROM slots WHERE project_id=%s AND key = ANY(%s)", pid, s["deps"])
    return tpl.TemplateResponse(request, "slot.html", {"p": p, "s": s, "assets": assets, "tasks": tasks, "next": nxt, "sb_text": sb_text,
                                                       "deps": deps, "labels": STATE_LABEL})


@app.post("/p/{pid}/s/{key}/pick")
def pick(pid: int, key: str, asset_id: int = Form(...)):
    import engine
    engine.approve(pid, key, asset_id); return RedirectResponse(f"/p/{pid}/review", 303)


@app.post("/p/{pid}/s/{key}/regen")
def regen(pid: int, key: str, note: str = Form("")):
    import engine
    engine.regenerate(pid, key, note.strip()); return RedirectResponse(f"/p/{pid}", 303)


@app.post("/p/{pid}/s/{key}/reopen")
def reopen(pid: int, key: str):
    import engine
    engine.reopen(pid, key); return RedirectResponse(f"/p/{pid}/s/{key}", 303)


@app.post("/p/{pid}/s/{key}/retry")
def retry(pid: int, key: str):
    import engine
    engine.retry_failed(pid, key); return RedirectResponse(f"/p/{pid}", 303)


@app.post("/p/{pid}/script")
def save_script(pid: int, storyboard: str = Form(...), action: str = Form("save")):
    import drafting, engine
    s = one("SELECT state FROM slots WHERE project_id=%s AND key='script'", pid)
    try:
        sb = json.loads(storyboard); drafting.validate(sb)
    except Exception as e:
        event(pid, f"Storyboard not saved: {e}", "error"); return RedirectResponse(f"/p/{pid}/s/script", 303)
    if s["state"] != "approved":
        ex("DELETE FROM slots WHERE project_id=%s", pid); ex("DELETE FROM assets WHERE project_id=%s AND slot_key LIKE 'ref:%%' AND NOT (meta ? 'locked')", pid)
        ex("UPDATE projects SET storyboard=%s, updated_at=now() WHERE id=%s", J(sb), pid)
        locked = {r["slot_key"][4:]: r["s3_key"] for r in q("SELECT slot_key, s3_key FROM assets WHERE project_id=%s AND meta ? 'locked'", pid)}
        ex("DELETE FROM assets WHERE project_id=%s AND meta ? 'locked'", pid)
        engine.build_slots(pid, sb, locked=locked)
        if action == "approve":
            engine.approve(pid, "script")
        else:
            event(pid, "Storyboard saved")
    return RedirectResponse(f"/p/{pid}" if action == "approve" else f"/p/{pid}/s/script", 303)


@app.post("/p/{pid}/status")
def set_status(pid: int, status: str = Form(...)):
    if status in ("running", "paused"):
        ex("UPDATE projects SET status=%s, updated_at=now() WHERE id=%s", status, pid); event(pid, f"Story {status}")
    return RedirectResponse(f"/p/{pid}", 303)


@app.get("/a/{aid}")
def asset(aid: int):
    a = one("SELECT s3_key FROM assets WHERE id=%s", aid)
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": a["s3_key"]}, ExpiresIn=3600)
    return RedirectResponse(url, 302)


@app.get("/a/{aid}/first")
def asset_first(aid: int):
    a = one("SELECT meta FROM assets WHERE id=%s", aid)
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": a["meta"]["first"]}, ExpiresIn=3600)
    return RedirectResponse(url, 302)


@app.get("/runs", response_class=HTMLResponse)
def runs(request: Request):
    import scaler
    rs = q("SELECT r.*, p.title FROM runs r LEFT JOIN projects p ON p.id=r.project_id ORDER BY r.id DESC LIMIT 100")
    for r in rs:
        r["cost"] = round(scaler.run_cost(r), 2)
    return tpl.TemplateResponse(request, "runs.html", {"runs": rs})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, ok: str = ""):
    return tpl.TemplateResponse(request, "settings.html", {"has_key": bool(db.setting("anthropic_key")), "url": db.setting("public_url", ""), "ok": ok})


@app.post("/settings")
def settings_save(anthropic_key: str = Form(""), new_password: str = Form("")):
    if anthropic_key.strip():
        db.set_setting("anthropic_key", anthropic_key.strip())
    if len(new_password) >= 12:
        db.set_setting("pw_hash", hash_pw(new_password))
    return RedirectResponse("/settings?ok=1", 303)


# ------------------------------------------------------------------ GPU worker API
def worker_run(request, body):
    r = one("SELECT * FROM runs WHERE id=%s", int(body.get("run_id", 0)))
    if not r or not hmac.compare_digest(r["token"], request.headers.get("x-worker-token", "")):
        return None
    return r


@app.post("/api/w/heartbeat")
async def w_heartbeat(request: Request):
    body = await request.json(); r = worker_run(request, body)
    if not r:
        return JSONResponse({"error": "auth"}, 403)
    if r["state"] == "booting":
        ex("UPDATE runs SET state='ready', ready_at=now() WHERE id=%s", r["id"]); event(r["project_id"], f"GPU box {r['instance_id']} is ready")
    ex("UPDATE runs SET last_seen=now() WHERE id=%s", r["id"])
    if body.get("task_id"):
        ex("UPDATE tasks SET heartbeat_at=now() WHERE id=%s AND run_id=%s", int(body["task_id"]), r["id"])
    return {"ok": True, "stop": r["state"] == "terminated"}


@app.post("/api/w/claim")
async def w_claim(request: Request):
    body = await request.json(); r = worker_run(request, body)
    if not r or r["state"] not in ("booting", "ready"):
        return JSONResponse({"task": None}, 200 if r else 403)
    # gpu lane takes any GPU family: first the family it just ran, then families already on disk, then the rest
    # (the worker copies a missing family on demand), so work is never stranded on a box launched for other models
    fams = ["voice"] if body["lane"] == "voice" else ["image", "edit", "video", "talk"]
    ready = body.get("ready", [])
    with db.tx() as c:
        t = c.execute("""SELECT * FROM tasks WHERE project_id=%s AND state='queued' AND family = ANY(%s)
                         ORDER BY (family = %s) DESC, (family = ANY(%s)) DESC, created_at LIMIT 1 FOR UPDATE SKIP LOCKED""",
                      (r["project_id"], fams, body.get("last") or "", ready)).fetchone()
        if not t:
            return {"task": None}
        c.execute("UPDATE tasks SET state='running', run_id=%s, started_at=now(), heartbeat_at=now(), attempts=attempts+1 WHERE id=%s", (r["id"], t["id"]))
        c.execute("UPDATE runs SET last_family=%s, last_task_at=now(), last_seen=now() WHERE id=%s", (t["family"], r["id"]))
    return {"task": {k: t[k] for k in ("id", "project_id", "slot_key", "round", "type", "family", "params")}}


@app.post("/api/w/complete")
async def w_complete(request: Request):
    body = await request.json(); r = worker_run(request, body)
    if not r:
        return JSONResponse({"error": "auth"}, 403)
    complete_task(int(body["task_id"]), body.get("outputs", []), r["id"])
    return {"ok": True}


@app.post("/api/w/judge")
async def w_judge(request: Request):
    """Second opinion on a shot the drift screen flagged. The Anthropic key never leaves this server: the worker sends
    S3 keys of the keyframe and a few frames; Claude looks at them. No key configured -> {"drift": null} (screen decides)."""
    body = await request.json(); r = worker_run(request, body)
    if not r:
        return JSONResponse({"error": "auth"}, 403)
    key = db.setting("anthropic_key")
    if not key:
        return {"drift": None, "problem": "no Anthropic key in Settings"}
    import asyncio, io, drafting
    from PIL import Image

    def run():
        imgs = []
        for k in body["images"][:6]:
            raw = s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()
            im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((768, 768))
            b = io.BytesIO(); im.save(b, "JPEG", quality=88); imgs.append(b.getvalue())
        return drafting.judge_drift(key, imgs, body.get("subjects", []))
    try:
        return await asyncio.to_thread(run)
    except Exception as e:
        return {"drift": None, "problem": f"judge unavailable: {str(e)[:200]}"}


@app.post("/api/w/fail")
async def w_fail(request: Request):
    body = await request.json(); r = worker_run(request, body)
    if not r:
        return JSONResponse({"error": "auth"}, 403)
    fail_task(int(body["task_id"]), body.get("error", ""))
    return {"ok": True}


def complete_task(tid, outputs, run_id=None):
    t = one("SELECT * FROM tasks WHERE id=%s", tid)
    with db.tx() as c:
        for o in outputs:
            c.execute("INSERT INTO assets (project_id, slot_key, round, kind, s3_key, meta, scores) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                      (t["project_id"], t["slot_key"], t["round"], o["kind"], o["s3_key"], J(o.get("meta", {})), J(o.get("scores", {}))))
        c.execute("UPDATE tasks SET state='done', finished_at=now(), progress=NULL WHERE id=%s", (tid,))
        if run_id:
            c.execute("UPDATE runs SET last_task_at=now() WHERE id=%s", (run_id,))


def fail_task(tid, err):
    t = one("SELECT * FROM tasks WHERE id=%s", tid)
    state = "queued" if t["attempts"] < 2 else "failed"
    ex("UPDATE tasks SET state=%s, run_id=NULL, error=%s, finished_at=now() WHERE id=%s", state, err[-3000:], tid)
    event(t["project_id"], f"{t['type']} for {t['slot_key']} " + ("failed, retrying" if state == "queued" else "failed") + f": {err.strip().splitlines()[-1][:200] if err.strip() else ''}",
          "warn" if state == "queued" else "error")


# ------------------------------------------------------------------ background loops
def loop(fn, every, name):
    while True:
        try:
            fn()
        except Exception:
            print(name, traceback.format_exc(), flush=True)
        time.sleep(every)


def engine_tick():
    import engine
    for p in q("SELECT id FROM projects WHERE status IN ('running','cap_reached')"):
        engine.advance(p["id"])
    # tasks whose box went away mid-task go back to the queue
    ex("""UPDATE tasks SET state='queued', run_id=NULL WHERE state='running' AND family<>'cpu'
          AND heartbeat_at < now() - interval '10 minutes'""")


def cpu_worker():
    import assemble
    t = None
    with db.tx() as c:
        t = c.execute("SELECT * FROM tasks WHERE state='queued' AND family='cpu' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if t:
            c.execute("UPDATE tasks SET state='running', started_at=now(), heartbeat_at=now(), attempts=attempts+1 WHERE id=%s", (t["id"],))
    if not t:
        return
    event(t["project_id"], f"assembling {t['slot_key']}")
    try:
        complete_task(t["id"], assemble.CPU_HANDLERS[t["type"]](t))
    except Exception:
        fail_task(t["id"], traceback.format_exc())


def cpu_heartbeat():
    ex("UPDATE tasks SET heartbeat_at=now() WHERE state='running' AND family='cpu'")


@app.on_event("startup")
def startup():
    db.init()
    if not db.setting("secret"):
        db.set_setting("secret", secrets.token_urlsafe(32))
    if os.environ.get("VREA_PW_HASH") and not db.setting("pw_hash"):
        db.set_setting("pw_hash", os.environ["VREA_PW_HASH"])
    if os.environ.get("VREA_PUBLIC_URL"):
        db.set_setting("public_url", os.environ["VREA_PUBLIC_URL"])
    ex("UPDATE tasks SET state='queued' WHERE state='running' AND family='cpu'")      # restart: redo interrupted assembly
    if NO_BACKGROUND:
        return
    import scaler
    loops = [(engine_tick, 4, "engine"), (cpu_worker, 3, "cpu"), (cpu_heartbeat, 60, "cpu-hb")]
    if os.environ.get("VREA_NO_SCALER") != "1":                                     # local testing: never launch real GPUs
        loops.append((scaler.tick, 10, "scaler"))
    for fn, every, name in loops:
        threading.Thread(target=loop, args=(fn, every, name), daemon=True).start()
