"""GPU autoscaler with a hard per-story spending cap.

Spend per story = sum over its GPU boxes of (end or now - launch) x on-demand hourly price.
Three layers keep a story under its cap (default $14):
  1. no launch unless enough budget is left for at least MIN_SESSION_MIN minutes,
  2. every box is launched with a hard power-off timer = the minutes the remaining budget buys (it terminates itself
     even if this server dies),
  3. this loop terminates the box when spend reaches the cap minus a small margin.
One box at a time (the account's G-instance quota is 8 vCPU). The box loads only the model families that queued tasks
need (MODELS=fam:...); it stays warm while a review you are answering would unlock more GPU work."""
import math, os, secrets, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from db import J, event, ex, one, q, setting

REGION = os.environ.get("VREA_REGION", "us-east-1")
BUCKET = os.environ.get("VREA_BUCKET", "vrea-686112930191-us-east-1")
PROFILE = os.environ.get("VREA_GPU_PROFILE", "vrea-ec2")
TAG = "vrea-platform"
PRICES = {"g6e.2xlarge": 2.242, "g6e.xlarge": 1.861}          # us-east-1 on-demand $/h
TYPES = ["g6e.2xlarge", "g6e.xlarge"]
# tried in order: Spot first (the account's Spot G quota is 4 vCPU -> g6e.xlarge), then on-demand
PLAN = [("spot", "g6e.xlarge"), ("ondemand", "g6e.2xlarge"), ("ondemand", "g6e.xlarge")]
SPOT_MARGIN = 1.2            # the cap is charged at the live Spot price x 1.2 (it can move during a session)


def spot_price(itype, az):
    try:
        h = ec2.describe_spot_price_history(InstanceTypes=[itype], ProductDescriptions=["Linux/UNIX"], AvailabilityZone=az,
                                            StartTime=datetime.now(timezone.utc), MaxResults=1)["SpotPriceHistory"]
        return float(h[0]["SpotPrice"]) if h else None
    except ClientError:
        return None
AZS = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d"]
MIN_SESSION_MIN = 15
MARGIN_USD = 0.10
KEEP_WARM_MIN = 15          # idle box kept while a pending review would unlock GPU work
IDLE_STOP_MIN = 3           # idle box with nothing GPU left to do
BOOT_TIMEOUT_MIN = 40
ROOT = Path(__file__).resolve().parent
QUICK = Path(os.environ.get("VREA_QUICKTEST", ROOT.parent.parent / "infra" / "quicktest"))
ec2 = boto3.client("ec2", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)
_last_attempt = {}


def now():
    return datetime.now(timezone.utc)


def run_cost(r):
    if not r["launched_at"]:
        return 0.0
    end = r["ended_at"] or now()
    return max(0.0, (end - r["launched_at"]).total_seconds() / 3600 * float(r["hourly_usd"]))


def spent(pid):
    return round(sum(run_cost(r) for r in q("SELECT * FROM runs WHERE project_id=%s", pid)), 2)


def active_run():
    return one("SELECT * FROM runs WHERE state IN ('launching','booting','ready') ORDER BY id DESC LIMIT 1")


def families_needed(pid):
    rows = q("SELECT family, min(created_at) t FROM tasks WHERE project_id=%s AND state='queued' AND family<>'cpu' GROUP BY family ORDER BY t", pid)
    fams = [r["family"] for r in rows if r["family"] != "voice"]
    return fams


def user_data(run, hard_min, families):
    plan = ""
    if families:
        plan = subprocess.check_output(["python3", str(QUICK / "model_plan.py"), ",".join(families), str(QUICK / "models.json")]).decode().strip()
    boot = (QUICK / "gpu_bootstrap.sh").read_text()
    max_hours = max(1, math.ceil(hard_min / 60))
    for a, b in {"__BUCKET__": BUCKET, "__REGION__": REGION, "__IDLE_MIN__": "25", "__MAX_HOURS__": str(max_hours),
                 "__MODELS__": "none" if families else "none", "__MODEL_PLAN__": plan, "__HARD_MIN__": str(hard_min)}.items():
        boot = boot.replace(a, b)
    url = setting("public_url", "")
    worker = f"""
# ---- vrea platform worker (appended by the platform autoscaler) ----
cat >/etc/vrea-worker.env <<'WEOF'
SERVER_URL={url}
WORKER_TOKEN={run['token']}
RUN_ID={run['id']}
BUCKET={BUCKET}
WEOF
mkdir -p $ROOT/jobs3 && s5cmd cat s3://{BUCKET}/platform/worker_bundle.tar.gz | tar -xz -C $ROOT/jobs3
cat >/etc/systemd/system/vrea-worker.service <<'WEOF'
[Unit]
Description=vrea platform GPU worker
After=comfyui.service
[Service]
EnvironmentFile=/etc/vrea.env
EnvironmentFile=/etc/vrea-worker.env
Environment=HOME=/root HF_HOME=/mnt/nvme/hf PYTHONPATH=/mnt/nvme/jobs3:/mnt/nvme/jobs3/pipeline
WorkingDirectory=/mnt/nvme/jobs3
ExecStart=/mnt/nvme/ComfyUI/.venv/bin/python /mnt/nvme/jobs3/worker.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
WEOF
systemctl daemon-reload && systemctl enable --now vrea-worker
"""
    return boot + worker


def launch(pid):
    cap = float(one("SELECT cap_usd FROM projects WHERE id=%s", pid)["cap_usd"])
    remaining = cap - spent(pid) - MARGIN_USD
    fams = families_needed(pid)
    tok = secrets.token_urlsafe(24)
    run = one("INSERT INTO runs (project_id, state, token, families) VALUES (%s,'launching',%s,%s) RETURNING *", pid, tok, ",".join(fams))
    errors = []
    ami = ssm.get_parameter(Name="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id")["Parameter"]["Value"]
    for market, itype in PLAN:
        for az in AZS:
            price = PRICES[itype]
            if market == "spot":
                sp = spot_price(itype, az)
                if sp is None:
                    continue
                price = round(min(PRICES[itype], sp * SPOT_MARGIN), 3)
            hard_min = int(remaining / price * 60) - 2
            if hard_min < MIN_SESSION_MIN:
                continue
            opts = {"InstanceMarketOptions": {"MarketType": "spot", "SpotOptions": {"SpotInstanceType": "one-time",
                                                                                  "InstanceInterruptionBehavior": "terminate"}}} if market == "spot" else {}
            try:
                r = ec2.run_instances(
                    ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, IamInstanceProfile={"Name": PROFILE},
                    Placement={"AvailabilityZone": az}, InstanceInitiatedShutdownBehavior="terminate",
                    MetadataOptions={"HttpTokens": "required"}, UserData=user_data(run, hard_min, fams), **opts,
                    TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": f"vrea-gpu-p{pid}"}, {"Key": "project", "Value": TAG}]},
                                       {"ResourceType": "volume", "Tags": [{"Key": "project", "Value": TAG}]}])
                iid = r["Instances"][0]["InstanceId"]
                ex("UPDATE runs SET state='booting', instance_id=%s, itype=%s, az=%s, hourly_usd=%s, hard_min=%s, market=%s, launched_at=now() WHERE id=%s",
                   iid, itype, az, price, hard_min, market, run["id"])
                event(pid, f"GPU box {iid} launched ({market} {itype}, {az}, ${price:.2f}/h counted); loads {', '.join(fams) or 'voice only'}; "
                           f"hard stop in {hard_min} min (budget)")
                return True
            except ClientError as e:
                code = e.response["Error"]["Code"]; errors.append(f"{market} {itype}/{az}: {code}")
                if code in ("VcpuLimitExceeded", "MaxSpotInstanceCountExceeded", "InstanceLimitExceeded"):
                    break                                            # same limit in every AZ: next market/type
                if code not in ("InsufficientInstanceCapacity", "Unsupported", "SpotMaxPriceTooLow", "InsufficientCapacity"):
                    break
    ex("UPDATE runs SET state='failed', error=%s, ended_at=now() WHERE id=%s", "; ".join(errors)[:2000] or "budget too low", run["id"])
    if not errors:
        ex("UPDATE projects SET status='cap_reached', updated_at=now() WHERE id=%s", pid)
        event(pid, f"Budget left (${remaining:.2f}) is below a {MIN_SESSION_MIN}-minute GPU session. GPU work stopped (cap ${cap:.0f}).", "error")
    else:
        event(pid, "No GPU capacity right now; retrying in 3 minutes (" + "; ".join(errors[:4]) + ")", "warn")
    return False


def terminate(run, why):
    if run["instance_id"]:
        try:
            ec2.terminate_instances(InstanceIds=[run["instance_id"]])
        except ClientError as e:
            event(run["project_id"], f"terminate {run['instance_id']} failed: {e}", "error")
    ex("UPDATE runs SET state='terminated', ended_at=coalesce(ended_at, now()), error=coalesce(error,'') || %s WHERE id=%s", why, run["id"])
    ex("UPDATE tasks SET state='queued', run_id=NULL WHERE run_id=%s AND state='running'", run["id"])
    event(run["project_id"], f"GPU box {run['instance_id']} stopped: {why}")


def tick():
    """Called every ~10 s by the engine loop."""
    run = active_run()
    if run:
        pid = run["project_id"]; proj = one("SELECT * FROM projects WHERE id=%s", pid)
        cap = float(proj["cap_usd"]) if proj else 14
        if spent(pid) >= cap - MARGIN_USD:
            terminate(run, f"spending cap ${cap:.0f} reached"); ex("UPDATE projects SET status='cap_reached' WHERE id=%s", pid); return
        if run["instance_id"]:
            try:
                st = ec2.describe_instances(InstanceIds=[run["instance_id"]])["Reservations"][0]["Instances"][0]["State"]["Name"]
            except (ClientError, IndexError):
                st = "unknown"
            if st in ("shutting-down", "terminated", "stopped"):
                ex("UPDATE runs SET state='terminated', ended_at=coalesce(ended_at, now()) WHERE id=%s", run["id"])
                ex("UPDATE tasks SET state='queued', run_id=NULL WHERE run_id=%s AND state='running'", run["id"])
                event(pid, f"GPU box {run['instance_id']} has {st}"); return
        if run["state"] == "booting" and run["launched_at"] and (now() - run["launched_at"]).total_seconds() > BOOT_TIMEOUT_MIN * 60:
            terminate(run, "did not come up in time"); return
        if run["state"] == "ready":
            if run["last_seen"] and (now() - run["last_seen"]).total_seconds() > 300:
                terminate(run, "worker stopped reporting"); return
            busy = one("SELECT count(*) n FROM tasks WHERE run_id=%s AND state='running'", run["id"])["n"]
            queued = one("SELECT count(*) n FROM tasks WHERE project_id=%s AND state='queued' AND family<>'cpu'", pid)["n"]
            if busy == 0 and queued == 0:
                from engine import gpu_work_remaining
                _, future = gpu_work_remaining(pid)
                idle = (now() - (run["last_task_at"] or run["ready_at"] or now())).total_seconds() / 60
                limit = KEEP_WARM_MIN if future else IDLE_STOP_MIN
                if idle >= limit:
                    terminate(run, f"idle {idle:.0f} min" + (" (waiting on your review)" if future else ""))
        return
    # no box: launch for the oldest project with queued GPU work and budget left
    row = one("""SELECT t.project_id pid FROM tasks t JOIN projects p ON p.id=t.project_id
                 WHERE t.state='queued' AND t.family<>'cpu' AND p.status='running' ORDER BY t.created_at LIMIT 1""")
    if row:
        pid = row["pid"]
        if time.time() - _last_attempt.get(pid, 0) < 180:
            return
        _last_attempt[pid] = time.time()
        launch(pid)
