"""Stage: retarget the MMD dance (VMD) onto the character's rig.

The VMD is imported by mmd_tools onto a proxy MMD skeleton built from this rig's own
proportions (arms in MMD's A-pose). The proxy's world-space bone rotations are then
copied onto the rig's bones relative to that A-pose, twist bones are shared half-and-half
between the upper arm / forearm, and the legs are solved with an analytic two-bone IK that
reaches the proxy's foot-IK targets (MMD 足ＩＫ / つま先ＩＫ).
"""
import math
import os
import time

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import config, vmd
from .util import hide_others, mmd_importer, new_action, nframes, put_curve, rig_and_body

FWD = Vector((0, -1, 0))    # the model faces -Y
MMD_LEG_UNITS = 9.42        # hip -> ankle of a standard MMD model, MMD units


def resolve(cfg):
    """Fill the automatic values (scale, frame range) in place, before any stage runs."""
    if cfg.project.frame_end < 0:
        v = vmd.read_vmd(cfg.path('motion.vmd'))
        cfg.project.frame_end = max(b[1] for b in v['bones'])
    if not cfg.motion.scale:
        rig, _ = rig_and_body(cfg)
        B = rig.data.bones

        def h(n):
            return B[cfg.bone(n)].head_local
        leg = ((h('LeftLeg') - h('LeftUpLeg')).length + (h('LeftFoot') - h('LeftLeg')).length)
        cfg.motion.scale = round(leg / MMD_LEG_UNITS, 4)
        print(f'[motion] scale (auto): {cfg.motion.scale} m per MMD unit')


def ref_pose(cfg, rig):
    """Armature-space matrices of every bone in MMD's A-pose (arms arm_angle down)."""
    bones = rig.data.bones
    M = {b.name: b.matrix_local.copy() for b in bones}
    ref = dict(M)

    def subtree(n):
        out = [n]
        for c in bones[n].children:
            out += subtree(c.name)
        return out
    for side, sgn in (('Left', 1), ('Right', -1)):
        arm = cfg.bone(side + 'Arm')
        h = M[arm].translation.copy()
        R = Matrix.Translation(h) @ Matrix.Rotation(math.radians(cfg.motion.arm_angle) * sgn, 4, 'Y') @ Matrix.Translation(-h)
        for n in subtree(arm):
            ref[n] = R @ M[n]
    return M, ref


def proxy_spec(cfg, ref):
    def head(n):
        return ref[cfg.bone(n)].translation.copy()

    def mid(a, b):
        return (head(a) + head(b)) / 2
    hips = head('Hips')
    center_z = cfg.motion.center_height * cfg.motion.scale
    spec = [
        ('全ての親', None, Vector((0, 0, 0))),
        ('センター', '全ての親', Vector((0, hips.y, center_z))),
        ('グルーブ', 'センター', Vector((0, hips.y, center_z))),
        ('腰', 'グルーブ', hips),
        ('上半身', '腰', head('Spine')),
        ('上半身2', '上半身', head('Spine2')),
        ('首', '上半身2', head('Neck')),
        ('頭', '首', head('Head')),
        ('下半身', '腰', hips),
    ]
    for jp, en in (('左', 'Left'), ('右', 'Right')):
        spec += [
            (jp + '肩P', '上半身2', head(en + 'Shoulder')),
            (jp + '肩', jp + '肩P', head(en + 'Shoulder')),
            (jp + '腕', jp + '肩', head(en + 'Arm')),
            (jp + '腕捩', jp + '腕', mid(en + 'Arm', en + 'ForeArm')),
            (jp + 'ひじ', jp + '腕捩', head(en + 'ForeArm')),
            (jp + '手捩', jp + 'ひじ', mid(en + 'ForeArm', en + 'Hand')),
            (jp + '手首', jp + '手捩', head(en + 'Hand')),
            (jp + '親指０', jp + '手首', head(en + 'HandThumb1')),
            (jp + '親指１', jp + '親指０', head(en + 'HandThumb2')),
            (jp + '親指２', jp + '親指１', head(en + 'HandThumb3')),
        ]
        for fj, fe in (('人指', 'Index'), ('中指', 'Middle'), ('薬指', 'Ring'), ('小指', 'Pinky')):
            spec += [
                (jp + fj + '１', jp + '手首', head(en + 'Hand' + fe + '1')),
                (jp + fj + '２', jp + fj + '１', head(en + 'Hand' + fe + '2')),
                (jp + fj + '３', jp + fj + '２', head(en + 'Hand' + fe + '3')),
            ]
        ank = head(en + 'Foot')
        spec += [
            (jp + '足', '下半身', head(en + 'UpLeg')),
            (jp + 'ひざ', jp + '足', head(en + 'Leg')),
            (jp + '足首', jp + 'ひざ', ank),
            (jp + '足IK親', '全ての親', Vector((ank.x, ank.y, 0))),
            (jp + '足ＩＫ', jp + '足IK親', ank),
            (jp + 'つま先ＩＫ', jp + '足ＩＫ', head(en + 'ToeBase')),
        ]
    return spec


def evaluate_proxy(cfg, spec, cache_path):
    """Import the VMD onto a proxy skeleton and sample world rotation deltas + positions."""
    if os.path.exists(cache_path):
        d = np.load(cache_path, allow_pickle=True)
        return list(d['names']), d['W'], d['POS']
    VMDImporter = mmd_importer()
    sc = bpy.context.scene
    arm_data = bpy.data.armatures.new('MMD_Proxy')
    px = bpy.data.objects.new('MMD_Proxy', arm_data)
    sc.collection.objects.link(px)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = px
    px.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, parent, h in spec:
        eb = arm_data.edit_bones.new(name)
        eb.head = h
        eb.tail = h + Vector((0, 0, 0.02))
        eb.roll = 0
    for name, parent, h in spec:
        if parent:
            arm_data.edit_bones[name].parent = arm_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in px.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    sc.frame_set(0)
    VMDImporter(cfg.path('motion.vmd'), scale=cfg.motion.scale, frame_margin=0).assign(px)

    hidden = hide_others(px)            # keep the heavy character out of the depsgraph while sampling
    names = [s[0] for s in spec]
    pbs = [px.pose.bones[n] for n in names]
    rest_inv = [np.array(px.data.bones[n].matrix_local.to_3x3().inverted()) for n in names]
    f0, f1 = cfg.project.frame_start, cfg.project.frame_end
    W = np.zeros((f1 - f0 + 1, len(names), 3, 3))
    POS = np.zeros((f1 - f0 + 1, len(names), 3))
    t0 = time.time()
    for i, f in enumerate(range(f0, f1 + 1)):
        sc.frame_set(f)
        for j, pb in enumerate(pbs):
            m = np.array(pb.matrix)
            W[i, j] = m[:3, :3] @ rest_inv[j]
            POS[i, j] = m[:3, 3]
    print(f'[motion] sampled proxy in {time.time() - t0:.1f}s')
    for o in hidden:
        o.hide_viewport = False
    act = px.animation_data.action if px.animation_data else None
    bpy.data.objects.remove(px)
    bpy.data.armatures.remove(arm_data)
    if act and act.users == 0:
        bpy.data.actions.remove(act)
    np.savez(cache_path, names=np.array(names, dtype=object), W=W, POS=POS)
    return names, W, POS


def basis(a, f):
    """Orthonormal frame from a primary axis `a` and a secondary hint `f`."""
    a = a.normalized()
    f = (f - a * f.dot(a)).normalized()
    return Matrix((a, f, a.cross(f))).transposed()


def half_twist(Wp, Wc):
    """Half of the relative rotation Wp^-1 Wc (used to share twist between two bones)."""
    q = (Wp.inverted() @ Wc).to_quaternion()
    return Quaternion().slerp(q, 0.5).to_matrix()


def retarget(cfg, rig, M, ref, names, W, POS):
    bones = rig.data.bones
    idx = {n: i for i, n in enumerate(names)}
    ref3 = {n: m.to_3x3() for n, m in ref.items()}
    B = cfg.bone

    def depth(b):
        return 0 if b.parent is None else 1 + depth(b.parent)
    order = sorted((b.name for b in bones), key=lambda n: depth(bones[n]))

    direct = {'Hips': '下半身', 'Spine': '上半身', 'Spine2': '上半身2', 'Neck': '首', 'Head': '頭'}
    for jp, en in (('左', 'Left'), ('右', 'Right')):
        direct[en + 'Shoulder'] = jp + '肩'
        direct[en + 'Hand'] = jp + '手首'
        direct[en + 'HandThumb1'] = jp + '親指０'
        direct[en + 'HandThumb2'] = jp + '親指１'
        direct[en + 'HandThumb3'] = jp + '親指２'
        for fj, fe in (('人指', 'Index'), ('中指', 'Middle'), ('薬指', 'Ring'), ('小指', 'Pinky')):
            for k, kj in (('1', '１'), ('2', '２'), ('3', '３')):
                direct[en + 'Hand' + fe + k] = jp + fj + kj
    legs = {B(s + n) for s in ('Left', 'Right') for n in ('UpLeg', 'Leg', 'Foot')}

    leg = {}
    for jp, en in (('左', 'Left'), ('右', 'Right')):
        H0 = ref[B(en + 'UpLeg')].translation
        K0 = ref[B(en + 'Leg')].translation
        A0 = ref[B(en + 'Foot')].translation
        T0 = ref[B(en + 'ToeBase')].translation
        leg[en] = dict(jp=jp, L1=(K0 - H0).length, L2=(A0 - K0).length,
                       thigh0=basis(K0 - H0, FWD), shin0=basis(A0 - K0, FWD), toe0=(T0 - A0).normalized())

    nf = W.shape[0]
    out_q = {n: np.zeros((nf, 4)) for n in order}
    out_l = {n: np.zeros((nf, 3)) for n in order}
    stats = dict(overreach=0)
    for i in range(nf):
        Wf = {n: Matrix(W[i, j].tolist()) for n, j in idx.items()}
        Pf = {n: Vector(POS[i, j]) for n, j in idx.items()}
        Wd, D = {}, {}
        for n in order:
            short = cfg.role(n) or ''
            b = bones[n]
            par = b.parent.name if b.parent else None
            # world-space rotation delta for this bone
            if short in direct:
                wd = Wf[direct[short]]
            elif short in ('LeftArm', 'RightArm'):
                jp = '左' if short.startswith('Left') else '右'
                wd = Wf[jp + '腕'] @ half_twist(Wf[jp + '腕'], Wf[jp + '腕捩'])
            elif short in ('LeftForeArm', 'RightForeArm'):
                jp = '左' if short.startswith('Left') else '右'
                wd = Wf[jp + 'ひじ'] @ half_twist(Wf[jp + 'ひじ'], Wf[jp + '手捩'])
            elif n in legs:
                wd = None  # solved by IK below
            elif par is None:
                wd = Matrix.Identity(3)
            else:
                wd = Wd[par]
            # head position: explicit for the two roots, rigid from the parent otherwise
            if short == 'Hips':
                head = Pf['下半身']
            elif short == 'Spine':
                head = Pf['上半身']
            elif par is None:
                head = M[n].translation.copy()
            else:
                head = D[par] @ (ref[par].inverted() @ ref[n]).translation
            if wd is None:
                side = 'Left' if short.startswith('Left') else 'Right'
                g = leg[side]
                jp = g['jp']
                if short.endswith('UpLeg'):
                    H = head
                    A = Pf[jp + '足ＩＫ']
                    d = A - H
                    dist = d.length
                    dmax = (g['L1'] + g['L2']) * 0.9995
                    if dist > dmax:
                        stats['overreach'] += 1
                        dist = dmax
                    dn = d.normalized()
                    hint = Wf[jp + '足'] @ FWD
                    pn = hint - dn * hint.dot(dn)
                    if pn.length < 1e-4:
                        alt = Wf['下半身'] @ FWD
                        pn = alt - dn * alt.dot(dn)
                    pn.normalize()
                    a = (g['L1'] ** 2 - g['L2'] ** 2 + dist ** 2) / (2 * dist)
                    h = math.sqrt(max(g['L1'] ** 2 - a * a, 0.0))
                    K = H + dn * a + pn * h
                    Aeff = H + dn * dist
                    g['K'], g['A'], g['pn'] = K, Aeff, pn
                    wd = basis(K - H, pn) @ g['thigh0'].inverted()
                elif short.endswith('Leg'):
                    wd = basis(g['A'] - g['K'], g['pn']) @ g['shin0'].inverted()
                    g['Rshin'] = wd
                else:  # Foot: aim the shin-carried foot at the IK bone's toe direction (MMD つま先IK)
                    t_shin = g['Rshin'] @ g['toe0']
                    t_ik = Wf[jp + '足ＩＫ'] @ g['toe0']
                    wd = t_shin.rotation_difference(t_ik).to_matrix() @ g['Rshin']
            Wd[n] = wd
            D[n] = Matrix.Translation(head) @ (wd @ ref3[n]).to_4x4()
            # local pose (basis) relative to the T-pose rest
            if par is None:
                basis_m = M[n].inverted() @ D[n]
            else:
                basis_m = M[n].inverted() @ M[par] @ D[par].inverted() @ D[n]
            q = basis_m.to_quaternion()
            if i and np.dot(out_q[n][i - 1], q) < 0:
                q = -q
            out_q[n][i] = q
            out_l[n][i] = basis_m.translation
    print('[motion] IK over-reach frames (per leg-frame):', stats['overreach'])
    return out_q, out_l


def write_action(cfg, rig, out_q, out_l):
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    act, cbag = new_action(rig, cfg.project.name + '_Dance')
    for n in out_q:
        pb = rig.pose.bones[n]
        pb.rotation_mode = 'QUATERNION'
        for k in range(4):
            put_curve(cbag, f'pose.bones["{n}"].rotation_quaternion', k, frames, out_q[n][:, k], group=n)
        if np.abs(out_l[n]).max() > 1e-4:
            for k in range(3):
                put_curve(cbag, f'pose.bones["{n}"].location', k, frames, out_l[n][:, k], group=n)
    return act


def run(cfg):
    sc = bpy.context.scene
    sc.render.fps = cfg.project.fps
    sc.render.fps_base = 1
    sc.frame_start, sc.frame_end = cfg.project.frame_start, cfg.project.frame_end
    rig, _ = rig_and_body(cfg)
    # Spine is driven independently of Hips (MMD 上半身/下半身 are siblings)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    rig.data.edit_bones[cfg.bone('Spine')].use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    M, ref = ref_pose(cfg, rig)
    spec = proxy_spec(cfg, ref)
    key = cfg.key(config.file_key(cfg.path('motion.vmd')), cfg.motion.scale, cfg.motion.arm_angle,
                  cfg.motion.center_height, cfg.project.frame_start, cfg.project.frame_end,
                  [(n, p, list(h)) for n, p, h in spec])
    names, W, POS = evaluate_proxy(cfg, spec, cfg.cache(f'proxy_{key}.npz'))
    t0 = time.time()
    out_q, out_l = retarget(cfg, rig, M, ref, names, W, POS)
    print(f'[motion] retarget {time.time() - t0:.1f}s ({nframes(cfg)} frames)')
    write_action(cfg, rig, out_q, out_l)
