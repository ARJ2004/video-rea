"""pytest infra/quicktest/video/test_gpu_dispatch.py  (CPU only, no ComfyUI needed)"""
import importlib, json, os, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def fresh(tmp_path):
    os.environ["VREA_ROOT"] = str(tmp_path)
    import gpu_dispatch
    return importlib.reload(gpu_dispatch)


def test_family_of_real_graphs(tmp_path):
    gd = fresh(tmp_path); import comfy, talk
    assert gd.family_of(comfy.g_keyframe("p", ["a.png"], "x", 1)) == "edit"
    assert gd.family_of(comfy.g_i2v("a.png", "p", "x", 1)) == "video"
    assert gd.family_of({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors"}}}) == "image"
    assert gd.family_of(talk.g_talk("a.png", "a.wav", "p", "x", 81)) == "talk"   # Wan 2.1 + InfiniteTalk patch


def J(i, fam, t):
    return {"id": str(i), "family": fam, "t": t}


def test_pick_prefers_loaded_family(tmp_path):
    gd = fresh(tmp_path)
    p = [J(1, "edit", 0), J(2, "video", 1), J(3, "edit", 2)]
    assert gd.pick(p, "video", 10)["id"] == "2"           # stay on video
    assert gd.pick(p, "edit", 10)["id"] == "1"
    assert gd.pick(p, None, 10)["id"] == "1"              # edit has more waiting


def test_pick_starvation_guard(tmp_path):
    gd = fresh(tmp_path)
    p = [J(1, "edit", 0), J(2, "video", 950)]
    assert gd.pick(p, "video", 1000, max_wait=900)["id"] == "1"


def test_pick_skips_family_not_on_disk(tmp_path):
    gd = fresh(tmp_path)
    p = [J(1, "video", 0), J(2, "edit", 1)]
    assert gd.pick(p, "video", 10, ready={"edit"})["id"] == "2"
    assert gd.pick([J(1, "video", 0)], None, 10, ready={"edit"}) is None


def switches(seq):
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def test_affinity_cuts_model_switches(tmp_path):
    """Replay the shape of the 2026-11-03 run: scene 3 (video) and scene 4 / deities (edit) submitting alternately."""
    gd = fresh(tmp_path)
    arrivals = [("edit" if i % 2 else "video") for i in range(12)] + ["edit"] * 3 + ["video"] * 3
    fifo = switches(arrivals)
    ran = []

    def execute(graph):
        ran.append(gd.family_of(graph)); time.sleep(0.01); return []
    graphs = {"edit": {"u": {"inputs": {"unet_name": "qwen_image_edit_2509_fp8_e4m3fn.safetensors"}}},
              "video": {"u": {"inputs": {"unet_name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"}}}}
    ids = [gd.submit(graphs[f]) for f in arrivals]       # everything queued (streams waiting on the GPU)
    gd.serve(execute=execute, once=True)
    assert len(ran) == len(arrivals)
    assert switches(ran) <= 1 < fifo                      # FIFO: 13 switches; affinity: 1
    log = [json.loads(x) for x in open(tmp_path / "logs" / "gpu_jobs.jsonl")]
    assert sum(r["switch"] for r in log) == switches(ran)
    for i in ids:
        files, _ = gd.wait_result(i, timeout=1, poll=0.01)
        assert files == []


def test_client_server_roundtrip(tmp_path):
    gd = fresh(tmp_path)
    th = threading.Thread(target=gd.serve, kwargs={"execute": lambda g: [tmp_path / "out.png"]}, daemon=True); th.start()
    time.sleep(0.2)
    assert gd.available()
    files, sec = gd.wait_result(gd.submit({"u": {"inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors"}}}), timeout=5, poll=0.05)
    assert files == [tmp_path / "out.png"]


def test_util_report(tmp_path):
    import util_report
    lines = []
    for i in range(120):                                   # 10 min: 2 min idle boot, 6 min busy with a 90 s gap, idle tail
        s = i * 5; util = 0 if s < 120 else (0 if 300 <= s < 390 else 95) if s < 480 else 0
        lines.append(f"2026/11/04 10:{s // 60:02d}:{s % 60:02d}.000, {util}, {30000 if util else 500}, {300 if util else 60}")
    (tmp_path / "gpu.csv").write_text("\n".join(lines))
    (tmp_path / "gpu_jobs.jsonl").write_text("\n".join(json.dumps(j) for j in [
        {"family": "edit", "run_s": 15, "wait_s": 1, "switch": False, "ok": True},
        {"family": "video", "run_s": 30, "wait_s": 2, "switch": True, "ok": True}]))
    R = util_report.report(tmp_path)
    assert R["time_to_first_busy_min"] == 2.0
    assert R["model_switches"] == 1 and R["jobs"] == 2
    assert R["idle_gaps_s"][0] == 90
    assert 40 < R["gpu_busy_pct"] < 60
