"""Bell-sleeve physics for the ChatGPT character: the sleeves hang from the forearms and swing.

Called from room.finish() when [stage.sleeves] is set, after the physics stage has simulated the
skirt. Also runnable on a built scene (--until N simulates only the first N frames, for tuning):

  blender -b build/ChatGPT_ChikaDance.blend --python sleeves.py -- project.toml [--until N] [--resim]

The model prep gave each sleeve a 5 x 6 grid of bone chains (Sleeve_L/R_cc_k): columns along the
forearm, rows down the bell. Rigidly carried by the forearm, a raised arm lifts the sleeve like a
board; here the chains are simulated with mmdance's solver instead, like the skirt and hair:
jointed chains under gravity with weak joint springs (the fabric hangs down whatever the arm
does), linked across the columns, kept out of the torso, legs, the other arm and the skirt's
current surface, and baked to keys. The top joints ride the arm where the sleeve is sewn on:
blended from the upper arm to the forearm across the elbow, as the skin weights are. The result
is cached under a key of everything it depends on, like the skirt.
"""
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mmdance import config, motion, physics  # noqa: E402
from mmdance import solver as ps  # noqa: E402
from mmdance.util import channelbag, put_curve, rig_and_body  # noqa: E402

TRACK = ps.TRACK
SIDES = (('Left', 'L'), ('Right', 'R'))


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


class SleeveLattice(ps.Lattice):
    """A lattice whose top row rides two bones: the root (forearm) and, near the elbow, the upper arm.

    Set `arm` to the upper arm's current world matrix before each step."""

    def __init__(self, *a, arm_rest, attach_fore, **kw):
        super().__init__(*a, **kw)
        inv = np.linalg.inv(arm_rest)
        self.local_arm = (inv[:3, :3] @ self.rest.T).T + inv[:3, 3]
        self.wf = attach_fore[:, None]
        self.arm = arm_rest

    def goals(self, root):
        g = super().goals(root)
        ga = (self.arm[:3, :3] @ self.local_arm.T).T + self.arm[:3, 3]
        p = self.pinned
        g[p] = self.wf[p] * g[p] + (1 - self.wf[p]) * ga[p]
        return g


def chain_names(rig, s):
    cols = sorted({b.name.split('_')[2] for b in rig.data.bones if b.name.startswith(f'Sleeve_{s}_')})
    rows = 1 + max(int(b.name.split('_')[3]) for b in rig.data.bones if b.name.startswith(f'Sleeve_{s}_'))
    return [[f'Sleeve_{s}_{c}_{k}' for k in range(rows)] for c in cols]


def layout(rig, s):
    """Joint positions (ncol, nrow, 3): each chain's bone heads and its last tail."""
    names = chain_names(rig, s)
    bones = rig.data.bones
    return np.array([[np.array(bones[n].head_local) for n in col] + [np.array(bones[col[-1]].tail_local)]
                     for col in names]), names


def params(sec, nrows, substeps):
    p = {k: (np.array(v, float) if isinstance(v, list) else v) for k, v in sec.items()}
    p.setdefault('goal', np.zeros(nrows))
    p['goal_sub'] = 1 - (1 - np.clip(p['goal'], 0, 0.999)) ** (1.0 / substeps)
    p['goal_sub'][0] = 1.0
    p['elastic_sub'] = 1 - (1 - np.clip(p['elastic'], 0, 0.999)) ** (1.0 / substeps)
    return p


def skirt_track(cfg, rig, ob, rest, mats, motion_key):
    """The skirt lattice and its simulated (smoothed) particle positions per frame, or None."""
    lat = dict(np.load(cfg.cache('lattice.npz'), allow_pickle=True))
    if 'sk_pts' not in lat:
        return None
    caps = physics.build_colliders(cfg, ob, rig)
    boxes = physics.stage_colliders(cfg)
    sim_key = cfg.key(motion_key, {k: v.tolist() for k, v in lat.items()}, physics.sim_params(cfg.physics), boxes,
                      [(c[0], c[1].tolist(), c[2].tolist(), c[3], c[4]) for c in caps],
                      *([physics.sim_params(cfg.tail)] if cfg.tail.enabled else []))
    path = cfg.cache(f'sim_{sim_key}.npz')
    if not os.path.exists(path):
        print(f'[sleeves] no skirt simulation {os.path.basename(path)}: sleeves are not kept outside the skirt')
        return None
    d = np.load(path)
    L = physics.lattices(cfg, rest, lat)
    sims = physics.smooth_in_time(cfg, mats, {k: d[k] for k in d.files}, L)
    return dict(sk=L['sk'], X=sims['sk'], outer=lat['sk_thick'] + 0.004, axis=lat['sk_axis'], key=sim_key)


def colliders(cfg, ob, rig, side):
    """Body capsules a sleeve meets: everything but its own arm (it is sewn onto that)."""
    out = []
    for bi, a, b, r, tags in physics.build_colliders(cfg, ob, rig):
        name = TRACK[bi]
        if name.startswith(side) and name[len(side):] in ('Arm', 'ForeArm', 'Hand'):
            continue
        out.append((bi, a, b, r, 'V'))
    return out


def simulate(cfg, lats, caps, mats, rest, boxes, skirt, until):
    ti = {n: i for i, n in enumerate(TRACK)}
    inv_rest = np.linalg.inv(rest)
    nf = mats.shape[0]
    sub = cfg.physics.substeps
    sim = ps.Sim(cfg.project.fps, sub, physics.gravity(cfg), boxes)
    need = sorted({ti['Hips']} | {c[0] for cs in caps.values() for c in cs}
                  | {ti[s + n] for s, _ in SIDES for n in ('Arm', 'ForeArm')})
    out = {s: np.zeros((nf, L.n, 3)) for s, L in lats.items()}
    for side, s in SIDES:
        L = lats[s]
        L.arm = mats[0, ti[side + 'Arm']]
        L.init(mats[0, ti[side + 'ForeArm']])
    prev = {j: mats[0, j] @ inv_rest[j] for j in need}
    last = until or nf
    schedule = [0] * cfg.physics.preroll + list(range(last))
    t0 = time.time()
    fprev = 0
    for step, f in enumerate(schedule):
        cur = {j: mats[f, j] @ inv_rest[j] for j in need}
        for k in range(1, sub + 1):
            a = k / sub
            Dm = {j: ps.lerp_mat4(prev[j], cur[j], a) for j in need}
            Dfull = np.repeat(np.eye(4)[None], len(TRACK), 0)
            for j, m in Dm.items():
                Dfull[j] = m
            hips_D = Dm[ti['Hips']]
            upright = skirt is not None and hips_D[2, 2] > 0.8      # the skirt-cone test needs her upright
            if upright:
                skirt['sk'].x = skirt['X'][fprev] * (1 - a) + skirt['X'][f] * a
            for side, s in SIDES:
                L = lats[s]
                fa, arm = ti[side + 'ForeArm'], ti[side + 'Arm']
                L.arm = Dm[arm] @ rest[arm]
                push = ((lambda x, L=L: ps.skirt_surface_push(x, L.radius, skirt['sk'], hips_D, skirt['outer'],
                                                              skirt['axis'])) if upright else None)
                sim.step_lattice(L, Dm[fa] @ rest[fa], rest[fa][:3, :3], physics.caps_at(caps[s], Dfull, 'V'),
                                 extra=push)
        prev, fprev = cur, f
        if step >= cfg.physics.preroll:
            for s, L in lats.items():
                out[s][f] = L.x
        if step % 300 == 0:
            print(f'[sleeves] sim step {step}/{len(schedule)}  {time.time() - t0:.0f}s')
    return out


def bake(cfg, rig, mats, lats, names, sims):
    """Keys on the sleeve bones from the simulated joints (as mmdance's physics.bake does)."""
    ti = {n: i for i, n in enumerate(TRACK)}
    bones = rig.data.bones
    cbag = channelbag(rig)
    for fc in list(cbag.fcurves):
        if 'Sleeve_' in fc.data_path:
            cbag.fcurves.remove(fc)
    nf = mats.shape[0]
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    for side, s in SIDES:
        L, X = lats[s], sims[s]
        Frest = physics.frames_for(L.rest, L)
        nm = {(c, k): names[s][c][k] for (c, k) in Frest}
        M = {ck: np.array(bones[n].matrix_local) for ck, n in nm.items()}
        fa = ti[side + 'ForeArm']
        Mroot = np.array(bones[cfg.bone(side + 'ForeArm')].matrix_local)
        quats = {ck: np.zeros((nf, 4)) for ck in nm}
        locs = {ck: np.zeros((nf, 3)) for ck in nm}
        for f in range(nf):
            Fcur = physics.frames_for(X[f], L)
            D = {}
            for (c, k) in sorted(nm, key=lambda t: t[1]):
                Db = np.eye(4)
                Db[:3, :3] = Fcur[(c, k)] @ Frest[(c, k)].T @ M[(c, k)][:3, :3]
                Db[:3, 3] = X[f][L.id_of[(c, k)]]
                Mp, Dp = (Mroot, mats[f, fa]) if k == 0 else (M[(c, k - 1)], D[(c, k - 1)])
                D[(c, k)] = Db
                B = np.linalg.inv(M[(c, k)]) @ Mp @ np.linalg.inv(Dp) @ Db
                q = ps.quat_from_mat(B[:3, :3])
                if f and np.dot(quats[(c, k)][f - 1], q) < 0:
                    q = -q
                quats[(c, k)][f] = q
                locs[(c, k)][f] = B[:3, 3]
        for ck, n in nm.items():
            dp = f'pose.bones["{n}"]'
            for j in range(4):
                put_curve(cbag, dp + '.rotation_quaternion', j, frames, quats[ck][:, j], group=n)
            for j in range(3):
                put_curve(cbag, dp + '.location', j, frames, locs[ck][:, j], group=n)


def run(cfg, until=0, resim=False):
    sec = cfg.stage.sleeves
    rig, ob = rig_and_body(cfg)
    rest = np.array([np.array(rig.data.bones[cfg.bone(n)].matrix_local) for n in TRACK])
    motion_key = cfg.key(config.file_key(cfg.path('motion.vmd')), cfg.motion.scale, cfg.motion.arm_angle,
                         cfg.project.frame_start, cfg.project.frame_end, rest.tolist(),
                         *([cfg.motion.thumb_rest, cfg.motion.hands_apart]
                           if cfg.motion.thumb_rest or cfg.motion.hands_apart else []))
    mats = physics.sample_track(cfg, rig, cfg.cache(f'body_track_{motion_key}.npz'), rest)
    skirt = skirt_track(cfg, rig, ob, rest, mats, motion_key) if sec.get('skirt', True) else None
    boxes = physics.stage_colliders(cfg)
    lats, names, caps = {}, {}, {}
    for side, s in SIDES:
        pts, names[s] = layout(rig, s)
        elbow_x = rig.data.bones[cfg.bone(side + 'ForeArm')].head_local.x
        sg = 1 if side == 'Left' else -1
        p = params(sec, pts.shape[1], cfg.physics.substeps)
        attach = smoothstep((sg * (pts[:, :, 0] - elbow_x) + 0.015) / 0.03)       # forearm share
        fa = np.array(rig.data.bones[cfg.bone(side + 'ForeArm')].matrix_local)
        arm = np.array(rig.data.bones[cfg.bone(side + 'Arm')].matrix_local)
        L = SleeveLattice('sleeve_' + s, pts, np.full(len(pts), pts.shape[1]), fa, False, p, sec.radius,
                          arm_rest=arm, attach_fore=attach.reshape(-1))
        lats[s] = L
        caps[s] = physics.rest_consistent(colliders(cfg, ob, rig, side), L, 'V')
    key = cfg.key(motion_key, skirt['key'] if skirt else '', {s: L.rest.tolist() for s, L in lats.items()},
                  physics.sim_params(sec), boxes,
                  {s: [(c[0], c[1].tolist(), c[2].tolist(), c[3]) for c in cs] for s, cs in caps.items()},
                  cfg.physics.substeps, cfg.physics.preroll, physics.gravity(cfg))
    path = cfg.cache(f'sleeves_{key}.npz')
    t0 = time.time()
    if os.path.exists(path) and not resim and not until:
        d = np.load(path)
        sims = {s: d[s] for s in d.files}
        print(f'[sleeves] reusing {os.path.basename(path)}')
    else:
        sims = simulate(cfg, lats, caps, mats, rest, boxes, skirt, until)
        print(f'[sleeves] simulated in {time.time() - t0:.0f}s')
        if until:
            return sims
        np.savez(path, **sims)
    sig = sec.get('smooth_frames', 0.0)
    if sig > 0:                                   # low-pass in the forearm's frame, as physics does
        ti = {n: i for i, n in enumerate(TRACK)}
        for side, s in SIDES:
            R, o = mats[:, ti[side + 'ForeArm'], :3, :3], mats[:, ti[side + 'ForeArm'], :3, 3]
            loc = np.einsum('fji,fnj->fni', R, sims[s] - o[:, None, :])
            sims[s] = np.einsum('fij,fnj->fni', R, physics.gauss_time(loc, sig)) + o[:, None, :]
    bake(cfg, rig, mats, lats, names, sims)
    print(f'[sleeves] baked {sum(len(c) * len(c[0]) for c in names.values())} bones')
    return sims


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--') + 1:]
    cfg = config.load(args[0])
    cfg.flags = {}
    motion.resolve(cfg)
    until = int(args[args.index('--until') + 1]) if '--until' in args else 0
    run(cfg, until=until, resim='--resim' in args)
    if not until:
        bpy.ops.wm.save_mainfile()
        print('[sleeves] saved', bpy.data.filepath)
