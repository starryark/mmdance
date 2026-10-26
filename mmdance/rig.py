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
    # connected components (legs are often a separate island under the skirt)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in me.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            parent[a] = b
    comp = np.array([find(i) for i in range(n)])
    co = mesh_arrays(me)
    ids, counts = np.unique(comp, return_counts=True)
    legs = None
    for c, k in zip(ids, counts):          # the island reaching the floor and spanning the leg height
        m = comp == c
        if co[m, 2].min() < 0.01 and co[m, 2].max() > cfg.legs.min_top and np.abs(co[m, 0]).max() < cfg.legs.max_abs_x:
            legs = c
    hair = hair_f & ~other_f
    skirt = other_f & ~hair_f & (co[:, 2] < cfg.skirt.top) & (comp != legs)
    if sk_mats:
        skirt &= skirt_mat
    return co, hair, skirt, comp == legs, hair_f & other_f


def column_points(co, sel, phis, rows_z, phi_fn, axis, mode):
    """Chain joint positions for each (column, row) from the vertices in each bin."""
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
    lab, soft = layers.classify_layers(ob, np.nonzero(skirt)[0], cfg.overskirt.ztop, tuple(ax))
    outer = skirt & (lab > 0.5)
    ov_all, ov_thick_all, ov_cnt = column_points(co, outer, sk_phis, rows, sk_phi, ax, 'median')
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
    if cfg.hair.enabled:
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
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        if pb.name.startswith(('Skirt_', 'Hair_', 'Over_')):
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
        idx, groups = build_weights(co, hsel, hr_phis, hr_rows, hr_phi, False, hr_names, B('Head'))
        set_weights(cfg, ob, idx, groups)
        # hair above the root ring (scalp, bangs) rides the head only
        top = np.nonzero(hair & (co[:, 2] >= hr_rows[0] + cfg.hair.root_band))[0]
        set_weights(cfg, ob, top, {B('Head'): np.ones(len(top))})

    if cfg.fixes.nape_seam:
        fix_nape(cfg, ob, seam)
    if cfg.fixes.waist_z:
        fix_waist(cfg, ob, co, hair, skirt, legs)
    if cfg.fixes.cross_side_legs_below > 0:
        fix_cross_side_legs(cfg, ob, co, hair, skirt)
    if cfg.fixes.rigid_boots:
        fix_rigid_boots(cfg, ob, rig, co, legs)
    np.savez(cfg.cache('lattice.npz'), **lat)
    return lat
