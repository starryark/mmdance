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


FINGERS = ['Index', 'Middle', 'Ring', 'Pinky']
HERE = os.path.dirname(os.path.abspath(__file__))


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


def generate(cfg, rig):
    """hands.npz for this rig + hands config (cached by content)."""
    bones_json = cfg.cache('hand_bones.json')
    export_bones(cfg, rig, bones_json)
    with open(bones_json) as f:
        key = cfg.key(json.load(f), dict(cfg.hands))
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


def replace_hands(cfg, body, rig):
    d = dict(np.load(generate(cfg, rig), allow_pickle=True))
    bones = rig.data.bones
    mats = [m.name for m in body.data.materials]
    si = mats.index(cfg.hands.material)
    # 1) delete the old hands
    bm = bmesh.new()
    bm.from_mesh(body.data)
    old = [f for f in bm.faces if f.material_index == si]
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
        o.data.uv_layers.new(name=body.data.uv_layers[0].name)
    for o in bpy.context.view_layer.objects:
        o.select_set(o in objs or o is body)
    bpy.context.view_layer.objects.active = body
    nv = sum(len(o.data.vertices) for o in objs)
    bpy.ops.object.join()
    skin_material(cfg)
    print(f'[hands] replaced the hands: {nv} new vertices')
