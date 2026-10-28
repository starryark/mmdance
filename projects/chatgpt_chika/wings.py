"""A living pair of wings for the ChatGPT character (called from room.finish() when [stage.wings]
is set). The model prep gave each wing two bones on the upper back (Wing_L/R_0 from the spine to
the end of the crossbar, Wing_L/R_1 the outer wing). They get keys:
  * a slow beat: the wings open and close a little and lift, the outer wing following late;
  * drag in turns: when her chest turns, the wings sweep back against the turn and settle.
Angles in degrees; [stage.wings] beat = [open, lift, period (frames), outer lag (frames)],
drag = degrees of sweep per (degree / frame) of chest turn, capped at drag_max.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mmdance import config, physics  # noqa: E402
from mmdance import solver as ps  # noqa: E402
from mmdance.util import channelbag, put_curve, rig_and_body  # noqa: E402


def rot(axis, deg):
    a = np.radians(deg) / 2
    axis = np.asarray(axis, float)
    return np.concatenate([[np.cos(a)], np.sin(a) * axis / np.linalg.norm(axis)])


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def run(cfg):
    sec = cfg.stage.wings
    rig, _ = rig_and_body(cfg)
    TRACK = ps.TRACK
    ti = {n: i for i, n in enumerate(TRACK)}
    rest = np.array([np.array(rig.data.bones[cfg.bone(n)].matrix_local) for n in TRACK])
    motion_key = cfg.key(config.file_key(cfg.path('motion.vmd')), cfg.motion.scale, cfg.motion.arm_angle,
                         cfg.project.frame_start, cfg.project.frame_end, rest.tolist(),
                         *([cfg.motion.thumb_rest, cfg.motion.hands_apart]
                           if cfg.motion.thumb_rest or cfg.motion.hands_apart else []))
    mats = physics.sample_track(cfg, rig, cfg.cache(f'body_track_{motion_key}.npz'), rest)
    nf = mats.shape[0]
    f = np.arange(nf) + cfg.project.frame_start
    # chest turn rate (deg/frame) relative to its rest facing, smoothed: the wings trail it
    R = mats[:, ti['Spine2'], :3, :3] @ rest[ti['Spine2']][:3, :3].T
    fwd = R @ np.array([0.0, -1.0, 0.0])
    yaw = np.degrees(np.unwrap(np.arctan2(fwd[:, 0], -fwd[:, 1])))
    rate = physics.gauss_time(np.gradient(yaw)[:, None], 4.0)[:, 0]
    sweep = np.clip(-sec.drag * rate, -sec.drag_max, sec.drag_max)
    sweep = physics.gauss_time(sweep[:, None], 3.0)[:, 0]
    op, lift, period, lag = sec.beat
    bones = rig.data.bones
    cbag = channelbag(rig)
    for fc in list(cbag.fcurves):
        if 'Wing_' in fc.data_path:
            cbag.fcurves.remove(fc)
    frames = f.astype(np.float32)
    for s, sg in (('L', 1), ('R', -1)):
        for k, (amp, delay) in enumerate(((1.0, 0.0), (0.6, lag))):
            name = f'Wing_{s}_{k}'
            Mr = np.array(bones[name].matrix_local)[:3, :3]
            ph = 2 * np.pi * (f - delay) / period
            o = amp * op * np.sin(ph)                   # open (+) / fold back (-), about the vertical
            li = amp * lift * np.sin(ph + 0.6)          # lift, about the wing's forward axis
            sw = np.interp(f - delay, f, sweep) * (1.0 if k == 0 else 0.5)
            q = np.zeros((nf, 4))
            for i in range(nf):
                # in rest armature space: about z through the root (+ opens for the left wing), then a
                # lift about the horizontal axis across the wing
                Rw = qmul(rot([0, 0, 1], -sg * (o[i]) + sw[i]), rot([0, 1, 0], -sg * li[i]))
                m = ps.mat_from_quat(Rw)
                q[i] = ps.quat_from_mat(Mr.T @ m @ Mr)   # the same rotation in the bone's own frame
                if i and np.dot(q[i - 1], q[i]) < 0:
                    q[i] = -q[i]
            dp = f'pose.bones["{name}"]'
            for j in range(4):
                put_curve(cbag, dp + '.rotation_quaternion', j, frames, q[:, j], group=name)
    print(f'[wings] keyed: beat {op}/{lift} deg over {period} frames, sweep up to {np.abs(sweep).max():.1f} deg')
