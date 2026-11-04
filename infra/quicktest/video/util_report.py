"""How well did a GPU session use the machine? Reads the logs the box syncs to s3://BUCKET/logs/<instance>/:
  gpu.csv        nvidia-smi every 5 s: timestamp, util %, memory MiB, power W   (vrea-gpustat service)
  gpu_jobs.jsonl one line per GPU job: family, wait_s, run_s, switch            (gpu_dispatch.py)
  models.log     when each model family finished copying                       (vrea-models service)
usage: python util_report.py <logs_dir>   -> prints a summary and writes util_report.json next to the logs"""
import csv, json, sys
from datetime import datetime
from pathlib import Path


def parse_ts(s):
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    raise ValueError(s)


def report(d):
    d = Path(d); R = {}
    rows = []
    if (d / "gpu.csv").exists():
        for r in csv.reader(open(d / "gpu.csv")):
            if len(r) >= 4:
                try:
                    rows.append((parse_ts(r[0]), float(r[1]), float(r[2]), float(r[3])))
                except ValueError:
                    continue
    if rows:
        span = (rows[-1][0] - rows[0][0]).total_seconds() or 1
        busy = [r for r in rows if r[1] >= 30]
        R["session_min"] = round(span / 60, 1)
        R["gpu_busy_pct"] = round(100 * len(busy) / len(rows), 1)          # samples with util >= 30 %
        R["gpu_util_mean"] = round(sum(r[1] for r in rows) / len(rows), 1)
        R["vram_peak_gib"] = round(max(r[2] for r in rows) / 1024, 1)
        R["time_to_first_busy_min"] = round(((busy[0][0] if busy else rows[-1][0]) - rows[0][0]).total_seconds() / 60, 1)
        gaps, start = [], None                                               # idle stretches >= 60 s after first work
        for r in rows[rows.index(busy[0]) if busy else 0:]:
            if r[1] < 10:
                start = start or r[0]
            elif start:
                g = (r[0] - start).total_seconds()
                if g >= 60:
                    gaps.append(round(g))
                start = None
        R["idle_gaps_s"] = gaps; R["idle_after_first_work_min"] = round(sum(gaps) / 60, 1)
    jobs = [json.loads(x) for x in open(d / "gpu_jobs.jsonl")] if (d / "gpu_jobs.jsonl").exists() else []
    if jobs:
        fam = {}
        for j in jobs:
            f = fam.setdefault(j["family"], {"n": 0, "run_s": 0.0, "wait_s": 0.0})
            f["n"] += 1; f["run_s"] += j["run_s"]; f["wait_s"] += j["wait_s"]
        R["jobs"] = len(jobs); R["model_switches"] = sum(1 for j in jobs if j.get("switch"))
        R["failed_jobs"] = sum(1 for j in jobs if not j.get("ok", True))
        R["per_family"] = {k: {"n": v["n"], "mean_run_s": round(v["run_s"] / v["n"], 1), "mean_wait_s": round(v["wait_s"] / v["n"], 1)}
                           for k, v in fam.items()}
    if (d / "models.log").exists():
        R["models_ready"] = [x.strip() for x in open(d / "models.log") if x.strip()]
    json.dump(R, open(d / "util_report.json", "w"), indent=2)
    return R


if __name__ == "__main__":
    print(json.dumps(report(sys.argv[1]), indent=2))
