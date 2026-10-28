"""Stage: physics bones for the skirt, overskirt and hair, their skin weights, and weight repairs.

* Hair: a curtain of bone chains following the hair mass, rooted on the head. The hair surface
  is first ripped from the clothing below `hair.rip_below` (auto-riggers often fuse hair tips
  to the dress), so locks swing without dragging cloth along.
* Skirt: a ring of bone chains (columns round the hips, rows down to the hem) laid on the
  skirt's inner surface, rooted on the hips.
* Overskirt: an outer gown layer (found by raycasting, see layers.py) on its own chains, its
  weights blended with the skirt's across the folds where the layers meet.
* Vertices are weighted from their (angle, height) position on the lattice; the root band
  blends into the hips / head. Optional repairs fix common auto-rig weight errors.
The lattice layout is saved to the cache for the physics stage.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import hands, layers
from .util import rig_and_body


def sk_phi_fn(axis):
    """Skirt angle: 0 = front (-Y), increasing toward +X (model's left)."""
    def phi(xy):
        return np.arctan2(xy[..., 0] - axis[0], -(xy[..., 1] - axis[1]))
    phi.front = True
    return phi


def hr_phi_fn(axis):
    """Hair angle: 0 = back (+Y), + toward +X."""
    def phi(xy):
        return np.arctan2(xy[..., 0] - axis[0], xy[..., 1] - axis[1])
    phi.front = False
    return phi


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def mesh_arrays(me):
    n = len(me.vertices)
    co = np.zeros(n * 3)
    me.vertices.foreach_get('co', co)
    return co.reshape(-1, 3)


def material_index(me, name):
    mats = [m.name for m in me.materials]
    if name not in mats:
        raise RuntimeError(f'material {name!r} is not on {me.name}: {mats}')
    return mats.index(name)


def rip_hair(cfg, ob):
    me = ob.data
    hi = material_index(me, cfg.hair.material)
    bm = bmesh.new()
    bm.from_mesh(me)
    edges = []
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) < 2:
            continue
        kinds = {f.material_index == hi for f in lf}
        if len(kinds) == 2 and max(v.co.z for v in e.verts) < cfg.hair.rip_below:
            edges.append(e)
    bmesh.ops.split_edges(bm, edges=edges)
    bm.to_mesh(me)
    bm.free()
    me.update()
    print(f'[rig] ripped {len(edges)} hair/cloth seam edges')


def islands(me):
    """Connected-component id per vertex."""
    parent = np.arange(len(me.vertices))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in me.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            parent[a] = b
    return np.array([find(i) for i in range(len(me.vertices))])


def classify(cfg, ob):
    """Vertex masks: hair, skirt, legs (their own mesh island), hair/cloth seam."""
    me = ob.data
    n = len(me.vertices)
    hi = material_index(me, cfg.hair.material) if cfg.hair.material else -1
    sk_mats = {material_index(me, m) for m in cfg.skirt.materials}
    hair_f = np.zeros(n, bool)
    other_f = np.zeros(n, bool)
    skirt_mat = np.zeros(n, bool)
    for p in me.polygons:
        if p.material_index == hi:
            hair_f[list(p.vertices)] = True
        else:
            other_f[list(p.vertices)] = True
        if p.material_index in sk_mats:
            skirt_mat[list(p.vertices)] = True
    comp = islands(me)                     # legs are often a separate island under the skirt
    co = mesh_arrays(me)
    ids, counts = np.unique(comp, return_counts=True)
    legs = None
    for c, k in zip(ids, counts):          # the island reaching the floor and spanning the leg height
        m = comp == c
        if co[m, 2].min() < 0.01 and co[m, 2].max() > cfg.legs.min_top and np.abs(co[m, 0]).max() < cfg.legs.max_abs_x:
            legs = c
    hair = hair_f & ~other_f
    if cfg.hair.adopt_head_islands:
        hair |= head_islands(cfg, ob, comp, hair_f)
    leg_mask = comp == legs
    if cfg.legs.attach > 0 and leg_mask.any():
        leg_mask |= attached_islands(co, comp, leg_mask, cfg.legs.attach)
    skirt = other_f & ~hair_f & ~hair & (co[:, 2] < cfg.skirt.top) & ~leg_mask
    if sk_mats:
        skirt &= skirt_mat
    return co, hair, skirt, leg_mask, hair_f & other_f


def attached_islands(co, comp, legs, dist):
    """Small islands lying on the legs (shoe buckles, straps): every vertex within `dist` of them."""
    from mathutils.kdtree import KDTree
    lv = np.nonzero(legs)[0]
    kd = KDTree(len(lv))
    for i in lv:
        kd.insert(co[i], int(i))
    kd.balance()
    out = np.zeros(len(co), bool)
    for c in np.unique(comp[~legs]):
        m = np.nonzero(comp == c)[0]
        if all(kd.find(co[i])[2] < dist for i in m):
            out[m] = True
    print(f'[rig] {len(np.unique(comp[out]))} small islands on the legs ({out.sum()} vertices) join them')
    return out


def head_islands(cfg, ob, comp, hair_f):
    """Curls an auto-rigger gave another material: islands with no hair faces whose vertices
    mostly follow the head bone, below the top of the hair chains. They join the hair."""
    names = {g.index: g.name for g in ob.vertex_groups}
    skip = cfg.character.outline_group
    head = np.array([max(((g.weight, names[g.group]) for g in v.groups if names[g.group] != skip),
                         default=(0, ''))[1] == cfg.bone('Head') for v in ob.data.vertices])
    z = mesh_arrays(ob.data)[:, 2]
    out = np.zeros(len(comp), bool)
    for c in np.unique(comp[head & (z < cfg.hair.rows_z[0])]):
        m = comp == c
        if not (m & hair_f).any() and head[m].mean() > 0.8:
            out |= m
    print(f'[rig] {len(np.unique(comp[out]))} head-weighted islands ({out.sum()} vertices) joined the hair')
    return out


def column_points(co, sel, phis, rows_z, phi_fn, axis, mode, allow_empty=False):
    """Chain joint positions for each (column, row) from the vertices in each bin.

    allow_empty: columns without any vertices stay NaN (the overskirt drops them) instead of
    raising."""
    ph = phi_fn(co[sel, :2])
    z = co[sel, 2]
    r = np.hypot(co[sel, 0] - axis[0], co[sel, 1] - axis[1])
    pts = np.full((len(phis), len(rows_z), 3), np.nan)
    rad = np.zeros((len(phis), len(rows_z)))
    cnt = np.zeros((len(phis), len(rows_z)), int)
    dphi = np.abs(np.diff(phis)).mean() if len(phis) > 1 else 0.4
    for c, p0 in enumerate(phis):
        for k, z0 in enumerate(rows_z):
            for widen in (1.0, 1.5, 2.2, 3.0):
                m = (np.abs(wrap(ph - p0)) < 0.6 * dphi * widen) & (np.abs(z - z0) < 0.035 * widen)
                if widen == 1.0:
                    cnt[c, k] = m.sum()
                if m.sum() >= 4:
                    break
            if m.sum() < 2:
                continue
            if mode == 'inner':           # skirt: innermost layer, so legs collide with the inner fabric
                rr = np.percentile(r[m], 15)
                rad[c, k] = np.percentile(r[m], 85) - rr
                ang = p0
            elif mode == 'median':        # overskirt panels: middle of the panel fabric
                rr = np.median(r[m])
                rad[c, k] = np.percentile(r[m], 90) - rr
                ang = p0
            else:                         # hair: middle of the hair mass in this bin
                cx, cy = co[sel][m, 0].mean(), co[sel][m, 1].mean()
                rr = np.hypot(cx - axis[0], cy - axis[1])
                ang = phi_fn(np.array([cx, cy]))
                rad[c, k] = max(rr - np.percentile(r[m], 10), 0.0)
            if phi_fn.front:
                pts[c, k] = (axis[0] + rr * math.sin(ang), axis[1] - rr * math.cos(ang), z0)
            else:
                pts[c, k] = (axis[0] + rr * math.sin(ang), axis[1] + rr * math.cos(ang), z0)
    # fill holes from vertical neighbours
    for c in range(len(phis)):
        for k in range(len(rows_z)):
            if np.isnan(pts[c, k, 0]):
                ks = [j for j in range(len(rows_z)) if not np.isnan(pts[c, j, 0])]
                if not ks and allow_empty:
                    break
                if not ks:
                    raise RuntimeError(f'lattice column {c} found no vertices: check rows_z / axis / materials')
                j = min(ks, key=lambda j: abs(j - k))
                pts[c, k] = pts[c, j]
                pts[c, k, 2] = rows_z[k]
    return pts, rad, cnt


def chain_lengths(cnt, min_count=6):
    """Joints per column: contiguous rows from the root that actually contain hair."""
    lens = []
    for c in range(cnt.shape[0]):
        valid = [k for k in range(cnt.shape[1]) if cnt[c, k] >= min_count]
        lens.append(max(max(valid) + 1 if valid else 3, 3))
    return np.array(lens)


def smooth_xy(pts, lens, iters=2):
    for _ in range(iters):
        new = pts.copy()
        for c in range(pts.shape[0]):
            for k in range(1, lens[c]):
                acc, wsum = pts[c, k, :2] * 2.0, 2.0
                for cc in (c - 1, c + 1):
                    if 0 <= cc < pts.shape[0] and k < lens[cc]:
                        acc += pts[cc, k, :2]
                        wsum += 1
                for kk in (k - 1, k + 1):
                    if kk < lens[c]:
                        acc += pts[c, kk, :2] * 0.5
                        wsum += 0.5
                new[c, k, :2] = acc / wsum
        pts = new
    return pts


def lattice_weights(co, sel, phis, rows_z, phi_fn, wrap_cols):
    """Per-vertex weights over (column, bone-row); returns idx arrays and weights, plus root weight."""
    ph = phi_fn(co[sel, :2])
    z = co[sel, 2]
    ncol, nseg = len(phis), len(rows_z) - 1
    # column interpolation
    if wrap_cols:
        step = 2 * np.pi / ncol
        f = ((ph - phis[0]) % (2 * np.pi)) / step
        c0 = np.floor(f).astype(int) % ncol
        c1 = (c0 + 1) % ncol
        a = f - np.floor(f)
    else:
        f = np.interp(ph, phis, np.arange(ncol))
        c0 = np.clip(np.floor(f).astype(int), 0, ncol - 1)
        c1 = np.clip(c0 + 1, 0, ncol - 1)
        a = f - c0
    # row parameter t: 0 at the root joint, k at joint k
    zr = np.array(rows_z)
    t = np.interp(-z, -zr, np.arange(len(zr)))
    t = np.where(z > zr[0], (zr[0] - z) / (zr[0] - zr[1]), t)      # above root: negative
    t = np.where(z < zr[-1], nseg + (zr[-1] - z) / (zr[-2] - zr[-1]), t)
    roww = np.zeros((len(z), nseg))
    for k in range(nseg):
        roww[:, k] = np.clip(1 - np.abs(t - (k + 0.5)), 0, 1)
    roww[:, nseg - 1] = np.where(t > nseg - 0.5, 1.0, roww[:, nseg - 1])
    roww[:, 0] = np.where(t < 0.5, np.clip(0.5 + t, 0, 1) * 1.0, roww[:, 0])
    # smooth root blend: the first bone takes over from the parent over half a segment
    root_w = np.clip(1 - roww.sum(1), 0, 1)
    return c0, c1, a, roww, root_w


def add_chain_bones(rig, prefix, pts, parent_name, lens, roll_axis):
    eb = rig.data.edit_bones
    names = []
    ncol = pts.shape[0]
    for c in range(ncol):
        prev = eb[parent_name]
        col = []
        for k in range(lens[c] - 1):
            nm = f'{prefix}_{c:02d}_{k}'
            if nm in eb:
                eb.remove(eb[nm])
            b = eb.new(nm)
            b.head = Vector(pts[c, k])
            b.tail = Vector(pts[c, k + 1])
            if (b.tail - b.head).length < 1e-3:
                b.tail = b.head + Vector((0, 0, -0.02))
            # local Z points away from the lattice axis (outward)
            out = Vector((pts[c, k, 0], pts[c, k, 1], 0)) - Vector((roll_axis[0], roll_axis[1], 0))
            if out.length > 1e-4:
                b.align_roll(out.normalized())
            b.parent = prev
            b.use_connect = False
            b.use_deform = True
            prev = b
            col.append(nm)
        names.append(col)
    return names


def set_weights(cfg, ob, verts, groups_w):
    """groups_w: dict group_name -> weight array aligned with verts. Clears all other deform groups."""
    keep = {cfg.character.outline_group}
    for g in ob.vertex_groups:
        if g.name in keep:
            continue
        g.remove([int(v) for v in verts])
    for gname, w in groups_w.items():
        g = ob.vertex_groups.get(gname) or ob.vertex_groups.new(name=gname)
        nz = np.nonzero(w > 1e-4)[0]
        for i in nz:
            g.add([int(verts[i])], float(w[i]), 'REPLACE')


def build_weights(co, sel, phis, rows_z, phi_fn, wrap_cols, names, root_bone):
    """Lattice skin weights (normalized, root bone included) for the selected vertices."""
    idx = np.nonzero(sel)[0]
    c0, c1, a, roww, root_w = lattice_weights(co, sel, phis, rows_z, phi_fn, wrap_cols)
    groups = {}
    nseg = roww.shape[1]
    for k in range(nseg):
        for cc, wc in ((c0, 1 - a), (c1, a)):
            w = wc * roww[:, k]
            for c in range(len(phis)):
                m = cc == c
                if not m.any():
                    continue
                g = names[c][min(k, len(names[c]) - 1)]
                if g not in groups:
                    groups[g] = np.zeros(len(idx))
                groups[g][m] += w[m]
    groups[root_bone] = root_w
    tot = sum(groups.values())
    for g in groups:
        groups[g] = groups[g] / np.maximum(tot, 1e-6)
    return idx, groups


def overskirt_lattice(cfg, ob, co, skirt, sk_pts, sk_phis, sk_phi):
    """Panel chains for the outer gown layer, ordered round the back from the front opening."""
    ax = cfg.skirt.axis
    rows = cfg.skirt.rows_z
    allow = None
    if cfg.overskirt.phi_range:              # only this arc may be an outer layer (an apron)
        a0, a1 = np.radians(cfg.overskirt.phi_range)
        allow = (sk_phi(co[:, :2]) >= a0) & (sk_phi(co[:, :2]) <= a1) & (co[:, 2] >= cfg.overskirt.zbottom)
    lab, soft = layers.classify_layers(ob, np.nonzero(skirt)[0], cfg.overskirt.ztop, tuple(ax), allow)
    outer = skirt & (lab > 0.5)
    ov_all, ov_thick_all, ov_cnt = column_points(co, outer, sk_phis, rows, sk_phi, ax, 'median',
                                                 allow_empty=allow is not None)
    present = ov_cnt.sum(1) >= cfg.overskirt.min_vertices
    # panel rows above the overskirt (merged with the skirt at the waist) follow the skirt surface,
    # and a panel always hangs at least min_gap outside the skirt
    gap_min = cfg.overskirt.min_gap
    for c in range(len(sk_phis)):
        for k in range(len(rows)):
            ri = np.hypot(sk_pts[c, k, 0] - ax[0], sk_pts[c, k, 1] - ax[1])
            ro = np.hypot(ov_all[c, k, 0] - ax[0], ov_all[c, k, 1] - ax[1])
            if ov_cnt[c, k] < 3 and k <= 2:
                ro = ri + gap_min
            ro = max(ro, ri + gap_min)
            a = sk_phis[c]
            ov_all[c, k, :2] = (ax[0] + ro * math.sin(a), ax[1] - ro * math.cos(a))
    ov_lens_all = np.array([max([k for k in range(len(rows)) if ov_cnt[c, k] >= 4] + [2]) + 1 for c in range(len(sk_phis))])
    cols = np.nonzero(present)[0]
    gap = np.nonzero(~present)[0]
    gap_ang = math.atan2(np.sin(sk_phis[gap]).sum(), np.cos(sk_phis[gap]).sum()) if len(gap) else 0.0

    def ov_phi(xy):
        return (sk_phi(xy) - gap_ang) % (2 * np.pi)
    ov_phi.front = True
    ov_phis_u = (sk_phis[cols] - gap_ang) % (2 * np.pi)
    order = np.argsort(ov_phis_u)
    cols, ov_phis_u = cols[order], ov_phis_u[order]
    print('[rig] overskirt panel columns', cols.tolist(), 'joints', ov_lens_all[cols].tolist())
    return dict(pts=ov_all[cols], len=ov_lens_all[cols], thick=ov_thick_all[cols], cols=cols, phis=ov_phis_u,
                gap=gap_ang, phi_fn=ov_phi, soft=soft)


def hair_locks(cfg, ob, co, hair):
    """Bone chains along the hair's own locks (hair.mode = "locks").

    Below `split_z` the hair mesh falls apart into separate locks (its connected pieces). Each
    lock gets its own chain; a wide lock (a sheet of fused curls) gets one chain per
    `lock_width` degrees. Joints sit every `joint_step` down from `root_z` (pinned, riding the
    head): at the centroid of the lock's own vertices below the split, of the hair mass over the
    lock's arc higher up. Chains of different locks are not linked (`breaks`), so each lock
    swings on its own, as the locks of hand-rigged models do."""
    hc = cfg.hair
    me = ob.data
    E = np.array([e.vertices[:] for e in me.edges])
    phi = np.degrees(hr_phi_fn(hc.axis)(co[:, :2]))
    low = hair & (co[:, 2] < hc.split_z)
    parent = np.arange(len(co))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in E[low[E[:, 0]] & low[E[:, 1]]]:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = np.array([find(i) for i in range(len(co))])
    ids, counts = np.unique(comp[low], return_counts=True)
    chains = []
    for lk in ids[counts >= hc.min_lock]:
        m = low & (comp == lk)
        lo, hi = np.percentile(phi[m], 3), np.percentile(phi[m], 97)
        k = max(1, int(np.ceil((hi - lo) / hc.lock_width)))
        cuts = np.linspace(lo, hi, k + 1)
        for j in range(k):
            a = -1e9 if j == 0 else cuts[j]
            b = 1e9 if j == k - 1 else cuts[j + 1]
            chains.append(dict(lock=int(lk), sel=m & (phi >= a) & (phi < b), phi=0.5 * (cuts[j] + cuts[j + 1]),
                               lo=cuts[j], hi=cuts[j + 1]))
    chains.sort(key=lambda c: c['phi'])
    step = hc.joint_step
    pts, thick, lens = [], [], []
    for ch in chains:
        zmin = co[ch['sel'], 2].min()
        n = min(hc.max_joints, max(3, int(np.ceil((hc.root_z - zmin) / step - 0.35)) + 1))
        levels = hc.root_z - step * np.arange(n)
        P, T = [], []
        for z in levels:
            if z >= hc.split_z:          # still in the hair mass: its middle over this lock's arc
                m = hair & (np.abs(co[:, 2] - z) < step * 0.6) & (phi > ch['lo'] - 6) & (phi < ch['hi'] + 6)
            else:
                m = ch['sel'] & (np.abs(co[:, 2] - z) < step * 0.6)
            if m.sum() < 3:
                P.append(None)
                T.append(0.01)
                continue
            P.append(co[m].mean(0))
            T.append(float(np.median(np.linalg.norm(co[m] - co[m].mean(0), axis=1))))
        for i, q in enumerate(P):              # gaps (a curl's turn): the nearest filled level
            if q is None:
                j = min((j for j in range(n) if P[j] is not None), key=lambda j: abs(j - i))
                P[i] = P[j].copy()
        P = np.array(P)
        P[:, 2] = levels
        pts.append(P)
        thick.append(T)
        lens.append(n)
        ch['levels'] = levels
    nrow = max(lens)
    pts_a = np.array([np.vstack([p] + [p[-1:]] * (nrow - len(p))) for p in pts])
    thick_a = np.array([t + [t[-1]] * (nrow - len(t)) for t in thick])
    breaks = np.array([c for c in range(len(chains) - 1) if chains[c]['lock'] != chains[c + 1]['lock']], int)
    print(f'[rig] hair locks: {int((counts >= hc.min_lock).sum())} locks, {len(chains)} chains, joints {lens}')
    return dict(pts=pts_a, len=np.array(lens), thick=thick_a, chains=chains, comp=comp, low=low, phi=phi, breaks=breaks)


def hair_lock_weights(cfg, ob, co, hair, hl, names, head):
    """Each vertex follows its own lock's chain(s) (across a sheet's chains by angle), along the
    chain by height; above the split by angle over all chains; smoothed over the mesh so the
    locks part without seams. Hair above root_z + root_band rides the head."""
    hc = cfg.hair
    chains, phi = hl['chains'], hl['phi']
    idx = np.nonzero(hair & (co[:, 2] < hc.root_z + hc.root_band))[0]
    col0 = np.cumsum([0] + [len(n) for n in names])
    W = np.zeros((len(idx), col0[-1]))
    by_lock = {}
    for c, ch in enumerate(chains):
        by_lock.setdefault(ch['lock'], []).append(c)
    allc = list(range(len(chains)))
    joints = np.concatenate([hl['pts'][c, :hl['len'][c]] for c in allc])
    joint_c = np.concatenate([[c] * hl['len'][c] for c in allc])

    def between(cands, p):
        """Bilinear by angle among candidate chains (sorted by angle)."""
        ph = np.array([chains[c]['phi'] for c in cands])
        if len(cands) == 1 or p <= ph[0]:
            return [(cands[0], 1.0)]
        if p >= ph[-1]:
            return [(cands[-1], 1.0)]
        j = int(np.searchsorted(ph, p)) - 1
        t = (p - ph[j]) / max(ph[j + 1] - ph[j], 1e-6)
        return [(cands[j], 1 - t), (cands[j + 1], t)]
    for r, v in enumerate(idx):
        z = co[v, 2]
        if hl['low'][v] and hl['comp'][v] in by_lock:
            cw = between(by_lock[hl['comp'][v]], phi[v])
        elif hl['low'][v]:                    # a scrap too small to be a lock: the nearest chain
            cw = [(int(joint_c[np.argmin(np.linalg.norm(joints - co[v], axis=1))]), 1.0)]
        else:
            cw = between(allc, phi[v])
        for c, wc in cw:
            lv = chains[c]['levels']
            nseg = len(lv) - 1
            t = float(np.interp(-z, -lv, np.arange(len(lv))))
            if z > lv[0]:
                t = (lv[0] - z) / (lv[0] - lv[1])
            for k in range(nseg):
                w = max(0.0, 1 - abs(t - (k + 0.5)))
                if k == nseg - 1 and t > nseg - 0.5:
                    w = 1.0
                if k == 0 and t < 0.5:
                    w = min(1.0, max(0.0, 0.5 + t))
                W[r, col0[c] + k] += wc * w
    # smooth over the hair surface, so the locks part without seams
    pos = {int(v): r for r, v in enumerate(idx)}
    nb = [[] for _ in idx]
    for e in ob.data.edges:
        a, b = e.vertices
        if a in pos and b in pos:
            nb[pos[a]].append(pos[b])
            nb[pos[b]].append(pos[a])
    for _ in range(hc.smooth):
        W = np.array([0.5 * W[r] + 0.5 * W[nb[r]].mean(0) if nb[r] else W[r] for r in range(len(idx))])
    groups = {}
    flat = [n for col in names for n in col]
    for j, gname in enumerate(flat):
        groups[gname] = W[:, j]
    groups[head] = np.clip(1 - W.sum(1), 0, 1)
    tot = sum(groups.values())
    for g in groups:
        groups[g] = groups[g] / np.maximum(tot, 1e-6)
    return idx, groups


def tail_island(cfg, ob, co):
    """Vertex mask of the tail: the mesh island nearest to `tail.seed`."""
    comp = islands(ob.data)
    seed = int(np.argmin(np.linalg.norm(co - np.array(cfg.tail.seed), axis=1)))
    return comp == comp[seed]


def geodesic(me, sel, src):
    """Edge-path distance from the `src` vertices over the selected vertices (Dijkstra)."""
    import heapq
    co = mesh_arrays(me)
    adj = {}
    for e in me.edges:
        a, b = e.vertices
        if sel[a] and sel[b]:
            w = float(np.linalg.norm(co[a] - co[b]))
            adj.setdefault(a, []).append((b, w))
            adj.setdefault(b, []).append((a, w))
    dist = np.full(len(co), np.inf)
    heap = [(0.0, int(v)) for v in src]
    for _, v in heap:
        dist[v] = 0.0
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for u, w in adj.get(v, ()):
            if d + w < dist[u]:
                dist[u] = d + w
                heapq.heappush(heap, (d + w, u))
    return dist


def tail_lattice(cfg, ob, rig, co, tail):
    """Two side-by-side chains along the tail (two columns give the bones a stable twist).

    Joints sit at equal distances from the root along the surface (the end nearest the hips),
    at the centroid of each distance band, offset to either side along the normal of the
    tail's plane (its axis of least spread)."""
    hips = np.array(rig.data.bones[cfg.bone('Hips')].head_local)
    idx = np.nonzero(tail)[0]
    dh = np.linalg.norm(co[idx] - hips, axis=1)
    dist = geodesic(ob.data, tail, idx[dh < dh.min() + 0.01])
    d = dist[idx]
    n = cfg.tail.rows
    step = d.max() / (n - 1)
    cen = np.zeros((n, 3))
    thick = np.zeros(n)
    for k in range(n):
        m = np.abs(d - k * step) < 0.5 * step if 0 < k < n - 1 else np.abs(d - k * step) < 0.35 * step
        p = co[idx[m]]
        cen[k] = p.mean(0)
        thick[k] = np.median(np.linalg.norm(p - cen[k], axis=1))
    _, _, vt = np.linalg.svd(cen - cen.mean(0))
    side = vt[2] * cfg.tail.width / 2
    pts = np.stack([cen - side, cen + side])
    print('[rig] tail: %d vertices, %.3f m long, %d joints, radius %s' % (len(idx), d.max(), n, np.round(thick, 3).tolist()))
    return dict(pts=pts, len=np.array([n, n]), thick=np.stack([thick, thick]), t=d / step,
                s=(co[idx] - cen[np.clip(np.round(d / step).astype(int), 0, n - 1)]) @ (vt[2] / np.linalg.norm(vt[2])),
                idx=idx)


def tail_weights(cfg, tl, names):
    """Weights along the tail (bone k spans joints k..k+1) and across its two columns."""
    t, n = tl['t'], tl['len'][0]
    nseg = n - 1
    roww = np.stack([np.clip(1 - np.abs(t - (k + 0.5)), 0, 1) for k in range(nseg)], 1)
    roww[:, 0] = np.where(t < 0.5, 1.0, roww[:, 0])
    roww[:, -1] = np.where(t > nseg - 0.5, 1.0, roww[:, -1])
    roww /= roww.sum(1, keepdims=True)
    a = np.clip(0.5 + tl['s'] / max(cfg.tail.width, 1e-6), 0, 1)
    groups = {}
    for k in range(nseg):
        groups[names[0][k]] = roww[:, k] * (1 - a)
        groups[names[1][k]] = roww[:, k] * a
    return groups


def fix_nape(cfg, ob, seam):
    """Hair/cloth seam vertices at the nape: only neck/head may move them."""
    B = cfg.bone
    outline = cfg.character.outline_group
    names = {g.index: g.name for g in ob.vertex_groups}
    allowed = {B('Neck'), B('Head'), B('Spine2'), outline}
    fixed = 0
    for vi in np.nonzero(seam)[0]:
        v = ob.data.vertices[int(vi)]
        ws = {names[g.group]: g.weight for g in v.groups}
        if all(n in allowed for n in ws):
            continue
        keep = {n: w for n, w in ws.items() if n in allowed and n != outline}
        tot = sum(keep.values())
        if tot < 1e-4:
            keep, tot = {B('Neck'): 0.5, B('Head'): 0.5}, 1.0
        for n in ws:
            if n != outline:
                ob.vertex_groups[n].remove([int(vi)])
        for n, w in keep.items():
            ob.vertex_groups[n].add([int(vi)], w / tot, 'REPLACE')
        fixed += 1
    print(f'[rig] cleaned {fixed} nape seam vertices')


def fix_waist(cfg, ob, co, hair, skirt, legs):
    """Bodice/waist above the skirt must not follow the thighs."""
    B = cfg.bone
    z0, z1 = cfg.fixes.waist_z
    names = {g.index: g.name for g in ob.vertex_groups}
    waist = np.nonzero(~hair & ~skirt & ~legs & (co[:, 2] >= z0) & (co[:, 2] < z1))[0]
    leg_groups = {B(n) for n in ('LeftUpLeg', 'RightUpLeg', 'LeftLeg', 'RightLeg')}
    moved = 0
    for vi in waist:
        v = ob.data.vertices[int(vi)]
        lw = sum(g.weight for g in v.groups if names[g.group] in leg_groups)
        if lw < 1e-4:
            continue
        for gname in leg_groups:
            if gname in ob.vertex_groups:
                ob.vertex_groups[gname].remove([int(vi)])
        hw = next((g.weight for g in v.groups if names[g.group] == B('Hips')), 0.0)
        ob.vertex_groups[B('Hips')].add([int(vi)], hw + lw, 'REPLACE')
        moved += 1
    print(f'[rig] moved thigh weights to Hips on {moved} waist vertices')


def fix_cross_side_legs(cfg, ob, co, hair, skirt):
    """Strip opposite-side leg weights below the crotch (they smear a membrane between the feet)."""
    B = cfg.bone
    outline = cfg.character.outline_group
    names = {g.index: g.name for g in ob.vertex_groups}
    side_groups = {s_: {B(s_ + n) for n in ('UpLeg', 'Leg', 'Foot', 'ToeBase')} for s_ in ('Left', 'Right')}
    cleaned = 0
    for vi in np.nonzero(~hair & ~skirt & (co[:, 2] < cfg.fixes.cross_side_legs_below))[0]:
        x = co[vi, 0]
        if abs(x) < 0.002:
            continue
        wrong = side_groups['Right' if x > 0 else 'Left']
        v = ob.data.vertices[int(vi)]
        ws = {names[g.group]: g.weight for g in v.groups if names[g.group] != outline}
        bad = [n for n in ws if n in wrong and ws[n] > 0]
        if not bad:
            continue
        keep = {n: w for n, w in ws.items() if n not in wrong}
        tot = sum(keep.values())
        for n in bad:
            ob.vertex_groups[n].remove([int(vi)])
        if tot < 1e-4:          # only had wrong-side weights: mirror them onto this side
            for n in bad:
                role = cfg.role(n)
                twin = cfg.bone(role.replace('Right', 'Left') if x > 0 else role.replace('Left', 'Right'))
                ob.vertex_groups[twin].add([int(vi)], ws[n], 'ADD')
        else:
            for n, w in keep.items():
                ob.vertex_groups[n].add([int(vi)], w / tot, 'REPLACE')
        cleaned += 1
    print(f'[rig] removed cross-side leg weights on {cleaned} vertices')


def fix_unweighted(cfg, ob):
    """Vertices with no deform weight stay behind at the rest pose (long streaks once she moves):
    they take the weights of the nearest weighted vertex."""
    from mathutils.kdtree import KDTree
    skip = cfg.character.outline_group
    names = {g.index: g.name for g in ob.vertex_groups}
    w = [{names[g.group]: g.weight for g in v.groups if names[g.group] != skip and g.weight > 1e-4}
         for v in ob.data.vertices]
    bad = [i for i, d in enumerate(w) if not d]
    if not bad:
        return
    good = [i for i, d in enumerate(w) if d]
    kd = KDTree(len(good))
    for i in good:
        kd.insert(ob.data.vertices[i].co, i)
    kd.balance()
    for i in bad:
        _, j, _ = kd.find(ob.data.vertices[i].co)
        for n, x in w[j].items():
            ob.vertex_groups[n].add([i], x, 'REPLACE')
    print(f'[rig] {len(bad)} unweighted vertices took the weights of their nearest neighbour')


def fix_rigid_boots(cfg, ob, rig, co, legs):
    """Stiff partition along the leg chain: shaft -> shin, foot -> foot bone, toe cap -> toe bone."""
    B = cfg.bone
    bones = rig.data.bones
    rew = 0
    for side, sgn in (('Left', 1), ('Right', -1)):
        knee_z = bones[B(side + 'Leg')].head_local.z
        ank = bones[B(side + 'Foot')].head_local
        toe_y = bones[B(side + 'ToeBase')].head_local.y
        vs = np.nonzero(legs & (co[:, 0] * sgn > 0))[0]
        z, y = co[vs, 2], co[vs, 1]

        def ss_(e0, e1, v):
            t = np.clip((v - e0) / (e1 - e0), 0, 1)
            return t * t * (3 - 2 * t)
        w_up = ss_(knee_z - 0.02, knee_z + 0.035, z)                 # thigh above the knee
        w_foot_zone = 1 - ss_(ank.z - 0.012, ank.z + 0.022, z)       # at/below the ankle
        w_toe = ss_(toe_y + 0.012, toe_y - 0.010, y) * w_foot_zone    # forward of the toe joint
        groups_w = {B(side + 'UpLeg'): w_up * (1 - w_foot_zone),
                    B(side + 'Leg'): (1 - w_up) * (1 - w_foot_zone),
                    B(side + 'Foot'): w_foot_zone - w_toe,
                    B(side + 'ToeBase'): w_toe}
        if cfg.fixes.rigid_boots_hips:       # a leg mesh reaching the pelvis: its top follows the hips
            hip_z = bones[B(side + 'UpLeg')].head_local.z
            w_hip = ss_(hip_z - 0.05, hip_z + 0.02, z)
            groups_w[B(side + 'UpLeg')] *= 1 - w_hip
            groups_w[B('Hips')] = w_hip
        set_weights(cfg, ob, vs, groups_w)
        rew += len(vs)
    print(f'[rig] boots/stockings re-weighted rigidly: {rew} vertices')


def run(cfg):
    rig, ob = rig_and_body(cfg)
    B = cfg.bone
    if cfg.hands.enabled:
        hands.replace_hands(cfg, ob, rig)
    if cfg.hair.enabled:
        rip_hair(cfg, ob)
    co, hair, skirt, legs, seam = classify(cfg, ob)
    if cfg.tail.enabled:                     # a tail is its own island: keep it out of the skirt
        tail = tail_island(cfg, ob, co)
        skirt &= ~tail
        tl = tail_lattice(cfg, ob, rig, co, tail)
    print(f'[rig] hair verts {hair.sum()}, skirt verts {skirt.sum()}, leg verts {legs.sum()}')
    lat = {}
    sk_ax, hr_ax = cfg.skirt.axis, cfg.hair.axis
    sk_phi, hr_phi = sk_phi_fn(sk_ax), hr_phi_fn(hr_ax)
    roll_axis = hr_ax if cfg.hair.enabled else sk_ax
    if cfg.skirt.enabled:
        sk_rows = cfg.skirt.rows_z
        sk_phis = np.radians(np.arange(cfg.skirt.columns) * 360.0 / cfg.skirt.columns)
        sk_pts, sk_thick, _ = column_points(co, skirt, sk_phis, sk_rows, sk_phi, sk_ax, 'inner')
        sk_len = np.full(cfg.skirt.columns, len(sk_rows))
        lat.update(sk_pts=sk_pts, sk_thick=sk_thick, sk_len=sk_len, sk_phis=sk_phis, sk_axis=np.array(sk_ax))
        ov = overskirt_lattice(cfg, ob, co, skirt, sk_pts, sk_phis, sk_phi) if cfg.overskirt.enabled else None
    if cfg.hair.enabled and cfg.hair.mode == 'locks':
        hl = hair_locks(cfg, ob, co, hair)
        hr_pts, hr_len = hl['pts'], hl['len']
        lat.update(hr_pts=hr_pts, hr_thick=hl['thick'], hr_len=hr_len, hr_breaks=hl['breaks'],
                   hr_phis=np.radians([c['phi'] for c in hl['chains']]))
    elif cfg.hair.enabled:
        hr_rows = cfg.hair.rows_z
        hr_phis = np.radians(np.linspace(cfg.hair.phi_range[0], cfg.hair.phi_range[1], cfg.hair.columns))
        hsel = hair & (co[:, 2] < hr_rows[0] + cfg.hair.root_band)
        hr_pts, hr_thick, hr_cnt = column_points(co, hsel, hr_phis, hr_rows, hr_phi, hr_ax, 'mass')
        hr_len = chain_lengths(hr_cnt, cfg.hair.min_count)
        hr_pts = smooth_xy(hr_pts, hr_len)
        print('[rig] hair chain joints per column', hr_len.tolist())
        lat.update(hr_pts=hr_pts, hr_thick=hr_thick, hr_len=hr_len, hr_phis=hr_phis)

    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    if cfg.skirt.enabled:
        sk_names = add_chain_bones(rig, 'Skirt', sk_pts, B('Hips'), sk_len, roll_axis)
        if ov is not None:
            ov_names = add_chain_bones(rig, 'Over', ov['pts'], B('Hips'), ov['len'], roll_axis)
    if cfg.hair.enabled:
        hr_names = add_chain_bones(rig, 'Hair', hr_pts, B('Head'), hr_len, roll_axis)
    if cfg.tail.enabled:
        tl_names = add_chain_bones(rig, 'Tail', tl['pts'], B('Hips'), tl['len'], roll_axis)
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        if pb.name.startswith(('Skirt_', 'Hair_', 'Over_', 'Tail_')):
            pb.rotation_mode = 'QUATERNION'

    if cfg.skirt.enabled:
        # gown layers: the inner skirt keeps the Skirt chains, the overskirt panels get their own
        # Over chains, blended across the folds where the layers meet
        sidx = np.nonzero(skirt)[0]
        in_idx, in_groups = build_weights(co, skirt, sk_phis, sk_rows, sk_phi, True, sk_names, B('Hips'))
        if ov is not None:
            soft = ov['soft']
            ov_sel = skirt & (soft > 0.01)
            if ov_sel.any():
                o_idx, o_groups = build_weights(co, ov_sel, ov['phis'], sk_rows, ov['phi_fn'], False, ov_names, B('Hips'))
                pos = {int(v): i for i, v in enumerate(in_idx)}
                sw = soft[o_idx]
                for g in in_groups:
                    in_groups[g] = in_groups[g].copy()
                    in_groups[g][[pos[int(v)] for v in o_idx]] *= (1 - sw)
                rows = np.array([pos[int(v)] for v in o_idx])
                for g, w in o_groups.items():
                    arr = in_groups.get(g, np.zeros(len(in_idx)))
                    arr = arr.copy()
                    arr[rows] += w * sw
                    in_groups[g] = arr
            print(f'[rig] gown: {int((soft[sidx] > 0.5).sum())} overskirt vertices on {len(ov_names)} panel chains')
            lat.update(ov_pts=ov['pts'], ov_len=ov['len'], ov_thick=ov['thick'], ov_cols=ov['cols'],
                       ov_phis=ov['phis'], ov_gap=ov['gap'])
        set_weights(cfg, ob, in_idx, in_groups)
    if cfg.hair.enabled:
        if cfg.hair.mode == 'locks':
            idx, groups = hair_lock_weights(cfg, ob, co, hair, hl, hr_names, B('Head'))
            top_z = cfg.hair.root_z + cfg.hair.root_band
        else:
            idx, groups = build_weights(co, hsel, hr_phis, hr_rows, hr_phi, False, hr_names, B('Head'))
            top_z = hr_rows[0] + cfg.hair.root_band
        set_weights(cfg, ob, idx, groups)
        # hair above the root ring (scalp, bangs) rides the head only
        top = np.nonzero(hair & (co[:, 2] >= top_z))[0]
        set_weights(cfg, ob, top, {B('Head'): np.ones(len(top))})

    if cfg.fixes.nape_seam:
        fix_nape(cfg, ob, seam)
    if cfg.fixes.waist_z:
        fix_waist(cfg, ob, co, hair, skirt, legs)
    if cfg.fixes.cross_side_legs_below > 0:
        fix_cross_side_legs(cfg, ob, co, hair, skirt)
    if cfg.fixes.rigid_boots:
        fix_rigid_boots(cfg, ob, rig, co, legs)
    if cfg.tail.enabled:
        set_weights(cfg, ob, tl['idx'], tail_weights(cfg, tl, tl_names))
        lat.update(tl_pts=tl['pts'], tl_len=tl['len'], tl_thick=tl['thick'])
    if cfg.fixes.unweighted:
        fix_unweighted(cfg, ob)
    np.savez(cfg.cache('lattice.npz'), **lat)
    return lat
