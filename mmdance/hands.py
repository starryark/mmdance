"""Replace fused auto-rig hands with ones generated from the finger bones (see hand_sdf.py).

Called from rig.py when `hands.enabled`. The rig's hand bones are exported to the cache, the
implicit-surface hands are meshed by hand_sdf.py in system Python (scikit-image), and the result
is weighted from its part labels (palm / finger / thumb and position along it) with short blends
at the joints, decimated, and merged into the body in the hands' material slot. That material
switches from its texture to a flat skin colour.
"""
import json
import os
import subprocess

import bmesh
import bpy
import numpy as np
from mathutils import Vector


FINGERS = ['Index', 'Middle', 'Ring', 'Pinky']
HERE = os.path.dirname(os.path.abspath(__file__))
MERGE_KEYS = ('select', 'wrist_margin', 'skin_uv')     # only affect the merge, not the generated mesh
BONE_KEYS = ('phalanges', 'spread')     # act on the rig's finger bones, which are in the key already


def ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def export_bones(cfg, rig, path):
    d = {}
    for side in ('Left', 'Right'):
        for n in ['Hand', 'ForeArm'] + [f'Hand{f}{k}' for f in FINGERS + ['Thumb'] for k in (1, 2, 3, 4)]:
            b = rig.data.bones.get(cfg.bone(side + n))
            if b is None:
                raise RuntimeError(f'hands: the rig has no bone for {side + n} ({cfg.bone(side + n)})')
            d[side + n] = dict(head=list(b.head_local), tail=list(b.tail_local))
    with open(path, 'w') as f:
        json.dump(d, f, indent=1)


TIP_EXT = 0.45           # as hand_sdf.py: fingertip = head of the "4" bone + this fraction of its length


def finger_bones(cfg, rig):
    """Re-place the finger joints in the rest pose (before the motion is retargeted).

    Auto-riggers space a finger's three joints evenly and crowd the knuckles. Real and drawn hands
    have a long first segment (`hands.phalanges`, e.g. 1 : 0.62 : 0.55), and the knuckle row is
    wider (`hands.spread`). Fingertips stay where they were; each finger keeps its direction."""
    ratios, spread = cfg.hands.phalanges, cfg.hands.spread
    if not ratios and spread == 1.0:
        return
    B = cfg.bone
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for side in ('Left', 'Right'):
        wrist = np.array(eb[B(side + 'Hand')].head)
        kn = {f: np.array(eb[B(side + 'Hand' + f + '1')].head) for f in FINGERS}
        along = kn['Middle'] - wrist
        along /= np.linalg.norm(along)
        across = kn['Index'] - kn['Pinky']
        across -= along * (across @ along)
        across /= np.linalg.norm(across)
        centre = np.mean([kn[f] @ across for f in FINGERS])
        for f in FINGERS:
            bones = [eb[B(side + 'Hand' + f + str(k))] for k in (1, 2, 3, 4)]
            J = [np.array(b.head) for b in bones]
            T4 = np.array(bones[3].tail)
            len4 = np.linalg.norm(T4 - J[3])
            d4 = (T4 - J[3]) / len4
            tip = J[3] + TIP_EXT * (T4 - J[3])
            shift = (spread - 1.0) * ((kn[f] @ across) - centre) * across
            if ratios:
                pts = [J[0], J[1], J[2], tip]
                seg = [np.linalg.norm(pts[k + 1] - pts[k]) for k in range(3)]
                L = sum(seg)

                def at(s):                      # point at arc length s along the old finger
                    for k in range(3):
                        if s <= seg[k] or k == 2:
                            return pts[k] + (pts[k + 1] - pts[k]) * (s / seg[k])
                        s -= seg[k]
                S = sum(ratios)
                J = [J[0], at(L * ratios[0] / S), at(L * (ratios[0] + ratios[1]) / S), tip - TIP_EXT * len4 * d4]
            ends = J[1:] + [J[3] + d4 * len4]
            connected = [b.use_connect for b in bones]
            for b in bones:                     # a connected head would drag its parent's tail
                b.use_connect = False
            for b, h, t in zip(bones, J, ends):
                b.head = Vector(h + shift)
                b.tail = Vector(t + shift)
            for b, c in zip(bones, connected):
                b.use_connect = c
    bpy.ops.object.mode_set(mode='OBJECT')
    print(f'[hands] finger joints re-placed (phalanges {list(ratios)}, spread {spread})')


def generate(cfg, rig):
    """hands.npz for this rig + hands config (cached by content)."""
    bones_json = cfg.cache('hand_bones.json')
    export_bones(cfg, rig, bones_json)
    with open(bones_json) as f:
        key = cfg.key(json.load(f), {k: v for k, v in cfg.hands.items() if k not in MERGE_KEYS + BONE_KEYS})
    out = cfg.cache(f'hands_{key}.npz')
    if not os.path.exists(out):
        cmd = [cfg.tools.python, os.path.join(HERE, 'hand_sdf.py'), cfg['_file'], bones_json, out]
        print('[hands] generating:', ' '.join(cmd))
        subprocess.run(cmd, check=True)
    return out


def weights_for(cfg, side, label, par, palm_t, verts, knuckles):
    """Return dict bone -> weight array."""
    n = len(label)
    W = {}

    def add(b, w):
        name = cfg.bone(side + b)
        W.setdefault(name, np.zeros(n))
        W[name] += w
    # palm / wrist
    m = label == 0
    fh = ss(-0.16, 0.04, palm_t)                       # forearm -> hand across the wrist
    near_k = np.argmin(np.stack([np.linalg.norm(verts - k, axis=1) for k in knuckles]), 0)
    kb = ss(0.82, 1.02, palm_t) * 0.5                  # palm edge at the knuckles bends a little with the finger
    add('ForeArm', np.where(m, 1 - fh, 0))
    add('Hand', np.where(m, fh * (1 - kb), 0))
    for i, f in enumerate(FINGERS):
        add('Hand' + f + '1', np.where(m & (near_k == i), fh * kb, 0))
    # fingers and thumb: bone s covers par in [s, s+1]; blend +-0.18 around joints, base blends to Hand
    for li, f in enumerate(FINGERS + ['Thumb'], start=1):
        m = label == li
        t = par
        base = ss(0.0, 0.35, t)
        w1 = (1 - ss(0.82, 1.18, t)) * base
        w2 = ss(0.82, 1.18, t) * (1 - ss(1.82, 2.18, t))
        w3 = ss(1.82, 2.18, t)
        add('Hand', np.where(m, 1 - base, 0))
        add('Hand' + f + '1', np.where(m, w1, 0))
        add('Hand' + f + '2', np.where(m, w2, 0))
        add('Hand' + f + '3', np.where(m, w3, 0))
    tot = sum(W.values())
    for k in W:
        W[k] = W[k] / np.maximum(tot, 1e-9)
    return W


def build_hand_object(cfg, side, d, bones):
    verts = d[f'{side}_verts']
    faces = d[f'{side}_faces']
    me = bpy.data.meshes.new(f'NewHand_{side}')
    me.from_pydata(verts.tolist(), [], faces.tolist())
    me.update()
    ob = bpy.data.objects.new(f'NewHand_{side}', me)
    bpy.context.scene.collection.objects.link(ob)
    knuckles = [np.array(bones[cfg.bone(side + 'Hand' + f + '1')].head_local) for f in FINGERS]
    W = weights_for(cfg, side, d[f'{side}_label'], d[f'{side}_par'], d[f'{side}_palm_t'], verts, knuckles)
    for name, w in W.items():
        g = ob.vertex_groups.new(name=name)
        for val in np.unique(np.round(w[w > 0.002], 3)):
            idx = np.nonzero(np.abs(np.round(w, 3) - val) < 1e-6)[0]
            g.add(idx.tolist(), float(val), 'REPLACE')
    if cfg.character.outline_group:
        og = ob.vertex_groups.new(name=cfg.character.outline_group)
        og.add(list(range(len(verts))), cfg.hands.outline_weight, 'REPLACE')
    for p in me.polygons:
        p.use_smooth = True
    # decimate to a sensible density (weights are interpolated)
    dec = ob.modifiers.new('Dec', 'DECIMATE')
    dec.ratio = cfg.hands.decimate
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.view_layer.objects:
        o.select_set(o is ob)
    bpy.ops.object.modifier_apply(modifier='Dec')
    sm = ob.modifiers.new('Smooth', 'SMOOTH')
    sm.factor = 0.5
    sm.iterations = 4
    bpy.ops.object.modifier_apply(modifier='Smooth')
    return ob


def _flat_color(mat, rgb):
    """Feed a flat colour into whatever the material's image texture fed (and mute the texture)."""
    nt = mat.node_tree
    tex = next((n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage' and n.outputs['Color'].is_linked), None)
    targets = [l.to_socket for l in nt.links if tex is not None and l.from_node is tex and l.from_socket.name == 'Color']
    if not targets:
        sh = next((n for n in nt.nodes if 'Base Color' in n.inputs), None)
        targets = [sh.inputs['Base Color']] if sh else []
    node = nt.nodes.get('HandSkin') or nt.nodes.new('ShaderNodeRGB')
    node.name = node.label = 'HandSkin'
    node.outputs[0].default_value = tuple(rgb) + (1,)
    for s in targets:
        nt.links.new(node.outputs[0], s)
    if tex:
        tex.mute = True


def skin_material(cfg):
    _flat_color(bpy.data.materials[cfg.hands.material], cfg.hands.skin_color)
    if cfg.hands.line_material:
        _flat_color(bpy.data.materials[cfg.hands.line_material], cfg.hands.skin_color)


def beyond_wrist(cfg, bones, co, margin):
    """Rest-pose points past either wrist, along the forearm (minus a margin toward the elbow)."""
    out = np.zeros(len(co), bool)
    for side in ('Left', 'Right'):
        fa = bones[cfg.bone(side + 'ForeArm')]
        w = np.array(bones[cfg.bone(side + 'Hand')].head_local)
        d = w - np.array(fa.head_local)
        d /= np.linalg.norm(d)
        out |= (co - w) @ d > -margin
    return out


def replace_hands(cfg, body, rig):
    d = dict(np.load(generate(cfg, rig), allow_pickle=True))
    bones = rig.data.bones
    mats = [m.name for m in body.data.materials]
    si = mats.index(cfg.hands.material)
    # 1) delete the old hands: every face of the hands' material, or (select = "wrist", for a
    # material shared with other skin) only those past the wrists
    bm = bmesh.new()
    bm.from_mesh(body.data)
    old = [f for f in bm.faces if f.material_index == si]
    if cfg.hands.select == 'wrist':
        past = [bool(beyond_wrist(cfg, bones, np.array([v.co for v in f.verts]), cfg.hands.wrist_margin).all()) for f in old]
        old = [f for f, p in zip(old, past) if p]
    bmesh.ops.delete(bm, geom=old, context='FACES')
    bm.to_mesh(body.data)
    bm.free()
    # 2) build, weight and merge the new ones
    objs = [build_hand_object(cfg, s, d, bones) for s in ('Left', 'Right')]
    for o in objs:
        for p in o.data.polygons:
            p.material_index = 0
        o.data.materials.clear()
        for m in body.data.materials:
            o.data.materials.append(m)
        for p in o.data.polygons:
            p.material_index = si
        uv = o.data.uv_layers.new(name=body.data.uv_layers[0].name)
        if cfg.hands.skin_uv:          # one skin-coloured texel of the shared texture
            uv.data.foreach_set('uv', np.tile(np.array(cfg.hands.skin_uv, np.float32), len(uv.data)))
    for o in bpy.context.view_layer.objects:
        o.select_set(o in objs or o is body)
    bpy.context.view_layer.objects.active = body
    nv = sum(len(o.data.vertices) for o in objs)
    bpy.ops.object.join()
    if not cfg.hands.skin_uv:
        skin_material(cfg)
    print(f'[hands] replaced the hands ({len(old)} faces): {nv} new vertices')
