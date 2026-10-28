"""Physics checks on a project's cached simulation (system Python + numpy).

  python -m mmdance qa project.toml [hem_from hem_to]

* motion statistics: per-frame particle movement measured in the root bone's frame (the body's
  own translation is not counted), and the frames whose jerk exceeds 0.12 m/frame^2. Fast spins
  and kicks register as well as real pops, so this is a list of frames to step through in stills
  (compare with a calm stretch of the same dance), not a pass/fail test;
* hem lag (with a frame range, e.g. a spin): the hips' yaw rate against the hem's twist relative to
  the hips. A rigid skirt shows ~0 twist; fabric trails the turn (negative correlation with the rate).
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config  # noqa: E402
from mmdance.solver import TRACK  # noqa: E402


def newest(pattern):
    files = glob.glob(pattern)
    if not files:
        sys.exit(f'nothing matches {pattern}: build the project first')
    return max(files, key=os.path.getmtime)


def main(cfg_path, a=None, b=None):
    cfg = config.load(cfg_path)
    sim_path = newest(cfg.cache('sim_*.npz'))
    track_path = newest(cfg.cache('body_track_*.npz'))
    S = np.load(sim_path)
    tr = np.load(track_path)
    T = tr['mats']
    print('simulation', os.path.basename(sim_path), 'body track', os.path.basename(track_path))
    for key, root in (('sk', 'Hips'), ('ov', 'Hips'), ('hr', 'Head'), ('tl', 'Hips')):
        if key not in S:
            continue
        X = S[key]
        ri = TRACK.index(root)
        R, o = T[:len(X), ri, :3, :3], T[:len(X), ri, :3, 3]
        L = np.einsum('fij,fni->fnj', R, X - o[:, None, :])          # particles in the root bone's frame
        d = np.linalg.norm(np.diff(L, axis=0), axis=2).max(1)
        acc = np.linalg.norm(L[2:] - 2 * L[1:-1] + L[:-2], axis=2).max(1)
        print(f'{key}: move/frame median {np.median(d):.3f}  p99 {np.percentile(d, 99):.3f}  max {d.max():.3f} at {d.argmax() + 1}')
        bad = np.nonzero(acc > 0.12)[0] + 1
        print(f'    frames with jerk > 0.12 m/frame^2: {len(bad)}  {bad[:30].tolist()}')
    if a is None or 'sk' not in S:
        return
    lat = np.load(cfg.cache('lattice.npz'))
    ncol, nrow = len(lat['sk_len']), int(lat['sk_len'][0])
    hi = TRACK.index('Hips')
    rest = tr['rest'][hi]
    rest_hem = lat['sk_pts'][:, -1]
    rows, prev = [], None
    for f in range(int(a), int(b)):
        D = T[f][hi] @ np.linalg.inv(rest)            # rest-world -> world for the hips
        hem = S['sk'][f].reshape(ncol, nrow, 3)[:, -1]
        loc = (hem - D[:3, 3]) @ D[:3, :3]
        c = loc[:, :2] - loc[:, :2].mean(0)
        r0 = rest_hem[:, :2] - rest_hem[:, :2].mean(0)
        ang = np.degrees(np.arctan2((r0[:, 0] * c[:, 1] - r0[:, 1] * c[:, 0]).sum(), (r0 * c).sum()))
        yaw = np.degrees(np.arctan2(D[1, 0], D[0, 0]))
        rate = 0 if prev is None else ((yaw - prev + 180) % 360) - 180
        prev = yaw
        rows.append((f, rate, ang))
    for f, rate, ang in rows[::max(1, len(rows) // 30)]:
        print(f'{f:5d}  hips yaw rate {rate:7.2f} deg/frame   hem twist vs hips {ang:7.2f} deg')
    arr = np.array([(r, g) for _, r, g in rows])
    print('corr(yaw rate, -twist) =', round(float(np.corrcoef(arr[1:, 0], -arr[1:, 1])[0, 1]), 3),
          ' max |twist| =', round(float(np.abs(arr[:, 1]).max()), 1), 'deg')


if __name__ == '__main__':
    main(*sys.argv[1:4])
