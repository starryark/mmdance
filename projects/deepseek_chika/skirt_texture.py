"""Clean up the skirt's front panel in the body texture (system Python: numpy, opencv, pillow, scipy).

The texture projected from the concept sheets left the blue front panel of the skirt as smeared
streaks and blotches where the concept has crisp vertical pinstripes. The skirt is unrolled into a
panorama of its outer surface (angle round the skirt axis x height), where the UV islands' seams
disappear; the panel is redrawn there as its own smooth shading plus pinstripes at constant angle
(they run straight down the fabric and converge toward the waist), keeping the gold embroidery,
bows and trims of the original; then every texel of the panel, and the gutter texels next to it
(so filtering shows no seams), takes the new colour.

  blender -b character.blend --python export_skirt_uv.py -- project.toml skirt_uv.npz
  python skirt_texture.py skirt_uv.npz textures/Deepseek_Body_D_clean.png [preview.png]
"""
import sys

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None
PHI0, PHI1 = -np.pi, np.pi
Z0, Z1 = 0.06, 0.62
WP, HP = 4096, 1824
PANEL_PHI = 40.0          # degrees either side of the front: where the blue panel can be
STRIPE_PX = 32            # pinstripe spacing in panorama pixels (2.8 degrees)


def raster(P, W, H, grow=0.0):
    """Texels inside a UV-space triangle (pixel coordinates P), with barycentric weights."""
    x0, y0 = np.floor(P.min(0) - grow).astype(int)
    x1, y1 = np.ceil(P.max(0) + grow).astype(int)
    xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1 + 1, W)), np.arange(max(y0, 0), min(y1 + 1, H)))
    px = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
    T = np.array([P[1] - P[0], P[2] - P[0]]).T
    if abs(np.linalg.det(T)) < 1e-9:
        return None, None
    b = np.linalg.solve(T, (px - P[0]).T).T
    w = np.c_[1 - b.sum(1), b]
    inside = (w >= -1e-3).all(1)
    return ys.ravel()[inside] * W + xs.ravel()[inside], w[inside]


def uv_px(uv, W, H):
    return np.array([[u * W, (1 - v) * H] for u, v in uv])


def texels(d, W, H):
    """Covered texels of the skirt's outward-facing, non-apron triangles: index and pano coords."""
    idx, pos = [], []
    for tri, uv, f, a in zip(d['tris'], d['uvs'], d['facing'], d['apron']):
        if f < 0.2 or a >= 0.5:
            continue
        ti, w = raster(uv_px(uv, W, H), W, H)
        if ti is None:
            continue
        idx.append(ti)
        pos.append(w @ tri)
    idx, pos = np.concatenate(idx), np.concatenate(pos)
    ax = d['axis']
    phi = np.arctan2(pos[:, 0] - ax[0], -(pos[:, 1] - ax[1]))
    r = np.hypot(pos[:, 0] - ax[0], pos[:, 1] - ax[1])
    u = (phi - PHI0) / (PHI1 - PHI0) * WP
    v = (Z1 - pos[:, 2]) / (Z1 - Z0) * HP
    return idx, u, v, r


def coverage(d, W, H):
    cov = np.zeros(W * H, bool)
    for uv in d['all_uv']:
        ti, _ = raster(uv_px(uv, W, H), W, H)
        if ti is not None:
            cov[ti] = True
    return cov.reshape(H, W)


def panorama(flat, idx, u, v, r):
    """Outermost surface colour per panorama pixel, holes filled by normalised convolution."""
    order = np.argsort(r)
    pu, pv = u.astype(int).clip(0, WP - 1)[order], v.astype(int).clip(0, HP - 1)[order]
    pano = np.zeros((HP, WP, 3), np.float32)
    have = np.zeros((HP, WP), np.float32)
    pano[pv, pu] = flat[idx[order]]
    have[pv, pu] = 1.0
    acc = cv2.GaussianBlur(pano * have[..., None], (0, 0), 1.3)
    w = cv2.GaussianBlur(have, (0, 0), 1.3)
    return acc / np.maximum(w[..., None], 1e-4), w > 0.05


def panel_mask(pano, valid):
    """The blue panel's fabric (not its gold, bows or dark trims), soft-edged."""
    hsv = cv2.cvtColor((pano * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    h, s, val = hsv[..., 0] * 2, hsv[..., 1] / 255, hsv[..., 2] / 255
    blue = (h > 205) & (h < 250) & (s > 0.25) & (val > 0.42) & valid
    phi = np.degrees(np.linspace(PHI0, PHI1, WP, endpoint=False))[None, :].repeat(HP, 0)
    blue &= np.abs(phi) < PANEL_PHI
    blue = cv2.morphologyEx(blue.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    lab, n = ndimage.label(blue)
    if n:
        sizes = ndimage.sum(blue, lab, range(1, n + 1))
        blue = (lab == 1 + int(np.argmax(sizes)))
    blue = ndimage.binary_fill_holes(blue).astype(np.uint8)      # smears inside the panel are redrawn too
    # keep the gold strokes (even their thin, half-blue edges: warmer than the panel but not white)
    # and anything dark (outlines, trims) of the original; white smears are redrawn
    warm = pano[..., 0] - pano[..., 2]

    def step(e0, e1, x):
        t = np.clip((x - e0) / (e1 - e0), 0, 1)
        return t * t * (3 - 2 * t)
    dark = 1 - step(0.26, 0.34, val)
    lab, n = ndimage.label(dark > 0.5)
    if n:                                    # small dark specks are smear edges; trims and outlines are long
        sizes = ndimage.sum(np.ones_like(dark), lab, range(1, n + 1))
        dark[np.isin(lab, 1 + np.nonzero(sizes < 400)[0])] = 0
    keep = np.maximum(step(-0.26, -0.12, warm) * (1 - step(0.68, 0.78, pano.min(2))), dark)
    keep = cv2.dilate(keep, np.ones((3, 3), np.uint8))
    m = cv2.GaussianBlur(blue.astype(np.float32), (0, 0), 1.5) * (1 - keep)
    return m, blue.astype(bool)


def redraw(pano, valid, soft, region):
    """Smooth shading of the panel plus pinstripes at constant angle."""
    m = region.astype(np.float32)
    acc = cv2.GaussianBlur(pano * m[..., None], (0, 0), 28)
    w = cv2.GaussianBlur(m, (0, 0), 28)
    base = acc / np.maximum(w[..., None], 1e-4)
    # tame the blotches: pull the shading toward its row average (keeps the light falloff down the panel)
    rows = np.nanmedian(np.where(region[..., None], pano, np.nan), axis=1)
    rows = np.where(np.isnan(rows), np.nanmedian(rows, axis=0), rows)
    rows = ndimage.gaussian_filter1d(rows, 25, axis=0)
    base = 0.55 * base + 0.45 * rows[:, None, :]
    x = np.arange(WP, dtype=np.float32)
    d = np.abs(((x - WP / 2) / STRIPE_PX + 0.5) % 1.0 - 0.5) * STRIPE_PX       # px to the nearest stripe
    line = np.exp(-0.5 * (d / 0.9) ** 2)[None, :, None]
    stripe = np.clip(base * 1.32 + 0.05, 0, 1)
    new = base * (1 - 0.65 * line) + stripe * 0.65 * line
    return pano * (1 - soft[..., None]) + new * soft[..., None]


def main(npz, out, preview=None):
    d = np.load(npz)
    img = np.asarray(Image.open(str(d['image'])).convert('RGB'))
    H, W = img.shape[:2]
    flat = img.reshape(-1, 3).astype(np.float32) / 255
    idx, u, v, r = texels(d, W, H)
    pano, valid = panorama(flat, idx, u, v, r)
    soft, region = panel_mask(pano, valid)
    clean = redraw(pano, valid, soft, region)
    # texels take the redrawn colour where the panel mask says so (bilinear sample of the panorama)
    at = [v - 0.5, u - 0.5]                  # pixel centres
    a = ndimage.map_coordinates(soft, at, order=1, mode='nearest')
    col = np.stack([ndimage.map_coordinates(clean[..., c], at, order=1, mode='nearest') for c in range(3)], 1)
    sel = a > 0.002
    out_flat = flat.copy()
    out_flat[idx[sel]] = flat[idx[sel]] * (1 - a[sel, None]) + col[sel] * a[sel, None]
    changed = np.zeros(W * H, bool)
    changed[idx[sel]] = True
    # gutter texels next to changed ones (and covered by no triangle) copy their nearest changed texel
    cov = coverage(d, W, H)
    ch = changed.reshape(H, W)
    near = cv2.dilate(ch.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & ~cov
    ys, xs = np.nonzero(near)
    if len(ys):
        _, (iy, ix) = ndimage.distance_transform_edt(~ch, return_indices=True)
        out_flat[ys * W + xs] = out_flat[iy[ys, xs] * W + ix[ys, xs]]
    res = (out_flat.reshape(H, W, 3) * 255 + 0.5).clip(0, 255).astype(np.uint8)
    Image.fromarray(res).save(out, compress_level=6)
    print(f'panel: {int(region.sum())} panorama px, {int(sel.sum())} texels redrawn, {len(ys)} gutter texels')
    if preview:
        Image.fromarray((np.concatenate([pano, clean], 0) * 255).astype(np.uint8)).resize((WP // 2, HP)).save(preview)


if __name__ == '__main__':
    main(*sys.argv[1:4])
