"""Reshape the face so its front-projected painting reads from every angle.

The face texture was projected straight from the front (u = a*x + b, v = a*z + c), so the front
view is right by construction, and any vertex may move only along Y (depth) without breaking it.
Two repairs, both Y-only:
* Jaw. Below the painted jaw line the image shows neck shadow, but the mesh still carried the
  face forward there: from below or the side a second, shaded chin showed under the drawn one
  and slid as she turned. Vertices outside the painted face shape, below the mouth, now fall back
  toward the neck, so the surface turns under at the painted line, as an anime jaw does.
* Lips. Tripo's sculpted lips bulged and dipped round the painted mouth, so the mouth drawings
  warped as the head turned. The mouth area is set onto a smooth surface fitted to the face round it.
The shading normals are kept: the corner normals are read before and set again after.

Two halves: `python face_shape.py face.png out.npy` (system Python: scipy, pillow) measures how far
each texel lies outside the painted face skin; run(cfg, ob) (inside Blender, from room.py) moves
the vertices, running the first half when its result is missing.
"""
import os
import subprocess
import sys

import numpy as np

STEP = 4            # the distance field is stored at 1/4 of the texture resolution


def outside_distance(png, out):
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32) / 255
    warm = a[..., 0] - a[..., 2]
    skin = (a.mean(2) > 0.86) & (warm > 0.02) & (warm < 0.2)          # painted face skin: bright, warm
    skin = ndimage.binary_closing(ndimage.binary_opening(skin, iterations=3), iterations=6)
    d = ndimage.distance_transform_edt(~skin)[::STEP, ::STEP]
    np.save(out, d.astype(np.float32))


def run(cfg, ob):
    import bpy
    fs = cfg.stage.face_shape
    me = ob.data
    fi = [m.name for m in me.materials].index(fs.material)
    img = bpy.data.materials[fs.material].node_tree.nodes['BaseColor'].image
    W, H = img.size
    field = cfg.textures('face_outside.npy')
    if not os.path.exists(field):
        subprocess.run([cfg.tools.python, os.path.abspath(__file__), bpy.path.abspath(img.filepath), field], check=True)
    dist = np.load(field)
    uvl = me.uv_layers.active.data
    co = np.array([v.co for v in me.vertices])
    vid, uvs = [], []
    for p in me.polygons:
        if p.material_index == fi:
            for v, li in zip(p.vertices, p.loop_indices):
                vid.append(v)
                uvs.append(uvl[li].uv[:])
    vid, first = np.unique(np.array(vid), return_index=True)
    uvs = np.array(uvs)[first]
    px = np.clip((uvs[:, 0] * W / STEP).astype(int), 0, dist.shape[1] - 1)
    py = np.clip(((1 - uvs[:, 1]) * H / STEP).astype(int), 0, dist.shape[0] - 1)
    out_dist = dist[py, px]
    P = co[vid]
    normals = [tuple(n.vector) for n in me.corner_normals]
    y = P[:, 1].copy()
    # jaw: below the mouth and outside the painted face, back toward the neck
    t = np.clip(out_dist / fs.jaw_ramp_px, 0, 1)
    t = t * t * (3 - 2 * t) * (P[:, 2] < fs.mouth_z)
    y = y + t * np.maximum(fs.neck_y - y, 0)
    # lips: a smooth surface (quadratic in x, z) fitted to the face round the mouth
    x0, z0, rx, rz = fs.mouth_box
    d = np.maximum(np.abs(P[:, 0] - x0) / rx, np.abs(P[:, 2] - z0) / rz)
    ring = (d > 1.2) & (d < 2.2) & (t < 0.05)
    basis = np.c_[np.ones(len(P)), P[:, 0], P[:, 2], P[:, 0] ** 2, P[:, 2] ** 2, P[:, 0] * P[:, 2]]
    coef = np.linalg.lstsq(basis[ring], y[ring], rcond=None)[0]
    w = np.clip((1.6 - d) / 0.6, 0, 1)
    w = w * w * (3 - 2 * w)
    y = y * (1 - w) + (basis @ coef) * w
    for v, yy in zip(vid, y):
        me.vertices[int(v)].co.y = float(yy)
    me.update()
    me.normals_split_custom_set(normals)
    print(f'[stage] face reshaped (depth only): {int((t > 0.01).sum())} jaw vertices, {int((w > 0.01).sum())} lip vertices')


if __name__ == '__main__':
    outside_distance(*sys.argv[1:3])
