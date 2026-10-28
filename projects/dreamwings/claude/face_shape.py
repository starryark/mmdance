"""Make the front-projected face read as a drawn anime face from every angle (run inside Blender,
from room.py's finish()).

The face painting was projected straight from the front (u, v linear in x, z), so the front view is
right by construction, and a vertex may move along Y (depth) without breaking the painting. Tripo
sculpted a realistic face under it: a nose that stands 7 mm proud, lips, eye sockets. Its shading
and occlusion showed that form as the head turned, and the painted features warped over it.
Productions that render anime faces in 3D (Guilty Gear Xrd, Blue Protocol, Gakumas) do two things,
both done here on the face's own region, fading out toward its edges:
* the relief is taken out of the shape (here: depth only, so the painting stays registered): the
  face front is smoothed to a few percent of its sculpted relief;
* the shading normals come from a simple proxy instead of the surface (an ellipsoid round the
  head), so the light/shadow edge sweeps across the face as one clean curve, with no nose, lip or
  socket shading.
The normals are written as custom normals; they follow the head as the mesh deforms.
"""
import numpy as np


def neighbours(me, verts):
    """Edges among the given vertex indices, as index pairs into `verts`."""
    pos = {v: i for i, v in enumerate(verts)}
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get('vertices', e)
    e = e.reshape(-1, 2)
    keep = np.array([a in pos and b in pos for a, b in e], bool)
    return np.array([[pos[a], pos[b]] for a, b in e[keep]], np.int64)


def adopt_islands(me, fi, max_polys, min_ratio):
    """Patches of other materials set into the face (Tripo gave the mouth slit and the eye corners
    the cloth material, so the painting and the mouth drawings never reached them) join the face:
    material, and UVs from the face's own front projection, fitted on its corners."""
    import collections
    co = np.array([v.co for v in me.vertices])
    mi = np.array([p.material_index for p in me.polygons])
    edge_polys = collections.defaultdict(list)
    for p in me.polygons:
        for ek in p.edge_keys:
            edge_polys[ek].append(p.index)
    fco = co[sorted({v for p in me.polygons if mi[p.index] == fi for v in p.vertices})]
    lo, hi = fco.min(0), fco.max(0)
    def inside(c):                       # in front of the face's back edge, within its outline
        return (lo[[0, 2]] < c[[0, 2]]).all() and (c[[0, 2]] < hi[[0, 2]]).all() and c[1] < hi[1]
    cand = {p.index for p in me.polygons if mi[p.index] != fi and inside(co[list(p.vertices)].mean(0))}
    seen, adopted = set(), []
    for s in cand:
        if s in seen:
            continue
        stack, comp = [s], []
        while stack:
            q = stack.pop()
            if q in seen:
                continue
            seen.add(q)
            comp.append(q)
            stack += [r for ek in me.polygons[q].edge_keys for r in edge_polys[ek] if r in cand and r not in seen]
        if len(comp) > max_polys:
            continue
        cs = set(comp)
        nb = [mi[r] for q in comp for ek in me.polygons[q].edge_keys for r in edge_polys[ek] if r not in cs]
        if nb and sum(1 for m in nb if m == fi) / len(nb) >= min_ratio:
            adopted += comp
    if not adopted:
        return 0
    uvl = me.uv_layers.active.data
    X, U = [], []
    for p in me.polygons:
        if mi[p.index] == fi:
            for v, li in zip(p.vertices, p.loop_indices):
                X.append(co[v])
                U.append(uvl[li].uv[:])
    X, U = np.array(X), np.array(U)
    A = np.c_[X[:, 0], X[:, 2], np.ones(len(X))]
    cu, cv = np.linalg.lstsq(A, U[:, 0], rcond=None)[0], np.linalg.lstsq(A, U[:, 1], rcond=None)[0]
    for q in adopted:
        p = me.polygons[q]
        p.material_index = fi
        for v, li in zip(p.vertices, p.loop_indices):
            a = np.array([co[v][0], co[v][2], 1.0])
            uvl[li].uv = (float(a @ cu), float(a @ cv))
    return len(adopted)


def run(cfg, ob):
    fs = cfg.stage.face_shape
    me = ob.data
    fi = [m.name for m in me.materials].index(fs.material)
    n_adopted = adopt_islands(me, fi, fs.adopt_max_polys, fs.adopt_ratio) if fs.get('adopt_max_polys') else 0
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    mi = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get('material_index', mi)
    face_polys = np.nonzero(mi == fi)[0]
    in_face = np.zeros(len(me.vertices), bool)
    other = np.zeros(len(me.vertices), bool)
    for p in me.polygons:
        (in_face if p.material_index == fi else other)[list(p.vertices)] = True
    verts = np.nonzero(in_face)[0]
    P = co[verts]
    # how far inside the face region each vertex lies (from the vertices it shares with other materials)
    edge = P[other[verts]]
    d_edge = np.min(np.linalg.norm(P[:, None, [0, 2]] - edge[None, :, [0, 2]], axis=2), axis=1) if len(edge) else np.full(len(P), 1.0)
    w = np.clip(d_edge / fs.ramp, 0, 1)
    w = w * w * (3 - 2 * w)
    normals = np.array([n.vector[:] for n in me.corner_normals])
    # 1) relief: Laplacian smoothing of the depth only, the region's border held
    E = neighbours(me, verts)
    y = P[:, 1].copy()
    ys = y.copy()
    deg = np.bincount(E.ravel(), minlength=len(P)).astype(float)
    for _ in range(fs.smooth_iters):
        acc = np.zeros(len(P))
        np.add.at(acc, E[:, 0], ys[E[:, 1]])
        np.add.at(acc, E[:, 1], ys[E[:, 0]])
        avg = np.where(deg > 0, acc / np.maximum(deg, 1), ys)
        ys = ys + 0.6 * (avg - ys) * w
    y_new = ys + fs.detail * (y - ys)
    y_new = y * (1 - w) + y_new * w
    co[verts, 1] = y_new
    me.vertices.foreach_set('co', co.ravel())
    me.update()
    # 2) proxy normals: an ellipsoid round the head, blended in by w at each corner of the face region
    c = np.array(fs.normal_center)
    r = np.array(fs.normal_radii)
    wv = np.zeros(len(me.vertices))
    wv[verts] = w * fs.normal_mix
    loops = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get('vertex_index', loops)
    lp_face = np.zeros(len(me.loops), bool)
    for p in face_polys:
        poly = me.polygons[int(p)]
        lp_face[poly.loop_start:poly.loop_start + poly.loop_total] = True
    g = (co[loops] - c) / (r * r)
    g /= np.linalg.norm(g, axis=1, keepdims=True)
    t = np.where(lp_face, wv[loops], 0.0)[:, None]
    n = normals * (1 - t) + g * t
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    me.normals_split_custom_set(n.tolist())
    moved = np.abs(y_new - y)
    print(f'[stage] face: {n_adopted} polygons of other materials adopted, relief smoothed on '
          f'{int((w > 0.01).sum())} vertices (max {moved.max() * 1000:.1f} mm), proxy normals on {int(lp_face.sum())} corners')
