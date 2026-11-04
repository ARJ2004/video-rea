"""Deterministic Tridev group frame: cut each deity out of his OWN sheet (GrabCut on the plain cream background) and
place him at a fixed spot on a cosmic background with a drawn halo. No multi-reference generation, so the three
deities cannot blend into each other. Also returns the exact 9:16 close-shot window around each deity.
usage: compose(sheets: {k: path}, bg: path|None, out: path) -> {k: (x0, y0, x1, y1)} windows in out-pixels"""
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter

W, H = 720, 1280
# where each deity's cut-out goes: (centre x, bottom y, target height) - Shiva top centre (seated),
# Brahma lower left (on lotus), Vishnu lower right (standing)
SLOT = {"shiva": (360, 610, 520), "brahma": (175, 1240, 500), "vishnu": (560, 1245, 590)}
GOLD = (246, 196, 83)


def cutout(path):
    im = cv2.imread(str(path)); h, w = im.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    # background colour model: border strip is certain background
    b = 12; mask[:b] = mask[-b:] = cv2.GC_BGD; mask[:, :b] = mask[:, -b:] = cv2.GC_BGD
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    d = np.linalg.norm(lab - np.median(border, 0), axis=2)
    mask[d > 28] = cv2.GC_PR_FGD; mask[d > 60] = cv2.GC_FGD
    mask[:b] = mask[-b:] = cv2.GC_BGD; mask[:, :b] = mask[:, -b:] = cv2.GC_BGD
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(im, mask, None, bg, fg, 5, cv2.GC_INIT_WITH_MASK)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    # keep the big connected pieces (body + held objects), drop specks and stray text
    n, lbl, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 0.004 * h * w:
            keep[lbl == i] = 255
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    grey = (hsv[..., 1] < 40) & (keep > 0)
    rows = np.where(keep.sum(1) > 0)[0]
    for r in rows[::-1]:                                       # floor band: mostly grey, wide rows at the bottom
        if grey[r].sum() > 0.6 * max(1, (keep[r] > 0).sum()):
            keep[r] = 0
        else:
            break
    ys, xs = np.where(keep > 0)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    alpha = Image.fromarray(keep).filter(ImageFilter.GaussianBlur(1.2))
    rgba = Image.open(path).convert("RGB"); rgba.putalpha(alpha)
    return rgba.crop((x0, y0, x1, y1))


def halo(canvas, cx, cy, r):
    g = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(g)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD + (150,))
    g = g.filter(ImageFilter.GaussianBlur(r * 0.35))
    ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ring)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 236, 180, 255), width=7)
    ring = ring.filter(ImageFilter.GaussianBlur(2.5))
    canvas.alpha_composite(g); canvas.alpha_composite(ring)


def compose(sheets, bg, out):
    if bg:
        canvas = Image.open(bg).convert("RGB").resize((W, H)).convert("RGBA")
    else:
        y = np.linspace(0, 1, H)[:, None, None]
        canvas = Image.fromarray((np.array([60, 30, 10]) * (1 - y) + np.array([120, 70, 20]) * y).repeat(W, 1).astype(np.uint8)).convert("RGBA")
    boxes = {}
    for k in ("shiva", "brahma", "vishnu"):
        cx, by, th = SLOT[k]
        c = cutout(sheets[k]); s = th / c.height
        c = c.resize((max(1, int(c.width * s)), th), Image.LANCZOS)
        if c.width > 340:                                   # keep the lower pair from overlapping
            s2 = 340 / c.width; c = c.resize((340, int(c.height * s2)), Image.LANCZOS)
        x, y = int(cx - c.width / 2), by - c.height
        x = min(max(x, 4), W - c.width - 4)
        halo(canvas, x + c.width // 2, y + int(c.height * 0.36), int(max(c.width, c.height * 0.62) * 0.52))
        # soft contact shadow so they sit in the light rather than float on it
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse((x + c.width * 0.15, by - 14, x + c.width * 0.85, by + 10), fill=(40, 20, 0, 110))
        canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        canvas.alpha_composite(c, (x, y))
        boxes[k] = (x, y, x + c.width, y + c.height)
    canvas.convert("RGB").save(out)
    return {k: window(b) for k, b in boxes.items()}


def window(b, m=1.12):
    """9:16 close-shot window around a deity box, clamped to the frame."""
    x0, y0, x1, y1 = b; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = min(H, max((y1 - y0) * m, (x1 - x0) * m * 16 / 9)); w = h * 9 / 16
    if w > W: w = W; h = w * 16 / 9
    x = min(max(cx - w / 2, 0), W - w); y = min(max(cy - h / 2, 0), H - h)
    return tuple(int(round(v)) for v in (x, y, x + w, y + h))


if __name__ == "__main__":
    import sys, json
    sh = dict(a.split("=") for a in sys.argv[1].split(","))
    print(json.dumps(compose(sh, sys.argv[2] if sys.argv[2] != "-" else None, sys.argv[3])))
