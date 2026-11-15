"""Scan YouTube Shorts channels and find what works: each Short's views against its own channel's median ("x_median"),
so a 20x outlier on a small channel counts as much as one on a big channel. Writes the data plus, per channel, a sheet of
the top-6 vs 6 typical thumbnails (for Shorts the thumbnail is usually the hook frame) to read by eye.

Public metadata only (yt-dlp --flat-playlist; needs www.youtube.com and i.ytimg.com). Video files cannot be fetched from
cloud machines (YouTube asks datacenter IPs to sign in); to measure cuts/sound, download the listed outliers on your own
machine and run reel_autopsy.py on them.

Usage:  python3 yt_scan.py --out <dir> [--limit 120] "Name=https://www.youtube.com/@handle/shorts" ...
        python3 yt_scan.py --out <dir> --search "ai horror story shorts" ...     (discovery: Shorts sorted by views)"""
import argparse, io, json, statistics as st, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path


def ytdlp(url, n):
    r = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(n), url], capture_output=True, text=True)
    try:
        return json.loads(r.stdout) or {}
    except Exception:
        print("failed:", url, r.stderr[-200:], file=sys.stderr); return {}


def scan_channel(name, url, n):
    d = ytdlp(url, n)
    es = [e for e in d.get("entries") or [] if e and e.get("view_count")]
    if not es:
        return None
    med = st.median(e["view_count"] for e in es)
    rows = [{"id": e["id"], "title": e.get("title"), "views": e["view_count"], "x_median": round(e["view_count"] / med, 2),
             "thumb": (sorted(e.get("thumbnails") or [], key=lambda t: (t.get("height") or 0) * (t.get("width") or 0)) or [{}])[-1].get("url")}
            for e in es]
    return {"name": name, "url": url, "subs": d.get("channel_follower_count"), "median_views": med, "shorts": rows}


def sheet(ch, path):
    from PIL import Image, ImageDraw
    top = sorted(ch["shorts"], key=lambda e: -e["views"])[:6]
    mid = sorted(ch["shorts"], key=lambda e: abs(e["x_median"] - 1))[:6]
    W, H = 270, 500
    img = Image.new("RGB", (6 * W, 2 * H + 30), (15, 15, 15)); dr = ImageDraw.Draw(img)
    dr.text((6, 6), f"{ch['name']}: row 1 = top 6 by views, row 2 = typical (about median)", fill=(240, 240, 240))
    for i, e in enumerate(top + mid):
        try:
            im = Image.open(io.BytesIO(urllib.request.urlopen(e["thumb"] or f"https://i.ytimg.com/vi/{e['id']}/oar2.jpg", timeout=20).read())).convert("RGB")
        except Exception:
            im = Image.new("RGB", (W, H - 20), (50, 50, 50))
        im.thumbnail((W, H - 20)); x, y = (i % 6) * W, 30 + (i // 6) * H
        img.paste(im, (x, y + 18)); dr.text((x + 4, y + 2), f"{e['views'] / 1e6:.1f}M x{e['x_median']}", fill=(250, 200, 80) if i < 6 else (190, 190, 190))
    img.save(path, quality=85)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channels", nargs="*", help="Name=URL of the channel's /shorts tab")
    ap.add_argument("--search", nargs="*", default=[], help="search queries (results sorted by view count)")
    ap.add_argument("--out", required=True); ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--no-sheets", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    res = {"channels": [], "search": []}
    for q in a.search:
        d = ytdlp("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&sp=CAM%253D", 60)
        for e in d.get("entries") or []:
            if e and e.get("view_count") and ("/shorts/" in (e.get("url") or "") or (e.get("duration") or 999) <= 180):
                res["search"].append({"q": q, "id": e["id"], "title": e.get("title"), "views": e["view_count"],
                                      "channel": e.get("channel"), "channel_url": e.get("channel_url")})
        print(f"search '{q}': {sum(r['q'] == q for r in res['search'])} shorts")
    for spec in a.channels:
        name, url = spec.split("=", 1)
        ch = scan_channel(name, url, a.limit)
        if not ch:
            print(f"{name}: nothing found"); continue
        res["channels"].append(ch)
        top = max(ch["shorts"], key=lambda e: e["views"])
        print(f"{name}: {len(ch['shorts'])} shorts, median {ch['median_views'] / 1e3:.0f}K, best {top['views'] / 1e6:.1f}M (x{top['x_median']}) {top['title'][:60]}")
        if not a.no_sheets:
            sheet(ch, out / f"{name.replace(' ', '_')}_sheet.jpg")
    (out / "yt_scan.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
