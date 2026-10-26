"""Generate anime hands from the rig's finger bones (system Python: numpy, scikit-image).

Auto-riggers often produce fused finger blobs that cannot be skinned into readable gestures. The
new hand is an implicit surface: a palm (flattened metacarpal capsules, smooth-blended), a thumb
mound, and separate tapered fingers (round cones through the bone joints) that join the palm
smoothly but never each other. It is meshed with marching cubes, and every vertex is labelled with
the part it belongs to and its position along it, which hands.py turns into joint-blended weights.

The rig must be in a T-pose with the arms along +-X and the palms facing down (-Z).

  python hand_sdf.py project.toml hand_bones.json out.npz      (run by hands.py)
"""
import json
import os
import sys

import numpy as np
from skimage import measure

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config  # noqa: E402

FINGERS = ['Index', 'Middle', 'Ring', 'Pinky']
# finger / thumb radii at the joints (knuckle -> tip), for a hand REF_HAND long (wrist -> middle knuckle)
R_FINGER = {'Index': (0.0043, 0.0040, 0.0036, 0.0031), 'Middle': (0.0045, 0.0042, 0.0037, 0.0032),
            'Ring': (0.0042, 0.0039, 0.0035, 0.0030), 'Pinky': (0.0036, 0.0033, 0.0030, 0.0026)}
R_THUMB = (0.0070, 0.0058, 0.0048, 0.0038)
REF_HAND = 0.0598
TIP_EXT = 0.45           # fingertip = head of the "4" bone + this fraction of its length


def round_cone(p, a, b, ra, rb):
    """Signed distance to a capsule with linearly varying radius (good for small radius change)."""
    ab = b - a
    L2 = ab @ ab
    t = np.clip(((p - a) @ ab) / L2, 0.0, 1.0)
    q = a + t[..., None] * ab
    return np.linalg.norm(p - q, axis=-1) - (ra + (rb - ra) * t), t


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def build(side, B, hc):
    def head(n):
        return np.array(B[side + n]['head'])

    def tail(n):
        return np.array(B[side + n]['tail'])
    wrist = head('Hand')
    sgn = 1.0 if side == 'Left' else -1.0
    knuck = {f: head('Hand' + f + '1') for f in FINGERS}
    s = hc['scale'] or np.linalg.norm(head('HandMiddle1') - wrist) / REF_HAND      # size of the hand model
    vox = hc['voxel'] * s
    pts = {}
    for f in FINGERS:
        h4, t4 = head('Hand' + f + '4'), tail('Hand' + f + '4')
        pts[f] = [head('Hand' + f + '1'), head('Hand' + f + '2'), head('Hand' + f + '3'), h4 + TIP_EXT * (t4 - h4)]
    th4 = head('HandThumb4')
    t3 = head('HandThumb3')
    pts['Thumb'] = [head('HandThumb1'), head('HandThumb2'), t3, t3 + 0.85 * (th4 - t3)]
    # bounds
    allp = np.array([wrist] + [p for v in pts.values() for p in v])
    lo = allp.min(0) - 0.016 * s
    hi = allp.max(0) + 0.016 * s
    if sgn > 0:
        lo[0] = wrist[0] - 0.028 * s
    else:
        hi[0] = wrist[0] + 0.028 * s
    nx, ny, nz = (np.ceil((hi - lo) / vox)).astype(int)
    xs = lo[0] + np.arange(nx) * vox
    ys = lo[1] + np.arange(ny) * vox
    zs = lo[2] + np.arange(nz) * vox
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    # palm mid-plane (rest pose: palm faces -z)
    pz = hc['palm_plane_z'] or float(np.mean([wrist[2]] + [k[2] for k in knuck.values()]))
    # palm in a space flattened along z so the capsules become a slab
    flat = 1.75
    Pp = np.stack([X, Y, pz + (Z - pz) * flat], -1)
    palm_d = None
    wrist_c = wrist + np.array([0.004 * sgn, 0.0, 0.0012]) * s
    for f in FINGERS:
        kn = knuck[f].copy()
        kn[2] = pz
        base = wrist_c + (kn - wrist_c) * 0.12
        r = (0.0068 if f != 'Pinky' else 0.0058) * s
        d, _ = round_cone(Pp, base, kn - (kn - wrist_c) * 0.04, r * 0.9, r)
        palm_d = d if palm_d is None else smin(palm_d, d, 0.006 * s)
    # thumb mound (heel of the thumb)
    t1 = pts['Thumb'][0]
    mound_a = wrist_c + np.array([0.008 * sgn, -0.006, -0.0005]) * s
    md, _ = round_cone(np.stack([X, Y, Z], -1), mound_a, t1 + (pts['Thumb'][1] - t1) * 0.15, 0.0068 * s, 0.0058 * s)
    palm_d = smin(palm_d, md, 0.005 * s)
    # wrist, sliding under the cuff
    wd, _ = round_cone(np.stack([X, Y, Z], -1), wrist - np.array([0.024 * sgn, 0, 0]) * s,
                       wrist + np.array([0.006 * sgn, 0, 0.0008]) * s, 0.0080 * s, 0.0088 * s)
    palm_d = smin(palm_d, wd, 0.006 * s)
    Pw = np.stack([X, Y, Z], -1)
    # fingers
    fd = {}
    ftpar = {}
    for f in FINGERS + ['Thumb']:
        rr = [r * s for r in (R_THUMB if f == 'Thumb' else R_FINGER[f])]
        best, bpar = None, None
        for k in range(3):
            d, t = round_cone(Pw, pts[f][k], pts[f][k + 1], rr[k], rr[k + 1])
            if best is None:
                best, bpar = d, t + k
            else:
                m = d < best
                best = np.where(m, d, best)
                bpar = np.where(m, t + k, bpar)
        fd[f], ftpar[f] = best, bpar
    # fingers join the palm smoothly, but never each other
    total = palm_d
    for f in FINGERS + ['Thumb']:
        # the thumb's first bone is the metacarpal: it melts into the palm
        total = np.minimum(total, smin(palm_d, fd[f], (0.0075 if f == 'Thumb' else 0.0035) * s))
    verts, faces, normals, _ = measure.marching_cubes(total, 0.0, spacing=(vox, vox, vox))
    verts += lo
    # labels: nearest part (0 palm/wrist, 1.. fingers), with position along the finger
    ijk = np.clip(np.round((verts - lo) / vox).astype(int), 0, [nx - 1, ny - 1, nz - 1])
    names = ['Palm'] + FINGERS + ['Thumb']
    comps = np.stack([palm_d[tuple(ijk.T)]] + [fd[f][tuple(ijk.T)] for f in FINGERS + ['Thumb']], 1)
    label = comps.argmin(1)
    par = np.zeros(len(verts))
    for i, f in enumerate(FINGERS + ['Thumb']):
        m = label == i + 1
        par[m] = ftpar[f][tuple(ijk[m].T)]
    # palm vertices: distance along the wrist->knuckle axis, for the forearm/hand blend
    axis = np.mean([knuck[f] for f in FINGERS], 0) - wrist
    palm_t = ((verts - wrist) @ axis) / (axis @ axis)
    print(side, 'scale', round(float(s), 4), 'verts', len(verts), 'faces', len(faces), 'labels', np.bincount(label, minlength=6))
    return dict(verts=verts, faces=faces, label=label, par=par, palm_t=palm_t, names=names)


def main(cfg_path, bones_path, out_path):
    cfg = config.load(cfg_path)
    with open(bones_path) as f:
        B = json.load(f)
    out = {}
    for side in ('Left', 'Right'):
        r = build(side, B, cfg.hands)
        for k, v in r.items():
            if k != 'names':
                out[f'{side}_{k}'] = v
    out['names'] = np.array(['Palm'] + FINGERS + ['Thumb'])
    np.savez(out_path, **out)
    print('wrote', out_path)


if __name__ == '__main__':
    main(*sys.argv[1:4])
