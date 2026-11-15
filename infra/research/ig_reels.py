"""Study public Instagram reels: stats + caption from Instagram's official embed page (works logged out), the video file,
the autopsy measurements (reel_autopsy.py) and two frame sheets per reel: the hook (every 0.5 s for 8 s) and the body
(every 3 s). Read the sheets for what numbers cannot show (hook line, caption style, HUD, CTA).

Usage:  python3 ig_reels.py --out <dir> https://www.instagram.com/<user>/reel/<code>/ [...]
        (or a text file of URLs:  --list urls.txt)
Needs www.instagram.com and the Instagram video CDN host in the network allowlist. If the video host is refused, the
script prints it: add that exact host in the environment's network settings.
Only reels that are public and embeddable. No login, no private API."""
import argparse, json, re, subprocess, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0"}


def code_of(url):
    m = re.search(r"/(?:reel|reels|p)/([A-Za-z0-9_-]{6,})", url)
    return m.group(1) if m else url.strip()


def find(o, k):
    if isinstance(o, dict):
        if k in o:
            return o[k]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = find(v, k)
            if r is not None:
                return r
    return None


def embed(code):
    req = urllib.request.Request(f"https://www.instagram.com/reel/{code}/embed/captioned/", headers=UA)
    s = urllib.request.urlopen(req, timeout=30).read().decode("utf8", "replace")
    m = re.search(r'"contextJSON":"((?:[^"\\]|\\.)*)"', s)
    if not m:
        raise RuntimeError("embed has no data (private, removed, or embedding disabled)")
    ctx = json.loads(json.loads('"' + m.group(1) + '"'))
    g = lambda k: find(ctx, k)
    likes, comments = g("edge_liked_by") or g("edge_media_preview_like") or {}, g("edge_media_to_comment") or {}
    views = g("video_view_count") or g("video_play_count")
    return {"code": code, "owner": (g("owner") or {}).get("username"), "views": views, "likes": likes.get("count"),
            "comments": comments.get("count"), "duration_s": g("video_duration"), "taken_at": g("taken_at_timestamp"),
            "like_rate": round(likes["count"] / views, 3) if views and likes.get("count") else None,
            "comment_rate": round(comments["count"] / views, 4) if views and comments.get("count") else None,
            "caption": g("text"), "video_url": g("video_url")}


def sheets(mp4, out):
    tag = "drawtext=text='%{pts\\:hms}':x=4:y=4:fontsize=16:fontcolor=yellow:box=1:boxcolor=black@0.6"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", "8", "-i", mp4, "-vf", f"fps=2,scale=216:384,{tag},tile=8x2", "-frames:v", "1",
                    str(out / f"{Path(mp4).stem}_hook.jpg")], check=False)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "8", "-i", mp4, "-vf", f"fps=1/3,scale=216:384,{tag},tile=8x4", "-frames:v", "1",
                    str(out / f"{Path(mp4).stem}_body.jpg")], check=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*"); ap.add_argument("--list"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    urls = a.urls + (Path(a.list).read_text().split() if a.list else [])
    out = Path(a.out); (out / "reels").mkdir(parents=True, exist_ok=True)
    rows = []
    for u in urls:
        code = code_of(u)
        try:
            r = embed(code)
        except Exception as e:
            print(f"{code}: {e}", file=sys.stderr); continue
        mp4 = out / "reels" / f"{r['owner']}_{code}.mp4"
        if r["video_url"] and not mp4.exists():
            try:
                urllib.request.urlretrieve(r["video_url"], mp4)
            except Exception as e:
                host = re.match(r"https://([^/]+)", r["video_url"]).group(1)
                print(f"{code}: video download failed ({e}); allow host {host}", file=sys.stderr)
        if mp4.exists():
            sheets(str(mp4), out)
        r.pop("video_url"); rows.append(r)
        print(f"{r['owner']}/{code}: {r['views']} views, {r['likes']} likes ({r['like_rate']}), {r['comments']} comments, {r['duration_s']} s")
    (out / "reels.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    meta = {f"{r['owner']}_{r['code']}.mp4": {"page": r["owner"], "views": r["views"], "likes": r["likes"]} for r in rows}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    if any((out / "reels").glob("*.mp4")):
        subprocess.run([sys.executable, str(HERE / "reel_autopsy.py"), str(out / "reels"), "--out", str(out / "autopsy"),
                        "--scene", "0.25", "--meta", str(out / "meta.json")], check=False)


if __name__ == "__main__":
    main()
