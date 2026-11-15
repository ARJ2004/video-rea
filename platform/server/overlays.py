"""Text overlays drawn as separate layers (never inside generated artwork, so spelling is exact).
Storyboard: shot "overlays": [{"text": "line 1\\nline 2", "style": "hud|notebook|title|choice|label", "at": 0.5, "until": 6.0}]
(times relative to the shot; "until" omitted = to the end of the shot). The older single shot "overlay": {"text"} is a label."""
import re
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


STOP = set("a an the and or but so to of in on at for with from by is are was were be been it its this that these those i you he she we "
           "they me my your his her our their not no do did does have has had will would can could just then than as if into over".split())
ACCENT = {"amber": (246, 196, 83, 255), "red": (232, 72, 64, 255), "green": (88, 200, 120, 255), "cyan": (90, 200, 230, 255)}


def punch_chunks(caption, max_words=3, max_chars=20):
    """Short caption chunks (the reference reels show 2-4 words at a time), broken after punctuation when possible.
    Words wrapped in *asterisks* stay marked as the accent word."""
    out, cur = [], []
    for w in caption.split():
        if cur and (len(cur) >= max_words or len(" ".join(cur + [w]).replace("*", "")) > max_chars):
            out.append(" ".join(cur)); cur = []
        cur.append(w)
        if w.replace("*", "")[-1:] in ".!?;:" and len(cur) >= 2:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def punch_png(chunk, out, accent="amber"):
    """One caption chunk: uppercase, heavy, white with a dark outline, the key word in the accent colour (the word marked
    *like this*; otherwise the longest non-filler word of 4+ letters)."""
    words = chunk.split()
    marked = [i for i, w in enumerate(words) if "*" in w]
    words = [w.replace("*", "").upper() for w in words]
    if not marked:
        cands = [(len(w.strip(".,!?;:'\"")), i) for i, w in enumerate(words) if w.strip(".,!?;:'\"").lower() not in STOP and len(w) >= 4]
        marked = [max(cands)[1]] if cands else []
    im = Image.new("RGBA", (WD, HT), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    size = 78
    f = font("sansb", size)
    while d.textlength(" ".join(words), font=f) > WD - 140 and size > 48:
        size -= 4; f = font("sansb", size)
    total = d.textlength(" ".join(words), font=f)
    x, y = (WD - total) / 2, int(HT * 0.70)
    col = ACCENT.get(accent, ACCENT["amber"])
    for i, w in enumerate(words):
        d.text((x, y), w, font=f, fill=col if i in marked else (255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 235))
        x += d.textlength(w + " ", font=f)
    im.save(out); return out


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
    elif style == "vote":                  # end-of-episode audience vote card (the reference series' retention engine)
        # text lines: context line(s), the question (last plain line before buttons), "[A] [B]" buttons,
        # "~small footer", ">pill" call to action
        lines = [x for x in text.split("\n") if x.strip()]
        btn = next((x for x in lines if x.strip().startswith("[")), "")
        opts = re.findall(r"\[([^\]]+)\]", btn)
        foot = [r for x in lines if x.startswith("~") for r in wrap(d, x[1:].strip().upper(), font("sans", 28), 760)]
        pill = [x[1:].strip() for x in lines if x.startswith(">")]
        head = [x for x in lines if x not in (btn,) and not x.startswith(("~", ">"))]
        fq, fs, fb = font("sansb", 54), font("sans", 28), font("sansb", 44)
        rows = []
        for h in head:
            rows += wrap(d, h.upper(), fq, 760)
        h = 70 + 70 * len(rows) + (150 if opts else 0) + 46 * len(foot) + 40
        x0, y0 = 110, (HT - h) // 2 - 80
        d.rounded_rectangle((x0, y0, WD - x0, y0 + h), 26, fill=(246, 240, 226, 248))
        y = y0 + 44
        for i, r in enumerate(rows):
            c = (196, 72, 52, 255) if i == 0 and len(rows) > 1 else (30, 30, 34, 255)
            d.text(((WD - d.textlength(r, font=fq)) / 2, y), r, font=fq, fill=c); y += 70
        if opts:
            colors = [(44, 150, 84, 255), (214, 64, 56, 255), (60, 110, 200, 255)]
            bw = (WD - 2 * x0 - 80 - 30 * (len(opts) - 1)) / len(opts)
            for i, o in enumerate(opts):
                bx = x0 + 40 + i * (bw + 30)
                d.rounded_rectangle((bx, y + 20, bx + bw, y + 120), 18, fill=colors[i % 3])
                d.text((bx + (bw - d.textlength(o.upper(), font=fb)) / 2, y + 44), o.upper(), font=fb, fill=(255, 255, 255, 255))
            y += 150
        for ft in foot:
            d.text(((WD - d.textlength(ft.upper(), font=fs)) / 2, y + 6), ft.upper(), font=fs, fill=(90, 86, 80, 255)); y += 46
        for p_ in pill:
            fpw = d.textlength(p_.upper(), font=fb) + 100; px = (WD - fpw) / 2; py = y0 + h + 40
            d.rounded_rectangle((px, py, px + fpw, py + 96), 48, fill=(246, 196, 60, 255))
            d.text((px + 50, py + 22), p_.upper(), font=fb, fill=(30, 26, 20, 255))
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
