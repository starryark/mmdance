"""The Anthropic lobby (Anthropic_Scene/05_output/lobby.blend) as the stage, and the camera solved
from the meme's reference video.

A project stage builder for mmdance (stage.builder = "../lobby.py"), shared by the Claude and the
ChatGPT project:
* build() appends the lobby's collections (architecture, furniture, plants, lights, exterior,
  sign) and hangs them on one empty, `Lobby_Root`, scaled by [stage.lobby] scale around the dance:
  the characters are 1 m tall, the lobby is real size, so the lobby shrinks by 1/1.6 and they
  read as 1.6 m. Point, spot and area lights lose power by scale^2 to light it as before.
* finish() keys the camera and the dancer's turn from camera.track (tools/assemble_camera.py in
  Anthropic_Scene/MMD_DreamWings): `Ref_Cam` with the reference's lens (15 mm on 36 mm, 100 deg)
  on every frame, and the rig object's location and yaw on every frame (the mocap kept the dancer
  facing the lens; the real camera went round the rooftop, so the dancer and camera turn together).
  It also runs the per-character project code (face_rebuild.py for Claude, sleeves.py and wings.py
  for ChatGPT) as the room.py builders do, and sets the light and render settings.
"""
import importlib.util
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

KEEP = ['ARCHITECTURE', 'FURNITURE', 'VEGETATION', 'LIGHTS', 'EXTERIOR', 'SIGNAGE']


def lobby_cfg(cfg):
    return cfg.stage.lobby


def remove_lobby():
    """A re-run of the stage starts from a clean scene."""
    for name in KEEP:
        c = bpy.data.collections.get('Lobby_' + name)
        if c is not None:
            for o in list(c.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    o = bpy.data.objects.get('Lobby_Root')
    if o is not None:
        bpy.data.objects.remove(o, do_unlink=True)


def lobby_matrix(lc):
    """Lobby space -> dance space: scale, turn about Z, then the lobby's chosen spot onto the dance's."""
    s = lc.scale
    R = Matrix.Rotation(math.radians(lc.rotation), 4, 'Z')
    c_l = Vector((lc.center_lobby[0], lc.center_lobby[1], 0.0))
    c_d = Vector((lc.center_dance[0], lc.center_dance[1], 0.0))
    t = c_d - (R @ (s * c_l))
    return Matrix.Translation(t) @ R @ Matrix.Diagonal((s, s, s, 1.0))


def build(coll, cfg):
    lc = lobby_cfg(cfg)
    remove_lobby()
    path = cfg.resolve(lc.file)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [n for n in src.collections if n in KEEP]
        dst.worlds = [lc.world]
    root = bpy.data.objects.new('Lobby_Root', None)
    root.empty_display_size = 0.5
    coll.objects.link(root)
    parts = []
    for c in dst.collections:
        c.name = 'Lobby_' + c.name
        coll.children.link(c)
        for o in c.objects:
            if o.parent is None:
                o.parent = root
            parts.append(o)
    root.matrix_world = lobby_matrix(lc)
    s2 = lc.scale ** 2
    seen = set()
    for o in parts:
        if o.type == 'LIGHT' and o.data.name not in seen:
            seen.add(o.data.name)
            if o.data.type in ('POINT', 'SPOT', 'AREA'):
                o.data.energy *= s2
                if o.data.type != 'AREA':
                    o.data.shadow_soft_size *= lc.scale
    print(f'[stage] lobby: {len(parts)} objects from {os.path.basename(path)}, scale {lc.scale}')
    return parts


def colliders(cfg):
    """The dance stays on open floor: the floor (always on) is the only collider."""
    return []


def project_module(cfg, name):
    """Another module of the character's project folder (face_rebuild.py, sleeves.py), loaded by path."""
    spec = importlib.util.spec_from_file_location('dreamwings_' + name, cfg.resolve(name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lining(mat_name, tint):
    """The inside of single-layer fabric in a darker shade of its print (as the room builders)."""
    m = bpy.data.materials.get(mat_name)
    if m is None or m.node_tree.nodes.get('Lining_Backfacing'):
        return
    nt = m.node_tree
    g = next(n for n in nt.nodes if n.bl_idname == 'ShaderNodeGroup' and n.node_tree.name == 'AIG_Toon')
    src = g.inputs['Base Color'].links[0].from_socket
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    geo.name = 'Lining_Backfacing'
    mul = nt.nodes.new('ShaderNodeMix')
    mul.data_type = 'RGBA'
    mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.0
    nt.links.new(src, mul.inputs['A'])
    mul.inputs['B'].default_value = tuple(tint) + (1,)
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    nt.links.new(geo.outputs['Backfacing'], mix.inputs['Factor'])
    nt.links.new(src, mix.inputs['A'])
    nt.links.new(mul.outputs['Result'], mix.inputs['B'])
    nt.links.new(mix.outputs['Result'], g.inputs['Base Color'])


def put_keys(obj, curves, frames, fresh=True):
    """Dense linear F-curves {data path: (n, k) values} on the object: in a new action, or (fresh=False)
    added to its own action, as for the rig, whose action carries the dance."""
    from mmdance.util import channelbag, new_action, put_curve
    if fresh or obj.animation_data is None or obj.animation_data.action is None:
        _, bag = new_action(obj, obj.name + '_Track')
    else:
        bag = channelbag(obj)
    for path, values in curves.items():
        for k in range(values.shape[1]):
            old = bag.fcurves.find(path, index=k)
            if old is not None:
                bag.fcurves.remove(old)
            put_curve(bag, path, k, frames, values[:, k].astype(np.float32))


def camera(cfg, track):
    sc = bpy.context.scene
    for m in list(sc.timeline_markers):
        sc.timeline_markers.remove(m)
    old = bpy.data.objects.get('Ref_Cam')
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    cd = bpy.data.cameras.new('Ref_Cam')
    cd.sensor_fit = 'HORIZONTAL'
    cd.sensor_width = float(track['sensor'])
    cd.lens = float(track['lens'])
    cd.clip_start, cd.clip_end = 0.01, 120.0
    cam = bpy.data.objects.new('Ref_Cam', cd)
    (bpy.data.collections.get('Cameras') or sc.collection).objects.link(cam)
    cam.rotation_mode = 'QUATERNION'
    put_keys(cam, {'location': track['loc'], 'rotation_quaternion': track['quat']}, track['frames'].astype(np.float32))
    sc.camera = cam
    return cam


def dancer_turn(cfg, track):
    """The rig object's location and yaw per frame: the turn the mocap left out."""
    who = lobby_cfg(cfg).character
    rig = bpy.data.objects[cfg.character.rig]
    rig.rotation_mode = 'XYZ'
    rz = track['rig_rotz_' + who]
    put_keys(rig, {'location': track['rig_loc_' + who],
                   'rotation_euler': np.stack([np.zeros_like(rz), np.zeros_like(rz), rz], 1)},
             track['frames'].astype(np.float32), fresh=False)
    return rig


def key_light(cfg, cam, track):
    """AIG_Sun, the character's key: it drives the face shading (its direction) and lights only the
    character (light linking), from above the camera and a little to its left, so the face reads
    lit as in the reference's evening light whichever way the dancer has turned."""
    lc = lobby_cfg(cfg)
    sun = bpy.data.objects[cfg.stage.sun]
    sun.animation_data_clear()
    sun.rotation_mode = 'XYZ'                     # the face driver reads rotation_euler x and z (y = 0)
    el, az = math.radians(lc.key_elevation), math.radians(lc.key_azimuth)
    rx, rz = [], []
    for q in track['quat']:
        fwd = Quaternion(q) @ Vector((0, 0, -1))
        yaw = math.atan2(-fwd.x, fwd.y)
        # the light travels the camera's way (from behind it), turned by az and coming down at el:
        # Euler (rx, 0, rz) sends the sun's -Z along (-sin rx sin rz, sin rx cos rz, -cos rx)
        rx.append(math.pi / 2 - el)
        rz.append(yaw + az)
    rz = np.unwrap(rz)
    put_keys(sun, {'rotation_euler': np.stack([rx, np.zeros_like(rz), rz], 1)}, track['frames'].astype(np.float32))
    sun.data.energy = lc.key_energy
    chars = bpy.data.collections.get('Dancer_Light') or bpy.data.collections.new('Dancer_Light')
    rig = bpy.data.objects[cfg.character.rig]
    for o in [rig] + [c for c in rig.children_recursive] + [o for o in bpy.data.objects if o.type == 'MESH' and any(
            m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]:
        if o.name not in chars.objects:
            chars.objects.link(o)
    sun.light_linking.receiver_collection = chars
    sun.light_linking.blocker_collection = chars
    return sun


def render(cfg):
    lc = lobby_cfg(cfg)
    sc = bpy.context.scene
    e = sc.eevee
    e.use_shadows = True
    e.shadow_ray_count = 2
    e.shadow_step_count = 8
    e.use_raytracing = True
    e.ray_tracing_method = 'SCREEN'
    e.ray_tracing_options.resolution_scale = '1'
    e.ray_tracing_options.trace_max_roughness = 0.5
    e.use_fast_gi = True
    e.shadow_pool_size = lc.shadow_pool
    sc.render.use_motion_blur = lc.motion_blur > 0
    sc.render.motion_blur_shutter = lc.motion_blur
    sc.view_settings.view_transform = lc.view_transform
    sc.view_settings.look = lc.look
    sc.view_settings.exposure = lc.exposure


def finish(coll, cfg):
    lc = lobby_cfg(cfg)
    body = bpy.data.objects[cfg.character.body]
    if cfg.stage.get('face_rebuild') and not body.get('face_rebuilt'):
        project_module(cfg, 'face_rebuild').run(cfg, body)
        body['face_rebuilt'] = 1                    # once per scene (the stage can be re-run)
    if cfg.stage.get('sleeves'):
        project_module(cfg, 'sleeves').run(cfg)
    if cfg.stage.get('wings'):
        project_module(cfg, 'wings').run(cfg)
    for name, tint in cfg.stage.get('lining', {}).items():
        lining(name, tint)
    sc = bpy.context.scene
    sc.world = bpy.data.worlds[lc.world]
    track = np.load(cfg.path('camera.track'))
    cam = camera(cfg, track)
    dancer_turn(cfg, track)
    key_light(cfg, cam, track)
    render(cfg)
    print(f'[stage] lobby camera and dancer turn keyed ({len(track["frames"])} frames, cut at {int(track["cut"])})')
