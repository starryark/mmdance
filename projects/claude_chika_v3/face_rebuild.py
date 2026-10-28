"""Rebuild the face as 3D anime faces are made (run inside Blender as a stage step:
stage.steps = ["face_rebuild.py"]; dreamwings/claude points at this file too).

Tripo's face is a realistic sculpt (nose, lips and a mouth slit, eye sockets, eyeballs, lids) in some
thirty pieces, under a painting projected straight from the front. Drawn features over sculpted ones
show twice: the outline shell caught the old mouth slit as a second mouth below the painted one, and
the sockets made their own creases round the painted eyes. Character models made for anime rendering
(Arknights: Endfield, Genshin, Gakumas, MMD and VRoid models) build the face from:
* a clean face surface: no nose, lip or socket relief, shading normals from a simple proxy shape, no
  outline on the inner face;
* a real mouth: an opening in that surface with a lip line round it, and behind it the inside of the
  mouth, the upper teeth and the tongue, shaped by shape keys for the vowels (あ い う え お), ワ and
  にやり;
* eyes in layers: the eyeball (white, iris, highlights) under an upper lid carrying the lash band and
  a lower lid carrying the lid line; shape keys close them (まばたき, winks) or bend them into ^^ (笑い).
All of it keeps the painting's front projection as UVs (u, v linear in x, z), so the painted look
carries over (face_textures.py makes the clean skin and the eye layers from the painting). The second
eye is the clean painted eye mirrored about the face's symmetry plane; the mouth is drawn by geometry.
The shape keys are keyed here from the facial track (with face.mode = "none").
"""
import collections
import json
import math
import os
import subprocess

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

from mmdance import config, face
from mmdance.util import new_action, put_curve

HERE = os.path.dirname(os.path.abspath(__file__))
MM = 0.001
# colours of the mouth (those of the painted expression tiles)
LIP = (0.77, 0.29, 0.24)
LIP_LOW = (0.66, 0.27, 0.24)
MOUTH_TOP = (0.36, 0.12, 0.14)
MOUTH_BOT = (0.59, 0.20, 0.22)
TONGUE = (0.89, 0.50, 0.49)
TONGUE_EDGE = (0.76, 0.38, 0.38)
TEETH = (0.99, 0.97, 0.96)
TEETH_EDGE = (0.88, 0.83, 0.83)
# mouth shapes in painting pixels, as the expression tiles drew them: width, opening above and below the
# centre line, roundness exponent, corner lift; the teeth band below the top, the tongue's rise
SHAPES = {
    'a': dict(w=180, up=30, down=76, p=1.0, lift=0, teeth=22, tongue=45),
    'i': dict(w=206, up=10, down=31, p=0.55, lift=2, teeth=23, tongue=None),
    'u': dict(w=86, up=22, down=48, p=1.0, lift=0, teeth=None, tongue=None),
    'e': dict(w=178, up=18, down=50, p=0.7, lift=2, teeth=22, tongue=30),
    'o': dict(w=118, up=38, down=84, p=1.0, lift=0, teeth=None, tongue=50),
    'wa': dict(w=232, up=42, down=109, p=0.8, lift=12, teeth=27, tongue=64),
}
SMIRK = [(-112, 3), (-40, 9), (40, 3), (98, -14), (120, -26)]     # にやり: the closed line, one corner up (px, y down)
TEXTURE_KEYS = ('skin_min_value', 'skin_min_sat', 'skin_max_sat', 'region_grow_px', 'nose_box', 'nose_shift_px', 'mouth_center_px', 'lid_edge_run',
                'lower_inset_px', 'opening_x_px', 'eyeball_grow')
PART_SKIN, PART_LIP, PART_CAVITY, PART_TEETH, PART_TONGUE, PART_BALL, PART_LID = 1, 2, 3, 4, 5, 6, 7


# ---------------------------------------------------------------- 2D helpers (x, z: the front view)

def inside(poly, pts):
    """Even-odd point in polygon, vectorised."""
    x, z = pts[:, 0][:, None], pts[:, 1][:, None]
    x1, z1 = poly[:, 0][None, :], poly[:, 1][None, :]
    x2, z2 = np.roll(poly[:, 0], 1)[None, :], np.roll(poly[:, 1], 1)[None, :]
    cross = ((z1 > z) != (z2 > z)) & (x < (x2 - x1) * (z - z1) / np.where(z2 == z1, 1e-30, z2 - z1) + x1)
    return cross.sum(1) % 2 == 1


def seg_dist(pts, poly):
    """Distance from points to a closed polyline."""
    a, b = poly, np.roll(poly, -1, axis=0)
    ab = b - a
    t = np.clip(((pts[:, None, :] - a[None]) * ab[None]).sum(2) / np.maximum((ab * ab).sum(1), 1e-30)[None], 0, 1)
    d = pts[:, None, :] - (a[None] + t[..., None] * ab[None])
    return np.sqrt((d * d).sum(2)).min(1)


def area2(poly):
    return 0.5 * (np.dot(poly[:, 0], np.roll(poly[:, 1], -1)) - np.dot(poly[:, 1], np.roll(poly[:, 0], -1)))


def blur(a, sigma):
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode='edge'), k, 'valid'), axis, a)
    return a


def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def curve(points, xs):
    """A guide curve of the painting (monotone x) at xs, lightly smoothed."""
    p = np.array(points, float)
    ys = np.interp(xs, p[:, 0], p[:, 1])
    k = np.ones(3) / 3
    return np.convolve(np.pad(ys, 1, mode='edge'), k, 'valid')


# ---------------------------------------------------------------- the face surface

class Surface:
    """A smooth face y(x, z): the old face (front-most) with its relief blurred away and a little of the
    nose kept, turning into the old surface near the outline, where the new face meets the head."""

    def __init__(self, tris, outer, fr, mirror_x):
        h = self.h = 0.0004
        lo, hi = outer.min(0) - 0.012, outer.max(0) + 0.012
        self.x0, self.z0 = lo
        nx, nz = int((hi[0] - lo[0]) / h) + 2, int((hi[1] - lo[1]) / h) + 2
        D = np.full((nz, nx), np.inf)
        for t in tris:
            q = t[:, [0, 2]]
            (ax, az), (bx, bz), (cx, cz) = q
            det = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
            if abs(det) < 1e-14:
                continue
            i0, i1 = int((q[:, 0].min() - self.x0) / h), int((q[:, 0].max() - self.x0) / h) + 1
            j0, j1 = int((q[:, 1].min() - self.z0) / h), int((q[:, 1].max() - self.z0) / h) + 1
            gx, gz = np.meshgrid(self.x0 + np.arange(i0, i1 + 1) * h, self.z0 + np.arange(j0, j1 + 1) * h)
            l1 = ((bz - cz) * (gx - cx) + (cx - bx) * (gz - cz)) / det
            l2 = ((cz - az) * (gx - cx) + (ax - cx) * (gz - cz)) / det
            l3 = 1 - l1 - l2
            m = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
            y = l1 * t[0, 1] + l2 * t[1, 1] + l3 * t[2, 1]
            sub = D[j0:j1 + 1, i0:i1 + 1]
            sub[m] = np.minimum(sub[m], y[m])
        valid = np.isfinite(D)
        Dz = np.where(valid, D, 0.0)
        sg = fr.smooth_mm * MM / h
        S = blur(Dz, sg) / np.maximum(blur(valid.astype(float), sg), 1e-9)
        gx, gz = np.meshgrid(self.x0 + np.arange(nx) * h, self.z0 + np.arange(nz) * h)
        cand = valid & (np.abs(gx - mirror_x) < 0.005)
        tip = np.unravel_index(np.argmin(np.where(cand, D, np.inf)), D.shape)
        self.nose = (float(gx[tip]), float(gz[tip]))
        nm = np.exp(-((gx - mirror_x) / (fr.nose_radii_mm[0] * MM)) ** 2
                    - ((gz - gz[tip] - fr.nose_radii_mm[1] * MM * 0.4) / (fr.nose_radii_mm[1] * MM)) ** 2)
        S = np.where(valid, S + fr.nose_keep * nm * (D - S), S)
        P = np.c_[gx.ravel(), gz.ravel()]
        din = inside(outer, P).reshape(D.shape)
        de = seg_dist(P, outer).reshape(D.shape)
        w = np.where(din, smoothstep(de / (fr.edge_ramp_mm * MM)), 0.0)
        self.Y = np.where(valid, Dz + (S - Dz) * w, S)
        self.relief = float(np.abs(np.where(valid & din, D - self.Y, 0)).max())
        self.nx, self.nz = nx, nz

    def __call__(self, x, z):
        fx = np.clip((np.asarray(x, float) - self.x0) / self.h, 0, self.nx - 1.001)
        fz = np.clip((np.asarray(z, float) - self.z0) / self.h, 0, self.nz - 1.001)
        i, j = fx.astype(int), fz.astype(int)
        tx, tz = fx - i, fz - j
        Y = self.Y
        return (Y[j, i] * (1 - tx) * (1 - tz) + Y[j, i + 1] * tx * (1 - tz)
                + Y[j + 1, i] * (1 - tx) * tz + Y[j + 1, i + 1] * tx * tz)


# ---------------------------------------------------------------- the old face

def projection(me, fi):
    """The painting's front projection: u, v as linear functions of x, z (fitted on the face's UVs)."""
    co = np.array([v.co[:] for v in me.vertices])
    uvl = me.uv_layers.active.data
    X, U = [], []
    for p in me.polygons:
        if p.material_index == fi:
            for v, li in zip(p.vertices, p.loop_indices):
                X.append(co[v])
                U.append(uvl[li].uv[:])
    X, U = np.array(X), np.array(U)
    A = np.c_[X[:, 0], X[:, 2], np.ones(len(X))]
    return np.linalg.lstsq(A, U[:, 0], rcond=None)[0], np.linalg.lstsq(A, U[:, 1], rcond=None)[0]


def outer_loop(bm, F):
    """The face polygons' outer boundary loop (vertex indices, counter-clockwise seen from the front)."""
    ec = collections.Counter(e.index for f in F for e in bm.faces[f].edges)
    adj = collections.defaultdict(list)
    for ei, n in ec.items():
        if n == 1:
            a, b = (v.index for v in bm.edges[ei].verts)
            adj[a].append(b)
            adj[b].append(a)
    seen, loops = set(), []
    for s in adj:
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nx = [n for n in adj[cur] if n != prev and n not in seen]
            if not nx:
                break
            prev, cur = cur, nx[0]
            loop.append(cur)
            seen.add(cur)
        loops.append(loop)

    def xz(L):
        return np.array([[bm.verts[i].co.x, bm.verts[i].co.z] for i in L])
    best = max(loops, key=lambda L: abs(area2(xz(L))))
    return best[::-1] if area2(xz(best)) < 0 else best


def untangle(P, span=8):
    """The outline in the front view, where the surface folds over itself (it crosses itself by less
    than a millimetre beside the eyes): each short folded run is laid straight between its ends. Only
    this 2D layout changes (it is what the new face is meshed in); the vertices stay where they are."""
    n, fixed = len(P), 0
    P = P.copy()

    def crosses(a, b, c, d):
        def cr(o, p, q):
            return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
        return cr(a, b, c) * cr(a, b, d) < 0 and cr(c, d, a) * cr(c, d, b) < 0
    for _ in range(20):
        hit = None
        for i in range(n):
            for k in range(2, span + 1):
                j = (i + k) % n
                if crosses(P[i], P[(i + 1) % n], P[j], P[(j + 1) % n]):
                    hit = (i, k)
                    break
            if hit:
                break
        if not hit:
            return P, fixed
        i, k = hit
        a, b = P[i], P[(i + k + 1) % n]
        for m in range(1, k + 1):
            P[(i + m) % n] = a + (b - a) * m / (k + 1)
        fixed += 1
    raise RuntimeError('face_rebuild: the face outline crosses itself in the front view and could not be untangled')


def region_to_remove(bm, F, loop, outer, mats_ok):
    """The old face: its polygons, whatever fills their holes inside the outline (reached across edges
    not on the outline), and the separate pieces (eyeballs, lids, lips, nose tip) lying inside it. Hair
    is never taken: the bangs hang in front of the face."""
    on_loop = set(loop)
    loop_edges = {frozenset(e) for e in zip(loop, loop[1:] + loop[:1])}
    vin = {}

    def v_inside(v):
        if v.index not in vin:
            vin[v.index] = v.index in on_loop or bool(inside(outer, np.array([[v.co.x, v.co.z]]))[0])
        return vin[v.index]
    take, stack = set(F), list(F)
    while stack:
        f = bm.faces[stack.pop()]
        for e in f.edges:
            if frozenset(v.index for v in e.verts) in loop_edges:
                continue
            for g in e.link_faces:
                if g.index not in take and g.material_index in mats_ok and all(v_inside(v) for v in g.verts):
                    take.add(g.index)
                    stack.append(g.index)
    parent = list(range(len(bm.verts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in bm.edges:
        a, b = find(e.verts[0].index), find(e.verts[1].index)
        if a != b:
            parent[a] = b
    comps = collections.defaultdict(list)
    for v in bm.verts:
        comps[find(v.index)].append(v.index)
    main = {find(bm.faces[f].verts[0].index) for f in F}
    pieces = 0
    for r, vs in comps.items():
        if r in main or len(vs) > 2000:
            continue
        P = np.array([[bm.verts[i].co.x, bm.verts[i].co.z] for i in vs])
        if inside(outer, P).mean() < 0.75:
            continue
        faces = {f.index for i in vs for f in bm.verts[i].link_faces}
        if faces and all(bm.faces[f].material_index in mats_ok for f in faces):
            take |= faces
            pieces += 1
    return take, pieces


# ---------------------------------------------------------------- the new face

def mouth_layout(fr, mx, mz):
    """The rest rim (a closed slit along a gently arched line), the lip strip and the rings round it.
    Every ring is a loop of the same vertices, counter-clockwise: left corner, lower rim left to right,
    right corner, upper rim right to left. Returns the slots' (side, i) and the rings' (x, z)."""
    n = fr.mouth_segments
    s = np.arange(n + 1) / n
    w0 = fr.mouth_width_mm * MM / 2
    x = mx - np.cos(np.pi * s) * w0
    zl = mz + fr.mouth_arch_mm * MM * np.sin(np.pi * s)
    g = fr.mouth_rest_gap_mm * MM / 2 * np.sin(np.pi * s)
    slots = [('c', 0)] + [('l', i) for i in range(1, n)] + [('c', n)] + [('u', i) for i in range(n - 1, 0, -1)]
    taper = 0.35 + 0.65 * np.sin(np.pi * s) ** 0.6

    def ring(off):
        out = []
        for side, i in slots:
            if side == 'c':
                p = np.array([x[i], zl[i]])
                p[0] += -off('c', i) if i == 0 else off('c', i)
            else:
                p = np.array([x[i], zl[i] + (g[i] if side == 'u' else -g[i])])
                d = np.array([-np.cos(np.pi * s[i]) * 0.8, 1.0 if side == 'u' else -1.0])
                p += off(side, i) * d / np.linalg.norm(d)
            out.append(p)
        return np.array(out)
    lip = {'c': fr.lip_corner_mm, 'u': fr.lip_upper_mm, 'l': fr.lip_lower_mm}
    rings = [ring(lambda side, i: 0.0),
             ring(lambda side, i: lip[side] * MM * (1.0 if side == 'c' else taper[i]))]
    for d in fr.mouth_rings_mm:
        rings.append(ring(lambda side, i, d=d: d * MM))
    return dict(n=n, s=s, slots=slots, rings=rings, center=(mx, mz))


def shape_rim(shape, lay, px):
    """Target (x, z) of the rim's slots for a mouth shape."""
    s, (mx, mz) = lay['s'], lay['center']
    if shape == 'smirk':
        pts = np.array(SMIRK, float)
        xs = mx + (-np.cos(np.pi * s) * 116 + 4) * px
        zs = mz - np.interp((xs - mx) / px, pts[:, 0], pts[:, 1]) * px
        return np.array([(xs[i], zs[i]) for side, i in lay['slots']])
    d = SHAPES[shape]
    zc = mz - 5 * px
    sn = np.sin(np.pi * s) ** d['p']
    lift = d['lift'] * px * np.cos(np.pi * s) ** 2
    xs = mx - np.cos(np.pi * s) * d['w'] / 2 * px
    out = []
    for side, i in lay['slots']:
        sign = 0 if side == 'c' else (d['up'] if side == 'u' else -d['down'])
        out.append((xs[i], zc + sign * px * sn[i] + lift[i]))
    return np.array(out)


def fill_region(outer, hole, spacing):
    """Triangles filling the outline minus the hole, with interior points on a hex grid. Returns
    (points, triangles); the points start with the outline, then the hole, in their own order."""
    lo, hi = outer.min(0), outer.max(0)
    pts, row, z = [], 0, lo[1] + spacing / 2
    while z < hi[1]:
        x = lo[0] + (spacing / 2 if row % 2 else 0)
        while x < hi[0]:
            pts.append((x, z))
            x += spacing
        z += spacing * math.sqrt(3) / 2
        row += 1
    pts = np.array(pts)
    pts = pts[inside(outer, pts) & ~inside(hole, pts)]
    pts = pts[(seg_dist(pts, outer) > 0.55 * spacing) & (seg_dist(pts, hole) > 0.55 * spacing)]
    allp = np.vstack([outer, hole, pts])
    no, nh = len(outer), len(hole)
    edges = [(i, (i + 1) % no) for i in range(no)] + [(no + i, no + (i + 1) % nh) for i in range(nh)]
    vc, ve, vf, ov, oe, of = delaunay_2d_cdt([Vector(p * 1000.0) for p in allp], edges, [], 0, 1e-5)
    if len(vc) != len(allp) or any(len(o) != 1 for o in ov):
        raise RuntimeError(f'face_rebuild: the fill merged or added points ({len(allp)} -> {len(vc)}): '
                           'the outline crosses itself in the front view?')
    out_id = [o[0] for o in ov]
    tris = []
    for f in vf:
        ids = [out_id[i] for i in f]
        c = allp[ids].mean(0)[None]
        if inside(outer, c)[0] and not inside(hole, c)[0]:
            tris.append(ids if area2(allp[ids]) > 0 else ids[::-1])
    return allp, tris


class Builder:
    """New vertices and faces, with UVs from the front projection and a part tag per face."""

    def __init__(self, bm, uv_of):
        self.bm, self.uv_of = bm, uv_of
        self.verts, self.info = [], []
        self.part = bm.faces.layers.int['fr_part']
        self.uvl = bm.loops.layers.uv.active

    def vert(self, co, **info):
        self.verts.append(self.bm.verts.new(co))
        self.info.append(info)
        return len(self.verts) - 1

    def face(self, ids, mat, part, uv_xz=None):
        """ids: new-vertex ids or BMVerts; uv_xz: the (x, z) to project per corner (default: the
        vertices' own)."""
        vs = [i if isinstance(i, bmesh.types.BMVert) else self.verts[i] for i in ids]
        f = self.bm.faces.new(vs)
        f.smooth = True                               # (new faces are flat: their custom normals would not show)
        f.material_index = mat
        f[self.part] = part
        for k, lp in enumerate(f.loops):
            x, z = uv_xz[k] if uv_xz is not None else (lp.vert.co.x, lp.vert.co.z)
            lp[self.uvl].uv = self.uv_of(x, z)
        return f


def grid_faces(B, ids, mat, part, uvs=None, flip=False):
    """Quads over [rows][cols] new-vertex ids (rows top to bottom, columns left to right in the front view)."""
    for r in range(len(ids) - 1):
        for c in range(len(ids[0]) - 1):
            corners = [(r + 1, c), (r + 1, c + 1), (r, c + 1), (r, c)]      # counter-clockwise from the front
            if flip:
                corners = corners[::-1]
            B.face([ids[a][b] for a, b in corners], mat, part, None if uvs is None else [uvs[a][b] for a, b in corners])


def run(cfg, coll):
    ob = bpy.data.objects[cfg.character.body]
    fr = cfg.stage.face_rebuild
    me = ob.data
    names = [m.name for m in me.materials]
    fi = names.index(fr.material)
    n_adopted = sibling('face_shape').adopt_islands(me, fi, fr.adopt_max_polys, fr.adopt_ratio)
    cu, cv = projection(me, fi)
    mat = bpy.data.materials[fr.material]
    _, base, shader, inp = face.face_nodes(cfg, mat)
    size = base.image.size[0] or 2048
    Ainv = np.linalg.inv(np.array([[cu[0], cu[1]], [cv[0], cv[1]]]))

    def uv_of(x, z):
        return (cu[0] * x + cu[1] * z + cu[2], cv[0] * x + cv[1] * z + cv[2])

    def px_to_xz(px, py):
        q = Ainv @ np.array([px / size - cu[2], 1 - py / size - cv[2]])
        return float(q[0]), float(q[1])
    px = 1.0 / (size * abs(cu[0]))                     # metres per painting pixel
    mx = fr.mirror_x
    hair = names.index(cfg.hair.material) if cfg.hair.material in names else -1
    mats_ok = {i for i in range(len(names)) if i != hair}
    m_ball, m_lid, m_mouth = len(names), len(names) + 1, len(names) + 2
    # the corners' shading normals as they are, carried through the edit
    cn = np.array([n.vector[:] for n in me.corner_normals], np.float32)
    a = me.attributes.get('fr_cn') or me.attributes.new('fr_cn', 'FLOAT_VECTOR', 'CORNER')
    a.data.foreach_set('vector', cn.ravel())

    bm = bmesh.new()
    bm.from_mesh(me)
    # every layer first: adding one later leaves the vertex references made before it invalid
    dl = bm.verts.layers.deform.verify()
    al = bm.verts.layers.float.get('fr_alpha') or bm.verts.layers.float.new('fr_alpha')
    cl = bm.verts.layers.float_color.get('fr_col') or bm.verts.layers.float_color.new('fr_col')
    if 'fr_part' not in bm.faces.layers.int:
        bm.faces.layers.int.new('fr_part')
    for seq in (bm.verts, bm.edges, bm.faces):
        seq.ensure_lookup_table()
    F = [f.index for f in bm.faces if f.material_index == fi]
    loop = outer_loop(bm, F)
    outer, n_untangled = untangle(np.array([[bm.verts[i].co.x, bm.verts[i].co.z] for i in loop]))
    cen = np.array([[f.calc_center_median().x, f.calc_center_median().z] for f in (bm.faces[i] for i in F)])
    F_in = [f for f, ok in zip(F, inside(outer, cen)) if ok]      # not the face-painted pieces outside (earrings)
    take, pieces = region_to_remove(bm, F_in, loop, outer, mats_ok)
    by_mat = collections.Counter(names[bm.faces[f].material_index] for f in take)
    tris = []
    for f in take:
        vs = [v.co[:] for v in bm.faces[f].verts]
        tris += [(vs[0], vs[k], vs[k + 1]) for k in range(1, len(vs) - 1)]
    surf = Surface(np.array(tris), outer, fr, mx)
    og = ob.vertex_groups.get(cfg.character.outline_group) if cfg.character.outline_group else None
    oidx = og.index if og else -1
    src = sorted({v.index for f in take for v in bm.faces[f].verts})
    src_co = np.array([bm.verts[i].co[:] for i in src])
    src_w = [dict(bm.verts[i][dl].items()) for i in src]
    loop_verts = [bm.verts[i] for i in loop]
    loop_w = np.array([v[dl].get(oidx, 0.0) for v in loop_verts])
    dead = [bm.faces[f] for f in take]
    dead_v = {v for f in dead for v in f.verts} - set(loop_verts)
    bmesh.ops.delete(bm, geom=dead, context='FACES_ONLY')
    bmesh.ops.delete(bm, geom=[v for v in dead_v if v.is_valid and not v.link_faces], context='VERTS')
    lv = set(loop_verts)                              # loose chords between outline vertices (not the outline itself)
    ring = {frozenset(e) for e in zip(loop_verts, loop_verts[1:] + loop_verts[:1])}
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces and set(e.verts) <= lv
                               and frozenset(e.verts) not in ring], context='EDGES')
    B = Builder(bm, uv_of)

    # ---- the face surface with the mouth opening
    _, mz = px_to_xz(0, fr.mouth_line_px)
    lay = mouth_layout(fr, mx, mz)
    ring_ids = [[B.vert((x, float(surf(x, z)), z), part='ring', ring=k, slot=j) for j, (x, z) in enumerate(ring)]
                for k, ring in enumerate(lay['rings'])]
    nl = len(lay['slots'])
    for k in range(len(ring_ids) - 1):
        for j in range(nl):
            q = [ring_ids[k][j], ring_ids[k + 1][j], ring_ids[k + 1][(j + 1) % nl], ring_ids[k][(j + 1) % nl]]
            P = np.array([[B.verts[i].co.x, B.verts[i].co.z] for i in q])
            B.face(q if area2(P) > 0 else q[::-1], m_mouth if k == 0 else fi, PART_LIP if k == 0 else PART_SKIN)
    allp, ftris = fill_region(outer, lay['rings'][-1], fr.fill_spacing_mm * MM)
    no, nh = len(outer), nl
    fill = [loop_verts[i] if i < no else (B.verts[ring_ids[-1][i - no]] if i < no + nh else None) for i in range(len(allp))]
    for i in range(no + nh, len(allp)):
        x, z = allp[i]
        fill[i] = B.verts[B.vert((x, float(surf(x, z)), z), part='skin')]
    for t in ftris:
        B.face([fill[i] for i in t], fi, PART_SKIN)

    # ---- inside the mouth: the cavity, the upper teeth and the tongue, behind the surface
    wmax = max(fr.mouth_width_mm * MM, max(d['w'] for d in SHAPES.values()) * px)
    umax = max(d['up'] + d['lift'] for d in SHAPES.values()) * px
    dmax = (max(d['down'] for d in SHAPES.values()) + 5) * px
    nxc, nzc = 15, 11
    cav = []
    for r, v in enumerate(np.linspace(1, -1, nzc)):
        z = mz + (umax + 1.4 * MM) * (v + 1) / 2 - (dmax + 1.8 * MM) * (1 - v) / 2
        row = []
        for u in np.linspace(-1, 1, nxc):
            x = mx + u * (wmax / 2 + 1.8 * MM)
            depth = (fr.cavity_depth_mm[0] + fr.cavity_depth_mm[1] * (1 - u * u) * (1 - v * v)) * MM
            t = float(np.clip((mz + umax - z) / (umax + dmax), 0, 1))
            row.append(B.vert((x, float(surf(x, z)) + depth, z), part='cavity',
                              col=tuple(MOUTH_TOP[i] * (1 - t) + MOUTH_BOT[i] * t for i in range(3))))
        cav.append(row)
    grid_faces(B, cav, m_mouth, PART_CAVITY)
    tw = fr.teeth_width * fr.mouth_width_mm * MM / 2
    teeth = []
    for r, z in enumerate([mz + 2.4 * MM, mz + (fr.teeth_rest_mm + 0.15) * MM, mz + fr.teeth_rest_mm * MM]):
        teeth.append([B.vert((x, float(surf(x, z)) + fr.teeth_depth_mm * MM, z), part='teeth', row=r,
                             depth=fr.teeth_depth_mm * MM, col=TEETH if r < 2 else TEETH_EDGE)
                      for x in mx + np.linspace(-1, 1, 15) * tw])
    grid_faces(B, teeth, m_mouth, PART_TEETH)
    tz = mz + fr.tongue_rest_mm * MM
    rx, rz = fr.tongue_radii_mm[0] * MM, fr.tongue_radii_mm[1] * MM
    tongue = [B.vert((mx, float(surf(mx, tz)) + (fr.tongue_depth_mm - fr.tongue_bulge_mm) * MM, tz), part='tongue',
                     depth=(fr.tongue_depth_mm - fr.tongue_bulge_mm) * MM, col=TONGUE)]
    nseg = 14
    for ring in (0.55, 1.0):
        for k in range(nseg):
            a = 2 * math.pi * k / nseg
            x, z = mx + ring * rx * math.cos(a), tz + ring * rz * math.sin(a)
            dep = (fr.tongue_depth_mm - fr.tongue_bulge_mm * (1 - ring * ring)) * MM
            tongue.append(B.vert((x, float(surf(x, z)) + dep, z), part='tongue', depth=dep,
                                 col=TONGUE if ring < 1 else TONGUE_EDGE))
    for k in range(nseg):
        k1 = (k + 1) % nseg
        B.face([tongue[0], tongue[1 + k], tongue[1 + k1]], m_mouth, PART_TONGUE)
        B.face([tongue[1 + k], tongue[1 + nseg + k], tongue[1 + nseg + k1], tongue[1 + k1]], m_mouth, PART_TONGUE)

    # ---- the eyes: eyeball, upper lid, lower lid, in layers over the face
    bm.faces.ensure_lookup_table()
    bvh = BVHTree.FromBMesh(bm)

    def surface_y(x, z):
        """The face under (x, z): the new surface inside the outline, the head (cast from inside) outside."""
        if inside(outer, np.array([[x, z]]))[0]:
            return float(surf(x, z))
        hit = bvh.ray_cast(Vector((x, fr.eye_cast_from_y, z)), Vector((0, -1, 0)), 0.08)
        return hit[0].y if hit[0] is not None else float(surf(x, z))
    E = cfg.face.atlas.eyes.R                          # the clean painted eye (image right: her left)
    x_px = np.linspace(E.lash_top[0][0], E.lash_top[-1][0], fr.eye_columns)
    cols = np.r_[x_px[0] - fr.eye_end_px, x_px, x_px[-1] + fr.eye_end_px]
    T, Bt, Lo = (np.r_[c[0], c, c[-1]] for c in (curve(E.lash_top, x_px), curve(E.lash_bot, x_px), curve(E.lower, x_px)))
    Lo = Lo - fr.lower_inset_px
    edge_a = np.r_[0.0, np.ones(len(x_px)), 0.0]
    eyes = {}
    for side, mirror in (('L', False), ('R', True)):

        def place(xp, yp, off, mirror=mirror):
            x, z = px_to_xz(xp, yp)
            if mirror:
                x = 2 * mx - x
            return (x, surface_y(x, z) - off * MM, z)

        def layer(rows, alpha, off, part, mat):
            """rows: [top..bottom] arrays of painting y per column."""
            ids = [[B.vert(place(cols[c], rows[r][c], off), part=part, eye=side, row=r, c=c,
                           alpha=(alpha[r] * edge_a[c]) if alpha else 1.0) for c in range(len(cols))]
                   for r in range(len(rows))]
            uvs = [[px_to_xz(cols[c], rows[r][c]) for c in range(len(cols))] for r in range(len(rows))]
            grid_faces(B, ids, mat, PART_LID if part != 'ball' else PART_BALL, uvs, flip=mirror)
            return ids
        up_rows = [T - a for a in fr.lid_rows_px[::-1]] + [T, Bt]
        up_alpha = list(fr.lid_alpha[::-1]) + [1.0, 1.0]
        lo_rows = [Lo] + [Lo + fr.lower_inset_px + a for a in fr.lower_rows_px]
        lo_alpha = [1.0] + list(fr.lower_alpha)
        ball_rows = [(Bt - fr.ball_margin_px) * (1 - f) + (Lo + fr.ball_margin_px) * f for f in np.linspace(0, 1, 7)]
        eyes[side] = dict(up=layer(up_rows, up_alpha, fr.lid_offset_mm, 'lid', m_lid),
                          lo=layer(lo_rows, lo_alpha, fr.lower_offset_mm, 'lower', m_lid),
                          ball=layer(ball_rows, None, fr.ball_offset_mm, 'ball', m_ball),
                          up_rows=up_rows, lo_rows=lo_rows, place=place, cols=cols)

    # ---- weights and attributes
    new_co = np.array([v.co[:] for v in B.verts])
    for i, v in enumerate(B.verts):
        d = np.linalg.norm(src_co - new_co[i], axis=1)
        nn = np.argpartition(d, 6)[:6]
        acc = collections.defaultdict(float)
        for j, wj in zip(nn, 1.0 / np.maximum(d[nn], 1e-5) ** 2):
            for g, val in src_w[j].items():
                if g != oidx:
                    acc[g] += wj * val
        tot = sum(acc.values())
        for g, val in acc.items():
            if val > 0.002 * tot:
                v[dl][g] = val / tot
    if og:                                            # outline: none on the inner face, the old weights near its edge
        for i, v in enumerate(B.verts):
            if B.info[i]['part'] == 'skin' or (B.info[i]['part'] == 'ring' and B.info[i]['ring'] >= 2):
                dd = np.linalg.norm(outer - np.array([v.co.x, v.co.z]), axis=1)
                j = int(np.argmin(dd))
                w = loop_w[j] * max(0.0, 1 - dd[j] / (fr.outline_fade_mm * MM))
                if w > 0.001:
                    v[dl][oidx] = w
    for i, v in enumerate(B.verts):
        inf = B.info[i]
        v[al] = inf.get('alpha', 1.0)
        col = inf.get('col')
        if col is None and inf['part'] == 'ring':
            col = LIP_LOW if lay['slots'][inf['slot']][0] == 'l' else LIP
        v[cl] = (*(col or (1.0, 1.0, 1.0)), 1.0)
    bm.verts.index_update()
    new_idx = np.array([v.index for v in B.verts])
    bm.to_mesh(me)
    me.update()
    bm.free()

    imgs = textures(cfg, mat, outer, uv_of, size)
    for m in materials(cfg, mat, base, shader, inp, imgs):
        me.materials.append(m)
    proxy_normals(fr, me, outer)
    keys = shape_keys(fr, ob, B.info, new_co, new_idx, lay, ring_ids, teeth, tongue, eyes, surf, px, mz)
    key_from_track(cfg, ob, keys)
    print(f'[stage] face rebuilt: {n_adopted} polygons adopted, {n_untangled} folds in the outline laid flat; {len(take)} old polygons removed {dict(by_mat)} '
          f'with {pieces} separate pieces; relief taken out up to {surf.relief * 1000:.1f} mm; '
          f'{len(B.verts)} new vertices ({len(ftris)} fill triangles); shape keys {list(keys)}')


# ---------------------------------------------------------------- textures, materials, normals

def textures(cfg, mat, outer, uv_of, size):
    """The clean skin and the eye layers from the painting (face_textures.py, system Python), cached."""
    src = face.source_texture(cfg, mat)
    poly = [[u * size, (1 - v) * size] for u, v in (uv_of(x, z) for x, z in outer)]
    keys = {k: cfg.stage.face_rebuild[k] for k in TEXTURE_KEYS}
    key = cfg.key(config.file_key(src), keys, cfg.face.atlas.eyes, cfg.face.atlas.get('halo_boxes'),
                  cfg.face.atlas.get('corner_box'), [[round(a, 1) for a in p] for p in poly],
                  config.file_key(os.path.join(HERE, 'face_textures.py')))
    meta = cfg.textures('face_rebuild.json')
    fresh = os.path.exists(meta) and json.load(open(meta)).get('key') == key
    if not fresh:
        region = cfg.textures('face_rebuild_region.json')
        with open(region, 'w') as f:
            json.dump({'polygon_px': poly}, f)
        cmd = [cfg.tools.python, os.path.join(HERE, 'face_textures.py'), cfg['_file'], src, region, key]
        print('[stage] face textures:', ' '.join(cmd))
        subprocess.run(cmd, check=True)
    out = {}
    for k, name in (('skin', 'Face_Skin.png'), ('lid', 'Face_EyeLid.png'), ('ball', 'Face_EyeBall.png')):
        img = bpy.data.images.load(cfg.textures(name), check_existing=True)
        img.reload()
        img.colorspace_settings.name = 'sRGB'
        img.alpha_mode = 'STRAIGHT'
        out[k] = img
    return out


def materials(cfg, mat, base, shader, inp, imgs):
    """The face gets the clean skin; the eyeball, lid and mouth materials are copies of it (same toon
    shading and light drivers): the eyeball cut out by its texture's alpha, the lids faded out at their
    edges, the mouth coloured by its vertices."""
    nt = mat.node_tree
    for n in [n for n in nt.nodes if n.name.startswith('FX_') and n.name != 'FX_UV']:
        nt.nodes.remove(n)                            # the painted expression tiles, if the scene had them
    nt.links.new(base.outputs['Color'], shader.inputs[inp])
    if 'mmdance_face_nodes' in mat:
        del mat['mmdance_face_nodes']
    base.image = imgs['skin']
    out = []
    for name in ('Claude_EyeBall', 'Claude_EyeLid', 'Claude_Mouth'):
        old = bpy.data.materials.get(name)
        if old is not None:
            bpy.data.materials.remove(old)
        m = mat.copy()
        m.name = name
        t = m.node_tree
        b, sh = t.nodes[base.name], t.nodes[shader.name]
        if 'Sun Band' in sh.inputs:
            sh.inputs['Sun Band'].default_value = 0.0
        if name == 'Claude_Mouth':
            ca = t.nodes.new('ShaderNodeVertexColor')
            ca.layer_name = 'fr_col'
            t.links.new(ca.outputs['Color'], sh.inputs[inp])
        else:
            b.image = imgs['ball' if name == 'Claude_EyeBall' else 'lid']
            if name == 'Claude_EyeBall':
                alpha = b.outputs['Alpha']
            else:
                at = t.nodes.new('ShaderNodeAttribute')
                at.attribute_type = 'GEOMETRY'
                at.attribute_name = 'fr_alpha'
                alpha = at.outputs['Fac']
            outn = next(n for n in t.nodes if n.bl_idname == 'ShaderNodeOutputMaterial')
            surf_in = outn.inputs['Surface']
            shade = surf_in.links[0].from_socket
            mix = t.nodes.new('ShaderNodeMixShader')
            tr = t.nodes.new('ShaderNodeBsdfTransparent')
            t.links.new(alpha, mix.inputs['Fac'])
            t.links.new(tr.outputs[0], mix.inputs[1])
            t.links.new(shade, mix.inputs[2])
            t.links.new(mix.outputs[0], surf_in)
            if hasattr(m, 'surface_render_method'):
                m.surface_render_method = 'DITHERED'
            if hasattr(m, 'use_transparent_shadow'):
                m.use_transparent_shadow = True
        out.append(m)
    return out


def proxy_normals(fr, me, outer):
    """Shading normals of the new parts from an ellipsoid round the head (as face_shape did), turning
    into the surface's own toward the outline; the old corners keep theirs."""
    nl = len(me.loops)
    old = np.empty(nl * 3, np.float32)
    me.attributes['fr_cn'].data.foreach_get('vector', old)
    old = old.reshape(-1, 3)
    part = np.empty(len(me.polygons), np.int32)
    me.attributes['fr_part'].data.foreach_get('value', part)
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    vn = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('normal', vn)
    vn = vn.reshape(-1, 3)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get('vertex_index', lv)
    lp = np.empty(nl, np.int64)
    for p in me.polygons:
        lp[p.loop_start:p.loop_start + p.loop_total] = p.index
    c, r = np.array(fr.normal_center), np.array(fr.normal_radii)
    g = (co[lv] - c) / (r * r)
    g /= np.linalg.norm(g, axis=1, keepdims=True)
    lpart = part[lp]
    t = np.ones(nl)
    sk = lpart == PART_SKIN
    d = seg_dist(co[lv[sk]][:, [0, 2]], outer)
    t[sk] = smoothstep(d / (fr.normal_ramp_mm * MM))
    n = np.where((lpart > 0)[:, None], g * t[:, None] + vn[lv] * (1 - t[:, None]), old)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    me.normals_split_custom_set(n.tolist())
    me.attributes.remove(me.attributes['fr_cn'])


# ---------------------------------------------------------------- shape keys

def shape_keys(fr, ob, info, new_co, new_idx, lay, ring_ids, teeth, tongue, eyes, surf, px, mz):
    """Mouth: the rim to each shape, the lip strip with it, the rings after it less and less (the lower
    ones more: the jaw), the teeth and tongue showing as the tiles had them. Eyes: the upper lid down
    to the lid line (closed), or both lids to a ^^ arch (smile)."""
    me = ob.data
    if me.shape_keys is None:
        ob.shape_key_add(name='Basis', from_mix=False)
    basis = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', basis)
    basis = basis.reshape(-1, 3)
    rest = [new_co[ids][:, [0, 2]] for ids in ring_ids]
    keys = {}

    def put(name, moves):
        kb = me.shape_keys.key_blocks.get(name) or ob.shape_key_add(name=name, from_mix=False)
        co = basis.copy()
        for vid, p in moves.items():
            co[new_idx[vid]] = p
        kb.data.foreach_set('co', co.ravel())
        keys[name] = kb
    for shape in list(SHAPES) + ['smirk']:
        tgt = shape_rim(shape, lay, px)
        disp = tgt - rest[0]
        moves = {}
        for k, ids in enumerate(ring_ids):
            for j, vid in enumerate(ids):
                side = lay['slots'][j][0]
                f = 1.0 if k <= 1 else (fr.ring_follow_low if side == 'l' else fr.ring_follow_up)[k - 2]
                x, z = rest[k][j] + f * disp[j]
                moves[vid] = (x, float(surf(x, z)), z)
        upper = sorted((tgt[j][0], tgt[j][1]) for j, (side, i) in enumerate(lay['slots']) if side != 'l')
        ux, uz = np.array(upper).T
        d = SHAPES.get(shape)
        for r, row in enumerate(teeth[1:], 1):         # the top row stays hidden behind the upper lip
            for vid in row:
                x, z0 = new_co[vid][0], new_co[vid][2]
                top = float(np.interp(x, ux, uz))
                if d and d['teeth']:                  # the band of teeth under the upper rim
                    z = top - d['teeth'] * px + (0.15 * MM if r == 1 else 0.0)
                else:                                 # kept above the opening
                    z = max(z0, top + (0.45 if r == 1 else 0.3) * MM)
                moves[vid] = (x, float(surf(x, z)) + info[vid]['depth'], z)
        if d and d['tongue']:
            low = min(tgt[j][1] for j, (side, i) in enumerate(lay['slots']) if side == 'l')
            dz = low + 0.25 * d['tongue'] * px - (mz + fr.tongue_rest_mm * MM)
            for vid in tongue:
                x, z = new_co[vid][0], new_co[vid][2] + dz
                moves[vid] = (x, float(surf(x, z)) + info[vid]['depth'], z)
        put(shape, moves)
    for side, e in eyes.items():
        up, lo, place = e['up'], e['lo'], e['place']
        nU = len(up)
        Bt = e['up_rows'][-1]
        Lo = e['lo_rows'][0]
        gap = Lo - Bt
        follow_up = list(fr.lid_follow[::-1]) + [1.0, 1.0]     # rows top to bottom
        for name, delta_up, delta_lo in (
                ('close', gap + fr.lid_overlap_px, np.zeros_like(gap)),
                ('smile', np.minimum(fr.eye_smile_frac * gap.max(), 0.85 * gap), None)):
            if delta_lo is None:                      # the lower lid rises to meet the lowered lash band
                delta_lo = (Bt + delta_up - fr.lid_overlap_px) - Lo
            moves = {}
            for r in range(nU):
                for c, vid in enumerate(up[r]):
                    yp = e['up_rows'][r][c] + follow_up[r] * delta_up[c]
                    moves[vid] = place(e['cols'][c], yp, fr.lid_offset_mm)
            follow_lo = [1.0] + list(fr.lower_follow)
            for r in range(len(lo)):
                for c, vid in enumerate(lo[r]):
                    yp = e['lo_rows'][r][c] + follow_lo[r] * delta_lo[c]
                    moves[vid] = place(e['cols'][c], yp, fr.lower_offset_mm)
            put(f'eye_{name}_{side}', moves)
    return keys


def key_from_track(cfg, ob, keys):
    """Shape key values per frame from the facial track's morphs: each eye closes with まばたき or its
    wink and smiles with 笑い while open; the vowels share one mouth (scaled down when they add up past
    1); にやり only while the mouth is closed."""
    mo = cfg.face.morphs
    fr = cfg.stage.face_rebuild
    w = face.morph_curves(cfg, [mo.blink, mo.wink_left, mo.wink_right, mo.smile, mo.a, mo.i, mo.u, mo.e,
                                mo.o, mo.wa, mo.smirk])
    close = {'L': np.maximum(w[mo.blink], w[mo.wink_left]), 'R': np.maximum(w[mo.blink], w[mo.wink_right])}
    vals = {}
    for s in ('L', 'R'):
        vals[f'eye_close_{s}'] = close[s]
        vals[f'eye_smile_{s}'] = w[mo.smile] * (1 - close[s])
    vow = {k: w[getattr(mo, k)] for k in ('a', 'i', 'u', 'e', 'o', 'wa')}
    tot = sum(vow.values())
    scale = 1.0 / np.maximum(tot, 1.0)
    for k, v in vow.items():
        vals[k] = v * scale * fr.vowel_gain
    vals['smirk'] = w[mo.smirk] * (1 - np.minimum(tot, 1.0))
    sk = ob.data.shape_keys
    act, cbag = new_action(ob, cfg.project.name + '_FaceKeys', id_type='KEY', id_data=sk)
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    for name, arr in vals.items():
        if name in keys:
            put_curve(cbag, f'key_blocks["{name}"].value', 0, frames, arr.astype(np.float32), group='Face')
    print('[stage] face keys:', {k: round(float(v.max()), 2) for k, v in vals.items()})


def sibling(name):
    """A module next to this file (it may run for another project, as dreamwings/claude)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('face_rebuild_' + name, os.path.join(HERE, name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
