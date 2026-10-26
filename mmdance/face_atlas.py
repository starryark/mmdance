"""Build expression atlases for a painted face (system Python: numpy, opencv-python, pillow).

For front-projected painted faces (typical of image-to-3D characters), expressions are texture
overlays, made the way 2D riggers (Live2D) animate painted eyes: the painting itself is reused.
  eyes : per eye, tiles [blink 1/3, blink 2/3, closed, smile ^^]. The painted lash band slides
         down to a target line between its rest position and the lower lid, keeping its
         thickness, over a lid filled with skin colour sampled right next to it; for the smile the
         cheek rises to meet the lowered lash so its natural arch becomes the ^^ line.
  mouth: tiles [a, i, u, e, o] x 3 openings, wa x 2, niyari (smirk), drawn with soft shading.
Every tile only carries the pixels that change (alpha = feathered difference mask), so no
patches or rectangles show. Optionally a cleaned copy of the painting is written first (grey
projection halos inpainted, a block at an eye corner repainted as sclera/skin).

The eye guide curves, mouth position and boxes come from [face.atlas] in project.toml (texture
pixels, measured on the painting). Run by face.py:
  python face_atlas.py project.toml face_texture.png key [preview_dir]
Writes Face_Eyes_Atlas.png, Face_Mouth_Atlas.png, face_atlas.json (+ the cleaned texture and
previews) to the project's textures folder.
"""
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config  # noqa: E402

SS = 4                   # supersampling of the drawn mouth shapes
EYES = {}                # filled from the config in setup()
SKIN_ABOVE = 34          # px of upper-lid skin above the lash band
CHEEK_BELOW = 46         # px of cheek skin below the lower lid (smile)
MOUTH_C = (0, 0)
MOUTH_RECT = (0, 0, 0, 0)
HALO_BOXES = []          # grey projection halos around strokes
CORNER_BOX = None        # an eye corner block repainted as sclera inside the opening, skin outside
CORNER_EYE = 'L'
LIP = (196, 74, 62)
LIP_DARK = (150, 58, 50)
MOUTH_TOP = (92, 30, 36)
MOUTH_BOT = (150, 52, 56)
TONGUE = (226, 128, 126)
TONGUE_HI = (244, 170, 166)
TEETH = (252, 248, 246)



def field_from(f, trusted, sigma):
    """Smooth colour field from trusted pixels, coarse to fine (finer scales win where supported)."""
    t = trusted.astype(np.float32)
    field = None
    for sg in (sigma * 8, sigma * 4, sigma * 2, sigma):
        num = cv2.GaussianBlur(f * t[..., None], (0, 0), sg)
        den = cv2.GaussianBlur(t, (0, 0), sg)[..., None]
        fs = num / np.maximum(den, 1e-6)
        if field is None:
            field = fs
            continue
        conf = np.clip(den * 5.0, 0, 1)
        field = fs * conf + field * (1 - conf)
    return field, None


def clean_base(img):
    """Remove grey projection halos: inpaint low-saturation light-grey pixels inside HALO_BOXES, and
    repaint the block at an eye corner (CORNER_BOX) as eye white inside the eye opening, skin outside."""
    f = img.astype(np.float32)
    mx, mn = f.max(2) / 255, f.min(2) / 255
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    H, W = mx.shape
    mask = np.zeros((H, W), np.uint8)
    for x0, y0, x1, y1 in HALO_BOXES:
        sub = (sat[y0:y1, x0:x1] < 0.09) & (mx[y0:y1, x0:x1] > 0.55) & (mx[y0:y1, x0:x1] < 0.965)
        mask[y0:y1, x0:x1] = sub.astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    out = cv2.cvtColor(cv2.inpaint(bgr, mask, 6, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB).astype(np.float32)
    if not CORNER_BOX:
        return np.clip(out, 0, 255).astype(np.uint8), mask > 0
    e = EYES[CORNER_EYE]
    xs = np.arange(W)
    lb, lo = curve(e['lash_bot'], xs), curve(e['lower'], xs)
    yy = np.arange(H)[:, None]
    opening = (yy > lb[None, :]) & (yy < lo[None, :])
    opening &= ~np.isnan(lb)[None, :] & ~np.isnan(lo)[None, :]
    x0, y0, x1, y1 = CORNER_BOX
    box = np.zeros((H, W), bool)
    box[y0:y1, x0:x1] = True
    keep = (mx < 0.42) | (sat > 0.38)                       # lash strokes, lid line, hair
    R, G, B = f[..., 0], f[..., 1], f[..., 2]
    sclera_ok = opening & (mx > 0.96) & (sat < 0.07) & ~box
    skin_ok = ~opening & (mx > 0.78) & (R - B > 12) & (R - G > 4) & ~box
    near = np.zeros((H, W), bool)
    near[y0 - 120:y1 + 120, x0 - 120:x1 + 200] = True
    scl, _ = field_from(f, sclera_ok & near, 10)
    skn, _ = field_from(f, skin_ok & near, 10)
    fix = box & ~keep
    fixed = np.where(opening[..., None], scl, skn)
    boxsoft = cv2.GaussianBlur(box.astype(np.float32), (0, 0), 7.0)          # fade out toward the box edges
    soft = (cv2.GaussianBlur(fix.astype(np.float32), (0, 0), 1.2) * np.clip(boxsoft * 2.0, 0, 1))[..., None]
    out = out * (1 - soft) + fixed * soft
    return np.clip(out, 0, 255).astype(np.uint8), (mask > 0) | fix


def curve(points, xs):
    """Smooth curve through points (monotone x), sampled at xs (NaN outside)."""
    p = np.array(points, float)
    ys = np.interp(xs, p[:, 0], p[:, 1], left=np.nan, right=np.nan)
    k = np.ones(9) / 9.0                     # light smoothing of the polyline
    valid = ~np.isnan(ys)
    if valid.sum() > 12:
        yv = ys[valid]
        yv = np.convolve(np.pad(yv, 4, mode='edge'), k, mode='valid')
        ys[valid] = yv
    return ys


def eye_state(img, e, p, smile=False, thick=1.0):
    """Slide the painted lash band down to lerp(rest, lower lid, p); fill the lid area it uncovers
    (and, for the smile, the eye below it) with smooth skin sampled right next to it."""
    H, W = img.shape[:2]
    out = img.astype(np.float32).copy()
    xs = np.arange(W)
    lt, lb, lo = curve(e['lash_top'], xs), curve(e['lash_bot'], xs), curve(e['lower'], xs)
    cols = np.nonzero(~np.isnan(lt) & ~np.isnan(lb) & ~np.isnan(lo))[0]
    x0, x1 = cols.min(), cols.max()
    span = np.clip(np.minimum(xs - x0, x1 - xs) / 24.0, 0, 1)
    span = span * span * (3 - 2 * span)
    f = img.astype(np.float32)
    # skin colours per column, smoothed across columns so fills carry no streaks
    lid = np.zeros((W, 3), np.float32)
    cheek = np.zeros((W, 3), np.float32)

    def skin_median(block, fallback):
        R, G, B = block[:, 0], block[:, 1], block[:, 2]
        ok = (block.max(1) > 200) & (R - B > 6) & (R - B < 70) & (R - G > 2)
        return np.median(block[ok], axis=0) if ok.sum() >= 3 else fallback
    glob_lid = skin_median(np.concatenate([f[int(lt[x]) - 34:int(lt[x]) - 5, x] for x in cols]), np.array([246, 222, 214], np.float32))
    glob_cheek = skin_median(np.concatenate([f[int(lo[x]) + 6:int(lo[x]) + 30, x] for x in cols]), glob_lid)
    for x in cols:
        lid[x] = skin_median(f[int(lt[x]) - 34:int(lt[x]) - 5, x], glob_lid)
        cheek[x] = skin_median(f[int(lo[x]) + 6:int(lo[x]) + 30, x], glob_cheek)
    for arr in (lid, cheek):
        seg = arr[x0:x1 + 1]
        pad = np.pad(seg, ((40, 40), (0, 0)), mode='edge')
        sm = cv2.GaussianBlur(pad[None], (0, 0), sigmaX=22)[0][40:-40]
        arr[x0:x1 + 1] = sm
    for x in cols:
        th = lb[x] - lt[x]
        open_h = max(lo[x] - lb[x], 0.0)
        target = lb[x] + (p * open_h + (4.0 if p >= 0.999 else 0.0)) * span[x]
        th_new = th * (1 - (1 - thick) * span[x])
        new_top = target - th_new
        y_a, y_b = int(np.floor(lt[x])) - 1, int(np.ceil(max(target, lo[x] + 6))) + 2
        col = f[:, x].copy()
        for y in range(y_a, y_b):
            if y < lt[x] - 3.5:
                continue
            if y <= new_top:                      # uncovered upper lid: skin, a soft shadow just above the lash
                d = new_top - y
                shade = 1.0 - 0.10 * np.exp(-d / 5.0)
                c = lid[x] * shade
                w_top = np.clip((y - (lt[x] - 3.5)) / 5.0, 0, 1)    # feather into the painting above
                c = c * w_top + f[y, x] * (1 - w_top)
            elif y <= target:                     # the lash band, resampled from its rest position
                t = (y - new_top) / max(th_new, 1e-3)
                sy = lt[x] + t * th
                i0 = int(np.floor(sy))
                fr = sy - i0
                c = f[i0, x] * (1 - fr) + f[min(i0 + 1, H - 1), x] * fr
            elif smile and y <= lo[x] + 6:        # smile: the cheek rises to meet the lash
                c = cheek[x]
            else:
                c = col[y]
            out[y, x] = c * span[x] + f[y, x] * (1 - span[x])
    return np.clip(out, 0, 255).astype(np.uint8)


def diff_alpha(new, orig, thr=6, grow=6, blur=5.0):
    d = np.abs(new.astype(int) - orig.astype(int)).sum(2)
    m = (d > thr).astype(np.uint8) * 255
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    a = cv2.GaussianBlur(m.astype(np.float32) / 255.0, (0, 0), blur)
    return np.clip(a * 1.15, 0, 1)


def to_tile(new, orig, rect):
    x0, y0, x1, y1 = rect
    a = diff_alpha(new, orig)
    return np.dstack([new[y0:y1, x0:x1], (a[y0:y1, x0:x1] * 255).astype(np.uint8)])


def eye_rect(e):
    pts = np.array(e['lash_top'] + e['lower'])
    return (int(pts[:, 0].min()) - 30, int(pts[:, 1].min()) - SKIN_ABOVE - 20,
            int(pts[:, 0].max()) + 30, int(pts[:, 1].max()) + CHEEK_BELOW + 24)


# ---------------------------------------------------------------- mouth
def inpaint(img, mask, radius=10):
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    out = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def catmull(pts, n=24):
    pts = np.asarray(pts, float)
    P = np.vstack([pts[0], pts, pts[-1]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(pts[-1])
    return np.array(out)


def stroke(draw, pts, width_fn, color, offset=(0, 0)):
    c = catmull(pts, 30)
    L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
    L /= max(L[-1], 1e-9)
    for p, s in zip(c, L):
        w = width_fn(s) * SS / 2
        x, y = (p[0] - offset[0]) * SS, (p[1] - offset[1]) * SS
        draw.ellipse([x - w, y - w, x + w, y + w], fill=color)


def mouth_tiles(img):
    x0, y0, x1, y1 = MOUTH_RECT
    line = np.zeros(img.shape[:2], np.uint8)
    cv2.rectangle(line, (MOUTH_C[0] - 140, MOUTH_C[1] - 14), (MOUTH_C[0] + 140, MOUTH_C[1] + 14), 255, -1)
    reddish = (img[..., 0].astype(int) - img[..., 2].astype(int) > 55) & (line > 0)
    hole = cv2.dilate(reddish.astype(np.uint8) * 255, np.ones((7, 7), np.uint8))
    skin = inpaint(img, hole)
    Wd, Hd = x1 - x0, y1 - y0
    base = Image.fromarray(skin[y0:y1, x0:x1]).resize((Wd * SS, Hd * SS), Image.LANCZOS)

    def shape(kind, k):
        cv = base.copy()
        d = ImageDraw.Draw(cv)
        cx, cy = (MOUTH_C[0] - x0) * SS, (MOUTH_C[1] - y0 + 5) * SS
        if kind == 'niyari':
            pts = [(MOUTH_C[0] - 112, MOUTH_C[1] + 3), (MOUTH_C[0] - 40, MOUTH_C[1] + 9), (MOUTH_C[0] + 40, MOUTH_C[1] + 3),
                   (MOUTH_C[0] + 98, MOUTH_C[1] - 14), (MOUTH_C[0] + 120, MOUTH_C[1] - 26)]
            stroke(d, pts, lambda s: 3.5 + 3.5 * math.sin(math.pi * s), LIP, offset=(x0, y0))
        else:
            dims = {'a': (180, 112), 'i': (206, 46), 'u': (86, 70), 'e': (178, 74), 'o': (118, 124), 'wa': (232, 160)}[kind]
            w = dims[0] * (0.74 + 0.26 * k) * SS
            h = max(12, dims[1] * k) * SS
            flat = {'a': 0.25, 'i': 0.55, 'u': 0.0, 'e': 0.4, 'o': 0.05, 'wa': 0.3}[kind]
            t = np.linspace(0, 2 * np.pi, 260)
            px = np.cos(t) * w / 2
            py = np.where(np.sin(t) < 0, np.sin(t) * h * (0.32 - flat * 0.2), np.sin(t) * h * 0.68)
            py += np.where(np.sin(t) < 0, -np.abs(np.cos(t)) ** 6 * h * 0.04, 0)
            poly = [(cx + a, cy + b) for a, b in zip(px, py)]
            top, bot = cy + py.min(), cy + py.max()
            # interior: vertical gradient, dark at the top (shadow of the upper lip)
            grad = Image.new('RGB', cv.size)
            gd = ImageDraw.Draw(grad)
            for yy in range(int(top), int(bot) + 1, 2):
                f = (yy - top) / max(bot - top, 1)
                col = tuple(int(MOUTH_TOP[i] * (1 - f) + MOUTH_BOT[i] * f) for i in range(3))
                gd.rectangle([0, yy, cv.size[0], yy + 2], fill=col)
            m = Image.new('L', cv.size, 0)
            ImageDraw.Draw(m).polygon(poly, fill=255)
            inner = grad.copy()
            idr = ImageDraw.Draw(inner)
            if kind in ('a', 'o', 'wa', 'e'):
                tw, tt = w * 0.6, h * 0.40
                idr.ellipse([cx - tw / 2, bot - tt * 1.05, cx + tw / 2, bot + tt * 0.55], fill=TONGUE)
                idr.ellipse([cx - tw * 0.22, bot - tt * 0.85, cx + tw * 0.12, bot - tt * 0.55], fill=TONGUE_HI)
            if kind in ('i', 'e', 'a', 'wa'):
                band = {'i': 0.5, 'e': 0.3, 'a': 0.2, 'wa': 0.17}[kind]
                ty = top - h * 0.02
                idr.rectangle([cx - w / 2, ty, cx + w / 2, ty + h * band], fill=TEETH)
                idr.rectangle([cx - w / 2, ty + h * band - 1.5 * SS, cx + w / 2, ty + h * band], fill=(226, 214, 214))
            cv = Image.composite(inner, cv, m)
            d = ImageDraw.Draw(cv)
            ring = poly + [poly[0]]
            for i in range(len(ring) - 1):
                ay, by = ring[i][1], ring[i + 1][1]
                upper = (ay + by) / 2 < cy
                lw = (5.0 if upper else 2.6) * SS * (0.8 + 0.2 * k)
                d.line([ring[i], ring[i + 1]], fill=LIP if upper else LIP_DARK, width=int(lw))
            # lower-lip highlight
            hl = [(cx - w * 0.16, bot + 7 * SS), (cx, bot + 9 * SS), (cx + w * 0.16, bot + 7 * SS)]
            d.line(hl, fill=(250, 214, 210), width=int(3 * SS))
        cv = cv.resize((Wd, Hd), Image.LANCZOS)
        new = img.copy()
        new[y0:y1, x0:x1] = np.array(cv)
        return to_tile(new, img, MOUTH_RECT)

    tiles = {'closed': np.zeros((Hd, Wd, 4), np.uint8)}
    for kind in 'aiueo':
        for li, k in enumerate((0.38, 0.68, 1.0)):
            tiles[f'{kind}{li + 1}'] = shape(kind, k)
    tiles['wa1'] = shape('wa', 0.7)
    tiles['wa2'] = shape('wa', 1.0)
    tiles['niyari'] = shape('niyari', 0)
    return MOUTH_RECT, tiles


def pack(tiles, order, cols):
    h, w = next(iter(tiles.values())).shape[:2]
    rows = (len(order) + cols - 1) // cols
    atlas = np.zeros((rows * h, cols * w, 4), np.uint8)
    for i, name in enumerate(order):
        r, c = divmod(i, cols)
        atlas[r * h:(r + 1) * h, c * w:(c + 1) * w] = tiles[name]
    return atlas, rows


def setup(cfg):
    global SKIN_ABOVE, CHEEK_BELOW, MOUTH_C, MOUTH_RECT, HALO_BOXES, CORNER_BOX, CORNER_EYE
    fa = cfg.face.atlas
    for k in ('L', 'R'):
        e = fa.eyes[k]
        EYES[k] = dict(lash_top=[tuple(p) for p in e.lash_top], lash_bot=[tuple(p) for p in e.lash_bot],
                       lower=[tuple(p) for p in e.lower])
    SKIN_ABOVE, CHEEK_BELOW = fa.skin_above, fa.cheek_below
    MOUTH_C, MOUTH_RECT = tuple(fa.mouth_center), tuple(fa.mouth_rect)
    HALO_BOXES = [tuple(b) for b in fa.halo_boxes]
    CORNER_BOX = tuple(fa.corner_box) if fa.corner_box else None
    CORNER_EYE = fa.corner_eye


def crop_box(rects, pad, W, H):
    r = np.array(rects)
    return (max(0, r[:, 0].min() - pad), max(0, r[:, 1].min() - pad), min(W, r[:, 2].max() + pad), min(H, r[:, 3].max() + pad))


def main(cfg_path, src, key, preview=None):
    cfg = config.load(cfg_path)
    setup(cfg)
    out_dir = cfg.textures()
    preview = preview or out_dir
    raw = np.array(Image.open(src).convert('RGB'))
    meta = {'size': raw.shape[1], 'key': key}
    if cfg.face.atlas.clean:
        img, halo = clean_base(raw)
        meta['clean'] = os.path.splitext(os.path.basename(src))[0] + '_clean.png'
        Image.fromarray(img).save(os.path.join(out_dir, meta['clean']))
        print('cleaned base: repainted', int((halo > 0).sum()), 'pixels')
    else:
        img = raw
    states = [('none', None), ('b1', dict(p=0.36)), ('b2', dict(p=0.70)), ('closed', dict(p=1.0, thick=0.62)),
              ('smile', dict(p=0.28, smile=True, thick=0.72))]
    eye_tiles, eye_meta = {}, {}
    for key, e in EYES.items():
        rect = eye_rect(e)
        eye_meta[key] = rect
        for name, kw in states:
            if kw is None:
                continue
            new = eye_state(img, e, **kw)
            eye_tiles[f'{key}_{name}'] = to_tile(new, img, rect)
    Hm = max(t.shape[0] for t in eye_tiles.values())
    Wm = max(t.shape[1] for t in eye_tiles.values())
    for k in list(eye_tiles):
        t = eye_tiles[k]
        pad = np.zeros((Hm, Wm, 4), np.uint8)
        pad[:t.shape[0], :t.shape[1]] = t
        eye_tiles[k] = pad
    for key in EYES:
        eye_tiles[f'{key}_none'] = np.zeros((Hm, Wm, 4), np.uint8)
    names = [s[0] for s in states]
    order = [f'{k}_{n}' for k in ('L', 'R') for n in names]
    atlas, rows = pack(eye_tiles, order, len(names))
    Image.fromarray(atlas).save(os.path.join(out_dir, 'Face_Eyes_Atlas.png'))
    meta['eyes'] = {k: dict(rect=[int(v) for v in r], tile_px=[Wm, Hm]) for k, r in eye_meta.items()}
    meta['eyes_atlas'] = dict(cols=len(names), rows=rows, order=order, states=names)
    mrect, mt = mouth_tiles(img)
    morder = ['closed'] + [f'{k}{i}' for k in 'aiueo' for i in (1, 2, 3)] + ['wa1', 'wa2', 'niyari']
    matlas, mrows = pack(mt, morder, 6)
    Image.fromarray(matlas).save(os.path.join(out_dir, 'Face_Mouth_Atlas.png'))
    meta['mouth'] = dict(rect=list(mrect))
    meta['mouth_atlas'] = dict(cols=6, rows=mrows, order=morder)
    with open(os.path.join(out_dir, 'face_atlas.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    # previews composited on the face
    base = Image.fromarray(img)
    H_, W_ = img.shape[:2]
    ebox = crop_box(list(eye_meta.values()), 30, W_, H_)
    ew = 1200
    eh = int(round(ew * (ebox[3] - ebox[1]) / (ebox[2] - ebox[0])))
    prev = []
    for n in names[1:]:
        im = base.copy()
        for key in EYES:
            x0, y0, x1, y1 = eye_meta[key]
            t = Image.fromarray(eye_tiles[f'{key}_{n}'][:y1 - y0, :x1 - x0])
            im.paste(t, (x0, y0), t)
        prev.append(im.crop(ebox).resize((ew, eh)))
    sheet = Image.new('RGB', (ew, eh * (len(prev) + 1)), 'black')
    sheet.paste(base.crop(ebox).resize((ew, eh)), (0, 0))
    for i, p in enumerate(prev):
        sheet.paste(p, (0, eh * (i + 1)))
    sheet.save(os.path.join(preview, 'atlas_eyes_preview.png'))
    mbox = crop_box([mrect], 40, W_, H_)
    mp = []
    for n in morder[1:]:
        im = base.copy()
        x0, y0, x1, y1 = mrect
        t = Image.fromarray(mt[n])
        im.paste(t, (x0, y0), t)
        mp.append(im.crop(mbox).resize((315, 240)))
    sm = Image.new('RGB', (315 * 6, 240 * ((len(mp) + 5) // 6)), 'black')
    for i, p in enumerate(mp):
        sm.paste(p, ((i % 6) * 315, (i // 6) * 240))
    sm.save(os.path.join(preview, 'atlas_mouth_preview.png'))
    print('atlas written', meta['eyes'], meta['mouth'])


if __name__ == '__main__':
    main(*sys.argv[1:5])
