"""End-to-end test of the platform without a GPU: real Postgres, real web server, real S3, real ffmpeg assembly;
the GPU worker is simulated (it returns stand-in images / audio / video made with ffmpeg). Acts as the owner through
the web UI: picks the top variant at every gate until the episode is approved.
usage: python e2e_local.py http://127.0.0.1:8001 <password> <project_id>"""
import json, re, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request, uuid
from http.cookiejar import CookieJar
from pathlib import Path
import boto3

BASE, PW, PID = sys.argv[1], sys.argv[2], int(sys.argv[3])
BUCKET = "vrea-686112930191-us-east-1"
s3 = boto3.client("s3", region_name="us-east-1")
jar = CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
TMP = Path(tempfile.mkdtemp())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def post(path, data):
    return op.open(BASE + path, urllib.parse.urlencode(data).encode(), timeout=60)


def get(path):
    return op.open(BASE + path, timeout=60).read().decode()


def fake(kind, w=480, h=832, sec=3, audio=False):
    f = TMP / f"{uuid.uuid4().hex[:6]}.{ {'image': 'png', 'audio': 'wav', 'video': 'mp4'}[kind] }"
    if kind == "image":
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=720x1280", "-frames:v", "1", f], check=True)
    elif kind == "audio":
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=f=330:d=2.5", "-ar", "24000", f], check=True)
    else:
        args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=16:d={sec}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=f=220:d={sec}", "-shortest"]
        subprocess.run(args + ["-pix_fmt", "yuv420p", f], check=True)
    key = f"platform/test/{f.name}"; s3.upload_file(str(f), BUCKET, key); return key


def worker(run_id, token):
    """Simulated GPU worker speaking the real /api/w protocol."""
    def api(path, body):
        req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Worker-Token": token})
        return json.load(urllib.request.urlopen(req, timeout=60))
    api("/api/w/heartbeat", {"run_id": run_id, "ready": True})
    while True:
        for lane in ("gpu", "voice"):
            t = api("/api/w/claim", {"run_id": run_id, "lane": lane, "ready": ["image", "edit", "video", "talk"], "last": None}).get("task")
            if not t:
                continue
            p = t["params"]
            if t["type"] in ("sheet", "keyframe"):
                outs = []
                for v in range(p.get("variants", 2)):
                    meta = {"variant": v + 1}
                    if p.get("shot", {}).get("tech") == "FLF":
                        meta["first"] = fake("image")
                    outs.append({"s3_key": fake("image"), "kind": "image", "meta": meta, "scores": {"ref_sim": 0.8 - v / 10, "rank": 0.8 - v / 10}})
            elif t["type"] == "voice":
                outs = [{"s3_key": fake("audio"), "kind": "audio", "meta": {}, "scores": {"n_issues": 0, "rank": -v}} for v in range(4)]
            elif t["type"] == "talk":
                outs = [{"s3_key": fake("video", sec=3, audio=True), "kind": "video", "meta": {}, "scores": {"rank": 1}}]
            else:
                outs = [{"s3_key": fake("video", sec=(p["frames"] - 1) / 16), "kind": "video", "meta": {}, "scores": {"rank": 1}}]
            api("/api/w/complete", {"run_id": run_id, "task_id": t["id"], "outputs": outs})
            print("  worker did", t["type"], t["slot_key"], flush=True)
        time.sleep(1)


def main():
    post("/login", {"password": PW})
    import psycopg
    c = psycopg.connect("postgresql://vrea:vrea@127.0.0.1/vrea", autocommit=True)
    run_id = c.execute("INSERT INTO runs (project_id, state, token, launched_at, hourly_usd, instance_id) VALUES (%s,'booting','tok',now(),0,'sim') RETURNING id",
                       (PID,)).fetchone()[0]
    threading.Thread(target=worker, args=(run_id, "tok"), daemon=True).start()
    t0 = time.time(); picked = 0
    while time.time() - t0 < 1500:
        st = c.execute("SELECT key, state FROM slots WHERE project_id=%s ORDER BY ord", (PID,)).fetchall()
        rev = [k for k, s in st if s == "review"]
        if dict(st).get("episode") == "approved":
            break
        for key in rev:
            html = get(f"/p/{PID}/s/{urllib.parse.quote(key)}")
            ids = re.findall(r'name="asset_id" value="(\d+)"', html)
            if ids:
                post(f"/p/{PID}/s/{urllib.parse.quote(key)}/pick", {"asset_id": ids[0]}); picked += 1
                print("picked", key, ids[0], flush=True)
        failed = [k for k, s in st if s == "failed"]
        if failed:
            err = c.execute("SELECT slot_key, error FROM tasks WHERE project_id=%s AND state='failed'", (PID,)).fetchall()
            print("FAILED", failed, err); sys.exit(1)
        time.sleep(2)
    st = dict(c.execute("SELECT key, state FROM slots WHERE project_id=%s", (PID,)).fetchall())
    ep = c.execute("SELECT a.meta FROM slots s JOIN assets a ON a.id=s.chosen_asset WHERE s.project_id=%s AND s.key='episode'", (PID,)).fetchone()
    print("episode:", st.get("episode"), "picks:", picked, "qa:", json.dumps(ep[0]["qa"] if ep else None))
    assert st.get("episode") == "approved"
    for page in ["/", f"/p/{PID}", f"/p/{PID}/board", "/runs", "/settings", "/new"]:
        assert "<" in get(page), page
    print("E2E OK")


if __name__ == "__main__":
    main()
