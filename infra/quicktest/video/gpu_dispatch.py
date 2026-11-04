"""Model-affinity GPU dispatcher for one ComfyUI box.

Problem it fixes: several streams (deities, scene 3, scene 4, ep2 ...) used to POST straight into ComfyUI's FIFO queue,
so image-edit jobs (Qwen, ~29 GB) and video jobs (Wan 2.2, ~35 GB) alternated on a 48 GB GPU and every alternation
evicted one model family and reloaded the other. Measured in the 2026-11-03 run: the same 480x832 video shot took 30 s
back to back and 60-220 s (incl. waiting) when interleaved with image jobs.

How: clients drop a request file into QDIR/pending; this daemon owns the GPU and always runs the next job of the family
that is ALREADY LOADED, switching family only when that family has nothing waiting (or when a job has waited longer
than MAX_WAIT, so nothing starves). A family is only scheduled once its weights are on disk (MODELS_READY/<family>,
written by gpu_bootstrap.sh while it streams families in priority order). Every job is logged to logs/gpu_jobs.jsonl
(family, wait, run, whether it caused a model switch) for util_report.py.

  daemon : python gpu_dispatch.py serve
  client : comfy.run(graph) uses submit()/wait_result() automatically when the daemon is up (QDIR/dispatcher.pid)."""
import json, os, sys, time, uuid
from pathlib import Path

ROOT = Path(os.environ.get("VREA_ROOT", "/mnt/nvme"))
QDIR = ROOT / "gpuq"; PENDING, DONE = QDIR / "pending", QDIR / "done"
MODELS_READY = ROOT / "models.ready"
LOG = ROOT / "logs" / "gpu_jobs.jsonl"
MAX_WAIT = float(os.environ.get("VREA_MAX_WAIT", 900))          # s; older jobs jump the family order
_here = Path(__file__).resolve().parent                        # repo: infra/quicktest/video/; box bundle: jobs3/ (flat)
_mf = next((p for p in (_here / "models.json", _here.parent / "models.json") if p.exists()), None)
MANIFEST = json.load(open(_mf)) if _mf else {"detect": {}}
DETECT = {k: v for k, v in MANIFEST.get("detect", {}).items() if not k.startswith("_")}


def family_of(graph):
    """Which model family a ComfyUI API graph needs (from its loader nodes)."""
    names = []
    for n in graph.values():
        ins = n.get("inputs", {})
        for key in ("unet_name", "name", "model_name", "ckpt_name", "patch_name"):
            v = ins.get(key)
            if isinstance(v, str):
                names.append(v)
    for needle, fam in DETECT.items():                       # order in models.json matters (talk before video, edit before image)
        if any(needle in x for x in names):
            return fam
    return "other"


def pick(pending, current, now, ready=None, max_wait=MAX_WAIT):
    """Choose the next job. pending: list of dicts with id, family, t (submit time). Pure function (unit-tested).
    1) any job older than max_wait (oldest first)  2) oldest job of the current family  3) the family with the most
    jobs waiting (ties: oldest job). Families whose weights are not ready yet are skipped."""
    runnable = [j for j in pending if ready is None or j["family"] in ready or j["family"] == "other"]
    if not runnable:
        return None
    runnable.sort(key=lambda j: j["t"])
    starving = [j for j in runnable if now - j["t"] > max_wait]
    if starving:
        return starving[0]
    same = [j for j in runnable if j["family"] == current]
    if same:
        return same[0]
    counts = {}
    for j in runnable:
        counts[j["family"]] = counts.get(j["family"], 0) + 1
    best = max(counts, key=lambda f: (counts[f], -min(j["t"] for j in runnable if j["family"] == f)))
    return next(j for j in runnable if j["family"] == best)


# ------------------------------------------------------------------ client side
def available():
    p = QDIR / "dispatcher.pid"
    if not p.exists():
        return False
    try:
        os.kill(int(p.read_text()), 0); return True
    except (OSError, ValueError):
        return False


def submit(graph, tag=""):
    PENDING.mkdir(parents=True, exist_ok=True)
    jid = f"{time.time():.6f}_{uuid.uuid4().hex[:8]}"
    req = {"id": jid, "family": family_of(graph), "t": time.time(), "tag": tag, "graph": graph}
    tmp = PENDING / f".{jid}.tmp"; tmp.write_text(json.dumps(req)); tmp.rename(PENDING / f"{jid}.json")   # atomic
    return jid


def wait_result(jid, timeout=7200, poll=1.0):
    f = DONE / f"{jid}.json"; t0 = time.time()
    while time.time() - t0 < timeout:
        if f.exists():
            r = json.loads(f.read_text()); f.unlink(missing_ok=True)
            if r.get("error"):
                raise RuntimeError(r["error"])
            return [Path(x) for x in r["files"]], round(time.time() - t0, 1)
        time.sleep(poll)
    raise TimeoutError(jid)


# ------------------------------------------------------------------ daemon
def ready_families():
    return {p.name for p in MODELS_READY.iterdir()} if MODELS_READY.exists() else None   # None = no staging, all ready


def serve(execute=None, once=False, idle_sleep=0.5):
    """execute(graph) -> list of output paths; defaults to ComfyUI via comfy.run_direct."""
    if execute is None:
        sys.path.insert(0, str(Path(__file__).parent)); import comfy
        comfy.wait_up(); execute = lambda g: comfy.run_direct(g)[0]
    for d in (PENDING, DONE, LOG.parent):
        d.mkdir(parents=True, exist_ok=True)
    (QDIR / "dispatcher.pid").write_text(str(os.getpid()))
    current = None
    while True:
        pending = []
        for f in PENDING.glob("*.json"):
            try:
                j = json.loads(f.read_text()); j["_file"] = f; pending.append(j)
            except (json.JSONDecodeError, OSError):
                continue
        job = pick(pending, current, time.time(), ready_families())
        if job is None:
            if once:
                return
            time.sleep(idle_sleep); continue
        job["_file"].unlink(missing_ok=True)
        switched = current is not None and job["family"] != current and job["family"] != "other"
        t0 = time.time(); rec = {"id": job["id"], "family": job["family"], "tag": job.get("tag", ""), "wait_s": round(t0 - job["t"], 1),
                                "switch": switched, "queued_behind": len(pending) - 1}
        try:
            files = execute(job["graph"]); out = {"files": [str(x) for x in files]}
        except Exception as e:                                # report to the client, keep serving
            out = {"files": [], "error": str(e)[-3000:]}
        rec["run_s"] = round(time.time() - t0, 1); rec["ok"] = "error" not in out
        if job["family"] != "other":
            current = job["family"]
        tmp = DONE / f".{job['id']}.tmp"; tmp.write_text(json.dumps(out)); tmp.rename(DONE / f"{job['id']}.json")
        with open(LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
