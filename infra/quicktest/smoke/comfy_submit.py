import json, sys, time, urllib.request
B = "http://127.0.0.1:8188"
def call(p, data=None):
    req = urllib.request.Request(B + p, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))
for _ in range(120):
    try: call("/system_stats"); break
    except Exception: time.sleep(5)
ids = []
for j in json.load(open(sys.argv[1])):
    r = call("/prompt", j); ids.append(r["prompt_id"])
print("queued", len(ids), flush=True)
t0 = time.time()
while time.time() - t0 < 1800:
    h = call("/history")
    done = [i for i in ids if i in h]
    errs = [i for i in done if h[i].get("status", {}).get("status_str") == "error"]
    if len(done) == len(ids):
        print(f"done {len(done)} errors {len(errs)} in {time.time()-t0:.0f}s", flush=True)
        for i in errs: print(json.dumps(h[i]["status"])[:1500])
        break
    time.sleep(10)
