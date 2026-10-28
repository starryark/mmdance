"""Textures of the rebuilt face (system Python: numpy, opencv-python, pillow). Run by face_rebuild.py:

  python face_textures.py project.toml painting.png region.json key

All three images keep the painting's layout (its exact front projection), so every part of the new
face is UV-mapped the same way:
* Face_Skin.png    the painting with its face region (the polygon in region.json) replaced by clean
                   skin: a smooth field from the skin pixels (blush kept), without the projected hair
                   strands, the painted eyes, the mouth line and the halos. Only the small painted nose
                   stays, moved onto the face's centre line. Outside the region (earrings and other
                   face-material pieces) the painting is unchanged.
* Face_EyeLid.png  that skin with the eye's painted lash band and lower lid line on it, from the clean
                   eye (`face.atlas.eyes.R`; the other eye is its mirror). The band's colour runs a few
                   pixels past its lower edge, and the lid line's past its upper edge, so the lid layers'
                   edges never pick up the white of the eye.
* Face_EyeBall.png (RGBA) the eye's opening (white, iris, highlights), carried on under the lids by
                   inpainting, alpha = the opening grown by `eyeball_grow` px.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from mmdance import config, face_atlas  # noqa: E402


def fill_polygon(shape, pts):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(np.asarray(pts)).astype(np.int32)], 255)
    return m > 0


def skin_field(f, trusted, sigmas=(96, 48, 24, 12, 6)):
    """Smooth colour field from the trusted pixels, coarse to fine over the median skin colour (no
    holes where no skin is near: the forehead under the bangs)."""
    t = trusted.astype(np.float32)
    field = np.broadcast_to(np.median(f[trusted], axis=0), f.shape).astype(np.float32).copy()
    for sg in sigmas:
        num = cv2.GaussianBlur(f * t[..., None], (0, 0), sg)
        den = cv2.GaussianBlur(t, (0, 0), sg)[..., None]
        conf = np.clip(den * 4.0, 0, 1)
        field = num / np.maximum(den, 1e-6) * conf + field * (1 - conf)
    return field


def eye_curves(e, W):
    xs = np.arange(W)
    top, bot, low = (face_atlas.curve(e[k], xs) for k in ('lash_top', 'lash_bot', 'lower'))
    return xs, top, bot, low


def main(cfg_path, src, region_path, key):
    cfg = config.load(cfg_path)
    fr = cfg.stage.face_rebuild
    face_atlas.setup(cfg)
    raw = np.array(Image.open(src).convert('RGB'))
    paint = face_atlas.clean_base(raw)[0] if cfg.face.atlas.clean else raw
    H, W = paint.shape[:2]
    with open(region_path) as f:
        region = json.load(f)
    f = paint.astype(np.float32)
    mx, mn = f.max(2) / 255, f.min(2) / 255
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    R, G, B = f[..., 0], f[..., 1], f[..., 2]

    # --- clean skin: a smooth field from trusted skin pixels
    xs, top, bot, low = eye_curves(face_atlas.EYES['R'], W)
    _, topL, botL, lowL = eye_curves(face_atlas.EYES['L'], W)
    yy = np.arange(H)[:, None]
    near_eyes = np.zeros((H, W), bool)
    for t, l in ((top, low), (topL, lowL)):
        ok = ~np.isnan(t) & ~np.isnan(l)
        near_eyes |= ok[None, :] & (yy > (t - 40)[None, :]) & (yy < (l + 40)[None, :])
    near_eyes = cv2.dilate(near_eyes.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
    mx0, my0 = fr.mouth_center_px
    excl = near_eyes.copy()
    excl[my0 - 40:my0 + 40, mx0 - 170:mx0 + 170] = True
    nx0, ny0, nx1, ny1 = fr.nose_box
    excl[ny0:ny1, nx0:nx1] = True
    skinlike = (mx > fr.skin_min_value) & (sat > fr.skin_min_sat) & (sat < fr.skin_max_sat) & (R - B > 10) & (R >= G)
    strokes = cv2.dilate((~skinlike).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0   # strands, lines and their fringes
    trusted = ~strokes & ~excl
    field = skin_field(f, trusted)
    region_mask = fill_polygon((H, W), region['polygon_px'])
    g = 2 * fr.region_grow_px + 1                           # past the outline too: the painting's jaw-line highlight
    soft = cv2.GaussianBlur(cv2.dilate(region_mask.astype(np.uint8), np.ones((g, g), np.uint8)).astype(np.float32), (0, 0), 4.0)[..., None]
    skin = f * (1 - soft) + field * soft
    # the painted nose, moved onto the centre line
    sx, sy = fr.nose_shift_px
    nb = np.zeros((H, W), np.float32)
    nb[ny0:ny1, nx0:nx1] = 1.0
    nb = cv2.GaussianBlur(nb, (0, 0), 6.0)
    diff = np.clip(np.abs(f - field).max(2) / 30.0, 0, 1) * nb
    M = np.float32([[1, 0, sx], [0, 1, sy]])
    nose = cv2.warpAffine(f, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
    na = cv2.warpAffine(diff, M, (W, H))[..., None]
    skin = skin * (1 - na) + nose * na
    Image.fromarray(np.clip(skin, 0, 255).astype(np.uint8)).save(cfg.textures('Face_Skin.png'))

    # --- lids: the clean eye's lash band and lower lid line over that skin
    ok = ~np.isnan(top) & ~np.isnan(bot) & ~np.isnan(low)
    band = ok[None, :] & (yy > (top - 6)[None, :]) & (yy < (bot + 6)[None, :])
    line = ok[None, :] & (np.abs(yy - low[None, :]) < 9)
    feat = cv2.GaussianBlur((band | line).astype(np.float32), (0, 0), 2.0)[..., None]
    lid = field * (1 - feat) + f * feat
    run = fr.lid_edge_run
    cols = np.nonzero(ok)[0]
    # per column: the band's colour just inside its lower edge, the lid line's darkest pixel; smoothed along x
    bc = np.array([f[int(round(bot[x])) - 3, x] for x in cols])
    lc = np.array([min((f[int(round(low[x])) + d, x] for d in range(-4, 5)), key=lambda c: c.sum()) for x in cols])
    k = np.ones(15) / 15
    bc = np.stack([np.convolve(np.pad(bc[:, i], 7, mode='edge'), k, 'valid') for i in range(3)], 1)
    lc = np.stack([np.convolve(np.pad(lc[:, i], 7, mode='edge'), k, 'valid') for i in range(3)], 1)
    for j, x in enumerate(cols):
        b, l = int(round(bot[x])), int(round(low[x]))
        lid[b - 1:b + run, x] = bc[j]                         # band colour past its lower edge
        lid[l - run:l + 1, x] = lc[j]                         # lid line colour past its upper edge
    Image.fromarray(np.clip(lid, 0, 255).astype(np.uint8)).save(cfg.textures('Face_EyeLid.png'))

    # --- eyeball: the opening, carried on under the lids
    xin, xout = fr.opening_x_px                              # the white ends here (hair strands past it)
    okx = ok & (xs >= xin) & (xs <= xout)
    opening = okx[None, :] & (yy > bot[None, :]) & (yy < (low - fr.lower_inset_px)[None, :])
    known = okx[None, :] & (yy > (bot + 2)[None, :]) & (yy < (low - fr.lower_inset_px)[None, :])
    grow = cv2.dilate(opening.astype(np.uint8), np.ones((121, 121), np.uint8)) > 0
    unknown = (grow & ~known).astype(np.uint8) * 255
    ball = face_atlas.inpaint(paint, unknown, 10).astype(np.float32)
    g = fr.eyeball_grow
    alpha = cv2.dilate(opening.astype(np.uint8) * 255, np.ones((2 * g + 1, 2 * g + 1), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.5)
    rgba = np.dstack([np.clip(ball, 0, 255).astype(np.uint8), alpha])
    Image.fromarray(rgba, 'RGBA').save(cfg.textures('Face_EyeBall.png'))
    with open(cfg.textures('face_rebuild.json'), 'w') as fo:
        json.dump({'key': key}, fo)
    # preview: the eye region of each image
    x0, x1 = int(np.nanmin(np.where(ok, xs, np.nan))) - 60, int(np.nanmax(np.where(ok, xs, np.nan))) + 60
    y0, y1 = int(np.nanmin(top[ok])) - 80, int(np.nanmax(low[ok])) + 80
    tiles = [Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)[y0:y1, x0:x1]) for a in (paint, lid, ball)]
    chk = np.full((y1 - y0, x1 - x0, 3), 60, np.uint8)
    chk[(np.add.outer(np.arange(y1 - y0) // 12, np.arange(x1 - x0) // 12) % 2) == 0] = 110
    bt = Image.fromarray(chk)
    bt.paste(Image.fromarray(rgba[y0:y1, x0:x1], 'RGBA'), (0, 0), Image.fromarray(rgba[y0:y1, x0:x1], 'RGBA'))
    tiles.append(bt)
    sheet = Image.new('RGB', ((x1 - x0) * 2, (y1 - y0) * 2))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 2) * (x1 - x0), (i // 2) * (y1 - y0)))
    sheet.save(cfg.textures('face_rebuild_eye_preview.png'))
    Image.fromarray(np.clip(skin, 0, 255).astype(np.uint8)).resize((1024, 1024)).save(cfg.textures('face_rebuild_skin_preview.png'))
    print('face textures written:', cfg.textures())


if __name__ == '__main__':
    main(*sys.argv[1:5])
