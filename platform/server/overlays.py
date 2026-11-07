"""Text overlays drawn as separate layers (never inside generated artwork, so spelling is exact).
Storyboard: shot "overlays": [{"text": "line 1\\nline 2", "style": "hud|notebook|title|choice|label", "at": 0.5, "until": 6.0}]
(times relative to the shot; "until" omitted = to the end of the shot). The older single shot "overlay": {"text"} is a label."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WD, HT = 1080, 1920
N = "/usr/share/fonts/truetype/noto/"
FONTS = {"sans": N + "NotoSans-Regular.ttf", "sansb": N + "NotoSans-Bold.ttf", "mono": N + "NotoSansMono-Regular.ttf",
         "serif": N + "NotoSerif-Regular.ttf", "serifb": N + "NotoSerif-Bold.ttf", "deva": N + "NotoSansDevanagari-Bold.ttf"}


def font(kind, size):
    p = FONTS[kind]
    if not Path(p).exists():
        p = FONTS["sans"] if Path(FONTS["sans"]).exists() else FONTS["deva"]
    return ImageFont.truetype(p, size)


def wrap(d, text, f, width):
    out = []
    for para in text.split("\n"):
        words, cur = para.split(), ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= width or not cur:
                cur = t
            else:
                out.append(cur); cur = w
        out.append(cur)
    return out


def card(text, style, out):
    im = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if style == "hud":                     # small game-like status line at the top
        f = font("mono", 40); lines = wrap(d, text, f, WD - 160)
        h = 34 + 54 * len(lines); d.rounded_rectangle((60, 120, WD - 60, 120 + h), 14, fill=(8, 14, 30, 170), outline=(240, 200, 90, 200), width=2)
        for i, l in enumerate(lines):
            d.text((90, 136 + 54 * i), l, font=f, fill=(245, 225, 170, 255))
    elif style == "notebook":              # old paper card with a title and numbered lines
        lines = text.split("\n"); title, body = lines[0], lines[1:]
        ft, fb = font("serifb", 50), font("serif", 40)
        rows = []
        for l in body:
            rows += wrap(d, l, fb, 820)
        h = 130 + 58 * len(rows) + 40; y0 = (HT - h) // 2 - 120
        d.rounded_rectangle((70, y0, WD - 70, y0 + h), 18, fill=(236, 226, 196, 242), outline=(120, 96, 60, 255), width=3)
        d.text(((WD - d.textlength(title, font=ft)) / 2, y0 + 36), title, font=ft, fill=(60, 36, 20, 255))
        for i, l in enumerate(rows):
            d.text((120, y0 + 120 + 58 * i), l, font=fb, fill=(40, 30, 24, 255))
    elif style == "choice":                # audience choice buttons near the bottom
        f = font("sansb", 46); items = [x for x in text.split("\n") if x.strip()]
        for i, l in enumerate(items):
            w = d.textlength(l, font=f) + 120; x0 = (WD - w) / 2; y0 = HT - 560 + i * 150
            d.rounded_rectangle((x0, y0, x0 + w, y0 + 104), 52, fill=(10, 16, 34, 215), outline=(240, 200, 90, 255), width=4)
            d.text((x0 + 60, y0 + 24), l, font=f, fill=(250, 232, 180, 255))
    else:                                  # title / label: centred glowing text
        big = style == "title"
        kind = "deva" if any("ऀ" <= ch <= "ॿ" for ch in text) else ("sansb" if big else "sansb")
        f = font(kind, 66 if big else 96); lines = wrap(d, text, f, WD - 120)
        lh = (86 if big else 118); y0 = (HT * 0.40 if big else HT * 0.12)
        glow = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); g = ImageDraw.Draw(glow)
        for i, l in enumerate(lines):
            x = (WD - d.textlength(l, font=f)) / 2
            g.text((x, y0 + lh * i), l, font=f, fill=(246, 196, 83, 255)); d.text((x, y0 + lh * i), l, font=f, fill=(255, 238, 190, 255))
        im = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12)), im)
    im.save(out); return out


def shot_overlays(shot, t0, L, work, label_png):
    """[(png, start, end)] in clip time. label_png renders the legacy single-line label (Devanagari-aware)."""
    out, w = [], Path(work)
    ov = shot.get("overlay")
    if ov and ov.get("text"):
        out.append((label_png(ov["text"], w / f"lab_{shot['id']}.png"), t0 + 0.3, t0 + L - 0.2))
    for i, o in enumerate(shot.get("overlays", [])):
        a = t0 + float(o.get("at", 0.3)); b = t0 + (float(o["until"]) if o.get("until") is not None else L - 0.1)
        out.append((card(o["text"], o.get("style", "label"), w / f"ov_{shot['id']}_{i}.png"), a, min(b, t0 + L)))
    return out
