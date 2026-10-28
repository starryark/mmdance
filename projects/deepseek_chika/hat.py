"""The red newsboy cap of the original video (run inside Blender, from room.py's finish()).

In the original she picks the cap up from the desk, wears it for a verse, then takes it off and
throws it at the camera, which goes red as it hits the lens. The motion (akomni's) has the hands
for all of it; the cap itself was a prop. Here the cap (a separate model, `[stage.hat] model`)
follows that motion, keyed every frame from the posed rig:
  desk -> both hands (pickup) -> the head (worn) -> the right hand (taken off) -> a throw that
  ends in front of the lens -> gone.
Each hand-over blends over a few frames. Frames come from [stage.hat] in project.toml, set from
the original video (its audio is 3.91 s ahead of the song) and the motion's hand positions.
"""
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def blend(A, B, t):
    """Blend two transforms (location lerp, rotation slerp, scale lerp)."""
    la, ra, sa = A.decompose()
    lb, rb, sb = B.decompose()
    return Matrix.LocRotScale(la.lerp(lb, t), ra.slerp(rb, t), sa.lerp(sb, t))


def import_cap(cfg, coll):
    """The cap model with its origin at the middle of its rim, facing -Y (the character's front)."""
    for o in [o for o in bpy.data.objects if o.name.startswith('Prop_Hat')]:
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=cfg.resolve(cfg.stage.hat.model))
    new = [o for o in bpy.data.objects if o not in before]
    mesh = next(o for o in new if o.type == 'MESH')
    for o in new:
        if o is not mesh:
            bpy.data.objects.remove(o, do_unlink=True)
    mesh.data.transform(mesh.matrix_world)              # the FBX axis rotation into the mesh
    mesh.matrix_world = Matrix.Identity(4)
    co = np.array([v.co for v in mesh.data.vertices])
    rim = co[co[:, 2] < co[:, 2].min() + 0.02]
    mesh.data.transform(Matrix.Translation(-Vector((rim[:, 0].mean(), co[:, 1].mean(), co[:, 2].min()))))
    for c in list(mesh.users_collection):
        c.objects.unlink(mesh)
    coll.objects.link(mesh)
    mesh.name = 'Prop_Hat'
    for p in mesh.data.polygons:
        p.use_smooth = True
    return mesh


def cap_material(mesh):
    """Her cel shading (the AIG_Toon group) over the cap's own colour texture."""
    old = mesh.data.materials[0]
    tex = next(n for n in old.node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage').image
    m = bpy.data.materials.get('Prop_Hat') or bpy.data.materials.new('Prop_Hat')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    im = nt.nodes.new('ShaderNodeTexImage')
    im.image = tex
    g = nt.nodes.new('ShaderNodeGroup')
    g.node_tree = bpy.data.node_groups['AIG_Toon']
    for k, v in (('Shadow Tint', (0.80, 0.68, 0.80, 1)), ('Deep Shadow Tint', (0.66, 0.54, 0.68, 1)), ('Threshold', 0.3),
                 ('Softness', 0.05), ('Rim Strength', 0.15), ('Use Light Dir', 0.0), ('Ambient', 0.16), ('Lit Boost', 1.0)):
        g.inputs[k].default_value = v
    nt.links.new(im.outputs['Color'], g.inputs['Base Color'])
    nt.links.new(g.outputs[0], out.inputs['Surface'])
    mesh.data.materials.clear()
    mesh.data.materials.append(m)
    ink = bpy.data.materials.get('Prop_HatInk') or bpy.data.materials.new('Prop_HatInk')
    ink.use_nodes = True
    ink.node_tree.nodes.clear()
    em = ink.node_tree.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (0.12, 0.02, 0.03, 1)
    o = ink.node_tree.nodes.new('ShaderNodeOutputMaterial')
    ink.node_tree.links.new(em.outputs[0], o.inputs['Surface'])
    ink.use_backface_culling = True
    mesh.data.materials.append(ink)
    sd = mesh.modifiers.new('Ink', 'SOLIDIFY')         # inverted-hull outline, as the set's props
    sd.thickness = 0.0025
    sd.offset = 1.0
    sd.use_flip_normals = True
    sd.use_rim = False
    sd.material_offset = 1


def run(cfg, coll):
    hc = cfg.stage.hat
    if not hc.get('model') or not os.path.exists(cfg.resolve(hc.model)):
        print('[stage] hat: no model, skipped')
        return
    sc = bpy.context.scene
    rig = bpy.data.objects[cfg.character.rig]
    B = cfg.bone
    cap = import_cap(cfg, coll)
    cap_material(cap)
    S = Matrix.Diagonal((hc.scale,) * 3).to_4x4()
    # worn: on the crown, tilted back, relative to the head bone's rest frame
    head_rest = rig.matrix_world @ rig.data.bones[B('Head')].matrix_local
    worn_rest = Matrix.Translation(Vector(hc.worn)) @ Euler((math.radians(hc.tilt), 0, 0)).to_matrix().to_4x4() @ S
    worn_rel = head_rest.inverted() @ worn_rest
    desk = Matrix.Translation(Vector(hc.desk)) @ Euler((0, 0, math.radians(hc.desk_yaw))).to_matrix().to_4x4() @ S
    pick, carry_end, grab, release, hit = hc.frames            # pickup, worn from, take-off grab, release, at the lens

    def bone(n):
        return rig.matrix_world @ rig.pose.bones[B(n)].matrix

    def hands_mid():
        a, b = bone('LeftHandMiddle1').translation, bone('RightHandMiddle1').translation
        return (a + b) / 2
    keys = {}
    sc.frame_set(grab)
    hand_rel = bone('RightHandMiddle1').inverted() @ (bone('Head') @ worn_rel)
    for f in range(pick - 8, hit + 4):
        sc.frame_set(f)
        worn = bone('Head') @ worn_rel
        if f < pick:                                         # reaching: still on the desk
            M = desk
        elif f < carry_end:                                  # both hands carry it up to the head
            t = smooth((f - pick) / (carry_end - pick))
            lifted = Matrix.Translation(hands_mid() + Vector((0, 0, 0.035))) @ desk.to_3x3().to_4x4()
            M = blend(blend(desk, lifted, smooth((f - pick) / 4)), worn, t)
        elif f < grab:
            M = worn
        elif f < release:                                    # in the right hand
            M = blend(worn, bone('RightHandMiddle1') @ hand_rel, smooth((f - grab) / 3))
        else:
            M = None
        keys[f] = M
    # the throw: from the release point to just in front of the lens, spinning, the crown facing the camera
    sc.frame_set(release)
    P0 = keys[release - 1].translation
    sc.frame_set(release - 1)
    Pm = keys[release - 2].translation
    v0 = (P0 - Pm)
    sc.frame_set(hit)
    cam = sc.camera
    cpos = cam.matrix_world.translation
    cfwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    P1 = cpos + cfwd * hc.lens_gap
    R0 = keys[release - 1].to_quaternion()
    face_cam = (-cfwd).to_track_quat('Z', 'Y')                # the crown toward the lens
    n = hit - release
    for i, f in enumerate(range(release, hit + 4)):
        t = (i + 1) / n
        c1 = P0 + v0 * (n / 3)
        p = (1 - t) ** 2 * P0 + 2 * (1 - t) * t * c1 + t * t * P1 if t <= 1 else P1 + cfwd * (-0.25 * (t - 1))
        spin = Quaternion(Vector((0, 0, 1)), math.radians(hc.spin) * t)
        q = R0.slerp(face_cam, smooth(t)) @ spin
        keys[f] = Matrix.LocRotScale(p, q, Vector((hc.scale,) * 3))
    cap.rotation_mode = 'QUATERNION'
    cap.animation_data_clear()

    def put(f, M, visible=True):
        loc, rot, scl = M.decompose()
        cap.location, cap.rotation_quaternion, cap.scale = loc, rot, scl
        for path in ('location', 'rotation_quaternion', 'scale'):
            cap.keyframe_insert(path, frame=f)
        cap.hide_render = cap.hide_viewport = not visible
        cap.keyframe_insert('hide_render', frame=f)
        cap.keyframe_insert('hide_viewport', frame=f)
    put(cfg.project.frame_start, desk)
    for f in sorted(keys):
        put(f, keys[f], visible=f <= hit + 1)
    put(hit + 4, keys[hit + 3], visible=False)
    for fc in cap.animation_data.action.layers[0].strips[0].channelbags[0].fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR' if 'hide' not in fc.data_path else 'CONSTANT'
    print(f'[stage] hat: desk -> hands {pick} -> head {carry_end} -> right hand {grab} -> thrown {release} -> lens {hit}')
