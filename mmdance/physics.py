"""Stage: simulate the skirt, overskirt and hair lattices and bake them onto their bones.

The body motion is sampled once into the cache (body track), colliders are capsules measured
from the body's skin weights plus the floor and the box colliders (`physics.boxes` and the stage
builder's `colliders()`). The simulation result is cached under a key of everything it depends
on, so it is recomputed only when the motion, the lattice or the parameters change (or with
--resim).
"""
import os
import time

import bpy
import numpy as np

from . import config
from . import solver as ps
from .util import channelbag, hide_others, project_module, put_curve, rig_and_body

SIDES = ('Left', 'Right')
TRACK = ps.TRACK
PARTS = (('sk', 'skirt', 'Skirt', 'Hips'), ('ov', 'overskirt', 'Over', 'Hips'), ('hr', 'hair', 'Hair', 'Head'),
         ('tl', 'tail', 'Tail', 'Hips'))


def params(cfg, part, nrows):
    """Solver parameters for a lattice, as numpy arrays where the config has lists."""
    sec = cfg.tail.physics if part == 'tail' else cfg.physics[part]
    p = {k: (np.array(v, float) if isinstance(v, list) else v) for k, v in sec.items()}
    p.setdefault('goal', np.zeros(nrows))
    sub = cfg.physics.substeps
    p['goal_sub'] = 1 - (1 - np.clip(p['goal'], 0, 0.999)) ** (1.0 / sub)
    p['goal_sub'][0] = 1.0
    if 'elastic' in p:
        p['elastic_sub'] = 1 - (1 - np.clip(p['elastic'], 0, 0.999)) ** (1.0 / sub)
    return p


def gravity(cfg):
    return cfg.physics.gravity or 9.81 * cfg.motion.scale / 0.08    # the character is scale/0.08 of real size


def stage_colliders(cfg):
    """Box colliders: the config's, plus those of a project stage builder that defines colliders()."""
    boxes = [tuple(b) for b in cfg.physics.boxes]
    mod = load_stage_module(cfg)
    if mod is not None and hasattr(mod, 'colliders'):
        boxes += [tuple(b) for b in mod.colliders(cfg)]
    return boxes


def load_stage_module(cfg):
    b = cfg.stage.builder
    if not b or b in ('default', 'set'):              # built in (stage.py)
        return None
    return project_module(cfg, b)


def sample_track(cfg, rig, path, rest):
    if os.path.exists(path) and not cfg.flags.get('resample'):
        return np.load(path)['mats']
    sc = bpy.context.scene
    hidden = hide_others(rig)
    pbs = [rig.pose.bones[cfg.bone(n)] for n in TRACK]
    f0, f1 = cfg.project.frame_start, cfg.project.frame_end
    mats = np.zeros((f1 - f0 + 1, len(TRACK), 4, 4))
    t0 = time.time()
    for i, f in enumerate(range(f0, f1 + 1)):
        sc.frame_set(f)
        for j, pb in enumerate(pbs):
            mats[i, j] = np.array(pb.matrix)
    for o in hidden:
        o.hide_viewport = False
    print(f'[physics] sampled body track {time.time() - t0:.1f}s')
    np.savez(path, mats=mats, rest=rest)          # world matrices per frame, and the rest pose
    return mats


def body_track(cfg, rig):
    """(mats, rest, key): world matrices of the TRACK bones per frame, cached, with their rest pose and
    the cache key. Project code that simulates or keys on the body (sleeves, wings) reads it here."""
    rest = np.array([np.array(rig.data.bones[cfg.bone(n)].matrix_local) for n in TRACK])
    key = cfg.key(config.file_key(cfg.path('motion.vmd')), cfg.motion.scale, cfg.motion.arm_angle,
                  cfg.project.frame_start, cfg.project.frame_end, rest.tolist(),
                  *([cfg.motion.thumb_rest, cfg.motion.hands_apart]
                    if cfg.motion.thumb_rest or cfg.motion.hands_apart else []))
    return sample_track(cfg, rig, cfg.cache(f'body_track_{key}.npz'), rest), rest, key


def sim_key(cfg, motion_key, lat, caps, boxes):
    """Cache key of the simulation: everything it depends on (the post-simulation keys excluded)."""
    return cfg.key(motion_key, {k: v.tolist() for k, v in lat.items()}, sim_params(cfg.physics), boxes,
                   [(c[0], c[1].tolist(), c[2].tolist(), c[3], c[4]) for c in caps],
                   *([sim_params(cfg.tail)] if cfg.tail.enabled else []))


def measure_radius(cfg, ob, bone, a, b, pct=70):
    """Radius of the body around segment a-b: distance of the bone's dominant verts to the segment."""
    gi = {g.name: g.index for g in ob.vertex_groups}
    if bone not in gi:
        return None
    me = ob.data
    dists = []
    names = {g.index: g.name for g in ob.vertex_groups}
    outline = cfg.character.outline_group
    for v in me.vertices:
        best = max(((g.weight, names[g.group]) for g in v.groups if names[g.group] != outline), default=(0, ''))
        if best[1] != bone or best[0] < 0.5:
            continue
        p = np.array(v.co)
        ab = b - a
        t = np.clip((p - a) @ ab / (ab @ ab), 0, 1)
        dists.append(np.linalg.norm(p - (a + t * ab)))
    return float(np.percentile(dists, pct)) if dists else None


def build_colliders(cfg, ob, rig):
    """Collider capsules in rest space: list of (track_bone_index, a_rest, b_rest, radius, tags).

    Tags: S = collides with skirt/panels, H = with hair. Radii are measured from the mesh where
    possible and clamped to a sane range for a ~1 m character.
    """
    bones = rig.data.bones
    ti = {n: i for i, n in enumerate(TRACK)}

    def hd(n):
        return np.array(bones[cfg.bone(n)].head_local)

    def tl(n):
        return np.array(bones[cfg.bone(n)].tail_local)
    caps = []

    def add(bone, a, b, r_default, tags, r_min=0.0, r_max=1.0, measure=True):
        raw = measure_radius(cfg, ob, cfg.bone(bone), a, b) if measure else None
        r = r_default if raw is None else float(np.clip(raw, r_min, r_max))
        caps.append((ti[bone], a, b, r, tags))
        print(f'[physics] collider {bone:14s} r={r:.3f} tags={tags}' + ('' if raw is None else f' (measured {raw:.3f})'))
    add('Hips', hd('LeftUpLeg') + [0.01, 0.01, 0.0], hd('RightUpLeg') + [-0.01, 0.01, 0.0], 0.075, 'SH', measure=False)
    add('Spine', hd('Spine'), tl('Spine'), 0.07, 'H', 0.05, 0.09)
    add('Spine1', hd('Spine1'), tl('Spine1'), 0.07, 'H', 0.05, 0.09)
    add('Spine2', hd('Spine2'), tl('Spine2'), 0.075, 'H', 0.05, 0.09)
    add('Neck', hd('Neck'), tl('Neck'), 0.035, 'H', 0.025, 0.045)
    hc = hd('Head') + 0.5 * (tl('Head') - hd('Head'))
    add('Head', hc + [0, 0.005, -0.01], hc + [0, 0.01, 0.02], 0.075, 'H', measure=False)
    for s_ in SIDES:
        add(s_ + 'Arm', hd(s_ + 'Arm'), tl(s_ + 'Arm'), 0.05, 'SH', 0.035, 0.07)
        add(s_ + 'ForeArm', hd(s_ + 'ForeArm'), tl(s_ + 'ForeArm'), 0.035, 'SH', 0.025, 0.05)
        add(s_ + 'Hand', hd(s_ + 'Hand'), tl(s_ + 'HandMiddle3'), 0.022, 'SH', measure=False)
        th_a, th_b = hd(s_ + 'UpLeg'), tl(s_ + 'UpLeg')
        add(s_ + 'UpLeg', th_a, th_a + 0.4 * (th_b - th_a), 0.045, 'SH', 0.03, 0.06)
        add(s_ + 'UpLeg', th_a + 0.4 * (th_b - th_a), th_b, 0.05, 'SH', 0.045, 0.065)
        add(s_ + 'Leg', hd(s_ + 'Leg'), tl(s_ + 'Leg'), 0.045, 'S', 0.03, 0.06)
        add(s_ + 'Foot', hd(s_ + 'Foot'), tl(s_ + 'ToeBase'), 0.035, 'S', measure=False)
    return caps


def rest_consistent(caps, L, tag, floor=0.02, gap=0.003):
    """Shrink capsules so that no free lattice particle penetrates them in the rest pose."""
    out = []
    free = ~L.pinned
    for bi, a, b, r, tags in caps:
        if tag in tags:
            ab = b - a
            t = np.clip((L.rest[free] - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
            d = np.linalg.norm(L.rest[free] - (a + t[:, None] * ab), axis=1) - L.radius[free]
            allowed = d.min() - gap
            if allowed < r:
                print(f'[physics] {L.name}: collider on {TRACK[bi]} shrunk {r:.3f} -> {max(allowed, floor):.3f}')
                r = max(allowed, floor)
        out.append((bi, a, b, r, tags))
    return out


def caps_at(caps, Dm, tag):
    out = []
    for bi, a, b, r, tags in caps:
        if tag not in tags:
            continue
        M = Dm[bi]
        out.append((M[:3, :3] @ a + M[:3, 3], M[:3, :3] @ b + M[:3, 3], r))
    return out


def lattices(cfg, rest, lat):
    """The solver lattices present in this project: dict key -> ps.Lattice."""
    ti = {n: i for i, n in enumerate(TRACK)}
    L = {}
    if 'sk_pts' in lat:
        n = lat['sk_pts'].shape[1]
        L['sk'] = ps.Lattice('skirt', lat['sk_pts'], lat['sk_len'], rest[ti['Hips']], True,
                             params(cfg, 'skirt', n), cfg.physics.skirt.radius)
    if 'hr_pts' in lat:
        hr_rad = np.array([lat['hr_thick'][c, k] for c in range(lat['hr_pts'].shape[0]) for k in range(lat['hr_len'][c])])
        L['hr'] = ps.Lattice('hair', lat['hr_pts'], lat['hr_len'], rest[ti['Head']], False,
                             params(cfg, 'hair', lat['hr_pts'].shape[1]), np.clip(hr_rad * 0.7 + 0.008, 0.01, 0.03),
                             lat['hr_breaks'] if 'hr_breaks' in lat else ())
    if 'ov_pts' in lat:
        L['ov'] = ps.Lattice('over', lat['ov_pts'], lat['ov_len'], rest[ti['Hips']], False,
                             params(cfg, 'overskirt', lat['ov_pts'].shape[1]), cfg.physics.overskirt.radius)
    if 'tl_pts' in lat:
        tl_rad = np.array([lat['tl_thick'][c, k] for c in range(2) for k in range(lat['tl_len'][c])])
        L['tl'] = ps.Lattice('tail', lat['tl_pts'], lat['tl_len'], rest[ti['Hips']], False,
                             params(cfg, 'tail', lat['tl_pts'].shape[1]),
                             np.maximum(tl_rad - cfg.tail.width / 2, 0.006))
        L['tl'].pinned = L['tl'].row < cfg.tail.pinned_rows      # the part inside the body rides the hips
    return L


def push_subset(x, m, rad, sk, hips_D, outer, axis):
    """skirt_surface_push on the particles in mask m only."""
    xs = x[m]
    ps.skirt_surface_push(xs, rad[m], sk, hips_D, outer, axis)
    x[m] = xs


def simulate(cfg, mats, rest, caps, lat, boxes, path):
    """Run the lattices over the dance. Returns particle positions per frame for each lattice."""
    ti = {n: i for i, n in enumerate(TRACK)}
    inv_rest = np.linalg.inv(rest)
    nf = mats.shape[0]
    hips_i, head_i = ti['Hips'], ti['Head']
    sub = cfg.physics.substeps
    sim = ps.Sim(cfg.project.fps, sub, gravity(cfg), boxes)
    L = lattices(cfg, rest, lat)
    sk, ov, hr, tl = L.get('sk'), L.get('ov'), L.get('hr'), L.get('tl')
    if sk is not None:
        sk_outer = lat['sk_thick'] + 0.004
        # hair rides over the panels where they exist: margin = rest gap between skirt and panel surface
        sk_outer_hair = sk_outer.copy()
        if ov is not None:
            for ci, c in enumerate(lat['ov_cols']):
                for k in range(lat['ov_len'][ci]):
                    ri = np.hypot(*(lat['sk_pts'][c, k, :2] - np.array(lat['sk_axis'])))
                    ro = np.hypot(*(lat['ov_pts'][ci, k, :2] - np.array(lat['sk_axis'])))
                    sk_outer_hair[c, k] = max(sk_outer_hair[c, k], ro - ri + lat['ov_thick'][ci, k] + 0.004)
        caps = rest_consistent(caps, sk, 'S')
    if ov is not None:
        caps = rest_consistent(caps, ov, 'S')
    if hr is not None:
        caps = rest_consistent(caps, hr, 'H')
    if tl is not None:              # the tail's own copy: it must not shrink the skirt's colliders
        caps_tl = rest_consistent(caps, tl, 'S')
        tl_free = tl.row >= cfg.tail.pinned_rows
    out = {k: np.zeros((nf, l.n, 3)) for k, l in L.items()}

    def delta(f):
        return mats[f] @ inv_rest                         # rest-world -> world, per track bone

    D0 = delta(0)
    for k, l in L.items():
        l.init(mats[0, head_i if k == 'hr' else hips_i])
    t0 = time.time()
    prev = D0
    last = cfg.flags.get('until') or nf
    schedule = [0] * cfg.physics.preroll + list(range(last))
    for step, f in enumerate(schedule):
        cur = delta(f)
        for s in range(1, sub + 1):
            a = s / sub
            Dm = np.array([ps.lerp_mat4(prev[j], cur[j], a) for j in range(len(TRACK))])
            root_h = Dm[hips_i] @ rest[hips_i]
            root_c = Dm[head_i] @ rest[head_i]
            caps_s = caps_at(caps, Dm, 'S')
            hips_D = Dm[hips_i]
            upright = hips_D[2, 2] > 0.8            # the skirt-cone surface tests only make sense upright
            if sk is not None:
                sim.step_lattice(sk, root_h, rest[hips_i][:3, :3], caps_s)
            if ov is not None:
                # panels lie on the skirt: keep them outside its current surface
                ov_push = (lambda x: ps.skirt_surface_push(x, ov.radius, sk, hips_D, sk_outer, lat['sk_axis'])) if upright else None
                sim.step_lattice(ov, root_h, rest[hips_i][:3, :3], caps_s, extra=ov_push)
            if hr is not None:
                push = None
                if sk is not None and upright:
                    push = (lambda x: ps.skirt_surface_push(x, hr.radius, sk, hips_D, sk_outer_hair, lat['sk_axis']))
                sim.step_lattice(hr, root_c, rest[head_i][:3, :3], caps_at(caps, Dm, 'H'), extra=push)
            if tl is not None:
                # the tail hangs outside the skirt (its pinned root rows are inside it)
                tl_push = None
                if sk is not None and upright:
                    tl_push = (lambda x: push_subset(x, tl_free, tl.radius, sk, hips_D, sk_outer, lat['sk_axis']))
                sim.step_lattice(tl, root_h, rest[hips_i][:3, :3], caps_at(caps_tl, Dm, 'S'), extra=tl_push)
        prev = cur
        if step >= cfg.physics.preroll:
            for k, l in L.items():
                out[k][f] = l.x
        if step % 300 == 0:
            print(f'[physics] sim step {step}/{len(schedule)}  {time.time() - t0:.0f}s')
    if not cfg.flags.get('until'):          # a partial run must not pass for the full simulation
        np.savez(path, **out)
    return out, L


def frames_for(X, L, side=None):
    """Orthonormal frame per bone (column c, row k) from lattice neighbours.

    Neighbours across a cut link (L.breaks) don't count; a chain with no linked neighbour takes
    its lateral axis from `side` (the root bone's own side axis at this frame)."""
    F = {}
    for (c, k), i in L.id_of.items():
        if k + 1 >= L.lens[c]:
            continue
        y = X[L.id_of[(c, k + 1)]] - X[i]

        def nb(cc):
            if L.wrap:
                cc %= L.ncol
            if cc < 0 or cc >= L.ncol or min(c, cc) in L.breaks:
                return None
            return X[L.id_of[(cc, min(k, L.lens[cc] - 1))]]
        l_, r_ = nb(c - 1), nb(c + 1)
        lat = (r_ if r_ is not None else X[i]) - (l_ if l_ is not None else X[i])
        if l_ is None and r_ is None and side is not None:
            lat = side
        y = y / (np.linalg.norm(y) + 1e-9)
        x = lat - (lat @ y) * y
        n = np.linalg.norm(x)
        if n < 1e-6:
            x = np.cross(y, [0, 0, 1.0])
            n = np.linalg.norm(x) + 1e-9
        x /= n
        z = np.cross(x, y)
        F[(c, k)] = np.stack([x, y, z], axis=1)
    return F


POST_KEYS = ('smooth_frames', 'sway')     # applied after the simulation: not part of its cache key


def sim_params(sec):
    """A config section without the post-simulation keys (nested sections too)."""
    return {k: (sim_params(v) if isinstance(v, dict) else v) for k, v in sec.items() if k not in POST_KEYS}


def gauss_time(a, sigma):
    """Gaussian filter along axis 0 with edge padding (numpy only: Blender has no scipy)."""
    r = int(np.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.concatenate([np.repeat(a[:1], r, 0), a, np.repeat(a[-1:], r, 0)])
    out = np.zeros_like(a)
    for i, w in enumerate(k):
        out += w * pad[i:i + len(a)]
    return out


def smooth_in_time(cfg, mats, sims, L):
    """Low-pass each lattice in its root bone's frame (`smooth_frames`: Gaussian sigma in frames).

    Removes the frame-to-frame jitter that contact corrections leave, without touching the
    swing: the body's own motion is taken out first, so only the fabric's motion is filtered."""
    ti = {n: i for i, n in enumerate(TRACK)}
    out = dict(sims)
    for key, part, _, root in PARTS:
        if key not in L:
            continue
        sec = cfg.tail.physics if part == 'tail' else cfg.physics[part]
        sig = sec.get('smooth_frames', 0.0)
        if sig <= 0:
            continue
        R, o = mats[:, ti[root], :3, :3], mats[:, ti[root], :3, 3]
        X = sims[key]
        loc = np.einsum('fji,fnj->fni', R, X - o[:, None, :])
        loc = gauss_time(loc, sig)
        out[key] = np.einsum('fij,fnj->fni', R, loc) + o[:, None, :]
    return out


def tail_sway(cfg, quats, names, nf):
    """A living tail: a slow side-to-side swish travelling down the chain, on top of its physics."""
    amp, period, lag = cfg.tail.sway
    if not amp:
        return
    rows = max(k for _, k in names) + 1
    f = np.arange(nf) + cfg.project.frame_start
    for (c, k), q in quats.items():
        a = np.radians(amp) * (k / max(rows - 1, 1)) * np.sin(2 * np.pi * (f - k * lag) / period)
        s = np.stack([np.cos(a / 2), 0 * a, 0 * a, np.sin(a / 2)], 1)          # about the bone's own Z
        w1, x1, y1, z1 = q.T
        w2, x2, y2, z2 = s.T
        quats[(c, k)] = np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                                  w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], 1)


def bake(cfg, rig, mats, rest, sims, L):
    ti = {n: i for i, n in enumerate(TRACK)}
    bones = rig.data.bones
    cbag = channelbag(rig)
    for fc in list(cbag.fcurves):          # drop old physics curves
        if any(p + '_' in fc.data_path for _, _, p, _ in PARTS):
            cbag.fcurves.remove(fc)
    nf = mats.shape[0]
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    for key, _, prefix, root in PARTS:
        if key not in L:
            continue
        lat, X = L[key], sims[key]
        side_rest = rest[ti[root]][:3, 0] if lat.breaks else None
        Frest = frames_for(lat.rest, lat, side_rest)
        names = {(c, k): f'{prefix}_{c:02d}_{k}' for (c, k) in Frest}
        M = {ck: np.array(bones[n].matrix_local) for ck, n in names.items()}
        Mroot = rest[ti[root]]
        quats = {ck: np.zeros((nf, 4)) for ck in names}
        locs = {ck: np.zeros((nf, 3)) for ck in names}
        for f in range(nf):
            Fcur = frames_for(X[f], lat, mats[f, ti[root]][:3, 0] if lat.breaks else None)
            D = {}
            for (c, k) in sorted(names, key=lambda t: t[1]):
                R = Fcur[(c, k)] @ Frest[(c, k)].T
                Db = np.eye(4)
                Db[:3, :3] = R @ M[(c, k)][:3, :3]
                Db[:3, 3] = X[f][lat.id_of[(c, k)]]
                if k == 0:
                    Mp, Dp = Mroot, mats[f, ti[root]]
                else:
                    Mp, Dp = M[(c, k - 1)], D[(c, k - 1)]
                D[(c, k)] = Db
                B = np.linalg.inv(M[(c, k)]) @ Mp @ np.linalg.inv(Dp) @ Db
                q = ps.quat_from_mat(B[:3, :3])
                if f and np.dot(quats[(c, k)][f - 1], q) < 0:
                    q = -q
                quats[(c, k)][f] = q
                locs[(c, k)][f] = B[:3, 3]
        if key == 'tl' and cfg.tail.sway[0]:
            tail_sway(cfg, quats, names, nf)
        for ck, n in names.items():
            dp = f'pose.bones["{n}"]'
            for j in range(4):
                put_curve(cbag, dp + '.rotation_quaternion', j, frames, quats[ck][:, j], group=n)
            for j in range(3):
                put_curve(cbag, dp + '.location', j, frames, locs[ck][:, j], group=n)


def run(cfg):
    rig, ob = rig_and_body(cfg)
    lat = dict(np.load(cfg.cache('lattice.npz'), allow_pickle=True))
    if not any(k in lat for k in ('sk_pts', 'hr_pts', 'tl_pts')):
        print('[physics] no skirt, hair or tail lattice: nothing to simulate')
        return
    mats, rest, motion_key = body_track(cfg, rig)
    caps = build_colliders(cfg, ob, rig)
    boxes = stage_colliders(cfg)
    path = cfg.cache(f'sim_{sim_key(cfg, motion_key, lat, caps, boxes)}.npz')
    t0 = time.time()
    if os.path.exists(path) and not cfg.flags.get('resim') and not cfg.flags.get('until'):
        d = np.load(path)
        sims, L = {k: d[k] for k in d.files}, lattices(cfg, rest, lat)
        print(f'[physics] reusing {os.path.basename(path)}')
    else:
        sims, L = simulate(cfg, mats, rest, caps, lat, boxes, path)
        print(f'[physics] simulated in {time.time() - t0:.0f}s')
    if cfg.flags.get('until'):
        return
    t0 = time.time()
    sims = smooth_in_time(cfg, mats, sims, L)
    bake(cfg, rig, mats, rest, sims, L)
    print(f'[physics] baked in {time.time() - t0:.0f}s')
