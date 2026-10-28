"""Stage: the set, lighting and render settings.

`stage.builder = "default"` makes a floor under a flat backdrop, and `"set"` appends a set made in
another .blend (`[stage.set]`), scaled and placed around the dance. A project can instead point it
at its own module (e.g. "room.py") defining build(collection, cfg), and optionally colliders(cfg)
returning box colliders (x0, x1, y0, y1, top) for the cloth and hair, and finish(collection, cfg),
called last to adjust the lights, shading and render settings for the project's look.

Before finish(), the stage runs the project's own steps on the built character (`stage.steps`:
a face rebuild, a prop, sleeves; each file defines run(cfg, collection)), swaps in cleaned copies
of the character's textures (`stage.textures`) and gives single-layer fabric a darker inside
(`stage.lining`). On a moving camera the key light can follow it (`stage.key_follow`), lighting
only the character (`stage.key_link`).
"""
import math

import bpy
import numpy as np
from mathutils import Matrix, Vector

from .camera import track_dancer
from .physics import load_stage_module
from .util import collection, new_action, project_module, put_curve, rig_and_body


def clear_collection(c):
    for o in list(c.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def world(cfg):
    """The world gives the ambient term (and the backdrop of the default stage)."""
    st = cfg.stage
    sc = bpy.context.scene
    w = bpy.data.worlds.get(st.world) if st.world else sc.world
    if w is None:
        w = bpy.data.worlds.new('Stage_World')
    sc.world = w
    if w.node_tree is None:                       # (worlds always have node trees from Blender 5)
        w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = tuple(st.world_color) + (1,)
    bg.inputs['Strength'].default_value = st.world_strength
    nt.links.new(bg.outputs[0], out.inputs['Surface'])


def key_sun(cfg):
    """The key light: `stage.sun`, else the character file's first sun, else None."""
    if cfg.stage.sun:
        return bpy.data.objects[cfg.stage.sun]
    return next((o for o in bpy.data.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)


def lights(cfg):
    st = cfg.stage
    sun = key_sun(cfg)
    if sun is None:
        ld = bpy.data.lights.new('Stage_Sun', 'SUN')
        sun = bpy.data.objects.new('Stage_Sun', ld)
        collection('Stage').objects.link(sun)
        sun.rotation_euler = [math.radians(a) for a in st.sun_rotation]
        ld.energy = st.sun_energy
    sun.data.angle = math.radians(st.sun_angle)
    sun.data.use_shadow = True
    sun.data.color = tuple(st.sun_color)


def default_stage(coll, cfg):
    """A large floor disc; the world colour is the backdrop."""
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=12.0, fill_type='NGON', location=(0, 0, 0))
    fl = bpy.context.object
    fl.name = 'Stage_Floor'
    for c in list(fl.users_collection):
        c.objects.unlink(fl)
    coll.objects.link(fl)
    m = bpy.data.materials.get('Stage_Floor') or bpy.data.materials.new('Stage_Floor')
    if m.node_tree is None:
        m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = tuple(cfg.stage.floor_color) + (1,)
    bsdf.inputs['Roughness'].default_value = 0.6
    fl.data.materials.append(m)


def set_stage(coll, cfg):
    """A set from another .blend (`[stage.set]`): its collections are appended and hung on one empty,
    `Set_Root`, which scales, turns and places them around the dance (the set's `center_set` onto
    the dance's `center_dance`, floor plan coordinates). Point, spot and area lights lose power by
    the scale squared and soft shadow size by the scale, so the smaller set is lit as before."""
    ss = cfg.stage.set
    path = cfg.resolve(ss.file)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [n for n in src.collections if n in ss.collections] if ss.collections else list(src.collections)
        dst.worlds = [ss.world] if ss.world else []
    nested = {ch for c in dst.collections for ch in c.children}
    root = bpy.data.objects.new('Set_Root', None)
    root.empty_display_size = 0.5
    coll.objects.link(root)
    parts = []
    for c in dst.collections:
        if c in nested:
            continue
        c.name = 'Set_' + c.name
        coll.children.link(c)
        for o in c.all_objects:
            if o.parent is None:
                o.parent = root
            parts.append(o)
    s = ss.scale
    c_set = Vector((ss.center_set[0], ss.center_set[1], 0.0))
    c_dance = Vector((ss.center_dance[0], ss.center_dance[1], 0.0))
    R = Matrix.Rotation(math.radians(ss.rotation), 4, 'Z')
    root.matrix_world = Matrix.Translation(c_dance - R @ (s * c_set)) @ R @ Matrix.Diagonal((s, s, s, 1.0))
    seen = set()
    for o in parts:
        if o.type == 'LIGHT' and o.data.name not in seen and o.data.type in ('POINT', 'SPOT', 'AREA'):
            seen.add(o.data.name)
            o.data.energy *= s * s
            if o.data.type != 'AREA':
                o.data.shadow_soft_size *= s
    if dst.worlds:
        bpy.context.scene.world = dst.worlds[0]
    print(f'[stage] set: {len(parts)} objects from {path}, scale {s}')


def camera_rotations(cfg):
    """The scene camera's world rotation on every frame (marker switches included), with everything
    but the cameras, their parents and their targets hidden so the frames evaluate fast."""
    sc = bpy.context.scene
    keep = set()
    for o in sc.objects:
        if o.type == 'CAMERA':
            p = o
            while p is not None:
                keep.add(p)
                p = p.parent
            keep.update(c.target for c in o.constraints if getattr(c, 'target', None) is not None)
    hidden = [o for o in sc.objects if o not in keep and not o.hide_viewport]
    for o in hidden:
        o.hide_viewport = True
    out = []
    for f in range(cfg.project.frame_start, cfg.project.frame_end + 1):
        sc.frame_set(f)
        out.append(sc.camera.matrix_world.to_quaternion())
    for o in hidden:
        o.hide_viewport = False
    return out


def key_follow(cfg):
    """The key light follows the camera (`stage.key_follow` = [elevation, azimuth] degrees: from above
    the camera, turned round from it), so a toon face reads lit whichever way the dancer turns. The
    face shading driver reads the sun's rotation_euler x and z, so y stays 0. `stage.key_link` lights
    only the character with it (light linking): the set keeps its own lights."""
    st = cfg.stage
    sun = key_sun(cfg)
    el, az = (math.radians(a) for a in st.key_follow)
    rz = []
    for q in camera_rotations(cfg):
        fwd = q @ Vector((0, 0, -1))
        rz.append(math.atan2(-fwd.x, fwd.y) + az)     # Euler (rx, 0, rz) sends the sun's -Z that way
    rz = np.unwrap(rz)
    sun.animation_data_clear()
    sun.rotation_mode = 'XYZ'
    _, cbag = new_action(sun, sun.name + '_Follow')
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    for k, v in enumerate((np.full(len(rz), math.pi / 2 - el), np.zeros(len(rz)), rz)):
        put_curve(cbag, 'rotation_euler', k, frames, v.astype(np.float32))
    if st.key_energy > 0:
        sun.data.energy = st.key_energy
    if st.key_link:
        rig, _ = rig_and_body(cfg)
        chars = bpy.data.collections.get('Dancer_Light') or bpy.data.collections.new('Dancer_Light')
        for o in [rig] + list(rig.children_recursive) + [o for o in bpy.data.objects if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]:
            if o.name not in chars.objects:
                chars.objects.link(o)
        sun.light_linking.receiver_collection = chars
        sun.light_linking.blocker_collection = chars
    print(f'[stage] key light follows the camera ({len(rz)} frames)')


def glow(cfg):
    """Soft bloom on bright areas (compositor fog glow)."""
    st = cfg.stage
    sc = bpy.context.scene
    try:
        ng = bpy.data.node_groups.get('Stage_Glow') or bpy.data.node_groups.new('Stage_Glow', 'CompositorNodeTree')
        ng.nodes.clear()
        if not any(getattr(i, 'in_out', '') == 'OUTPUT' for i in ng.interface.items_tree):
            ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ng.nodes.new('CompositorNodeRLayers')
        gl = ng.nodes.new('CompositorNodeGlare')
        out = ng.nodes.new('NodeGroupOutput')
        for k, v in (('glare_type', 'FOG_GLOW'), ('quality', 'HIGH'), ('threshold', st.glow_threshold), ('size', 7), ('mix', -0.55)):
            if hasattr(gl, k):
                try:
                    setattr(gl, k, v)
                except Exception:
                    pass
        for name, v in (('Threshold', st.glow_threshold), ('Strength', st.glow_strength), ('Size', st.glow_size)):
            if name in gl.inputs:
                gl.inputs[name].default_value = v
        if 'Type' in gl.inputs:
            try:
                gl.inputs['Type'].default_value = 'Fog Glow'
            except Exception:
                pass
        ng.links.new(rl.outputs['Image'], gl.inputs['Image'])
        ng.links.new(gl.outputs['Image'], out.inputs[0])
        sc.compositing_node_group = ng
        sc.render.use_compositing = True
        print('[stage] glow on')
    except Exception as ex:                       # never let the bloom block a build
        print('[stage] glow skipped:', ex)


def colour_input(nt, name):
    """The shader input `name` (e.g. "Base Color") that the material's colour is linked into: the
    one on the path to the material output when several nodes have it."""
    cands = [n for n in nt.nodes if name in n.inputs and n.inputs[name].is_linked]
    if len(cands) > 1:
        out = next((n for n in nt.nodes if n.bl_idname == 'ShaderNodeOutputMaterial' and n.is_active_output), None)
        upstream, todo = set(), [out] if out else []
        while todo:
            n = todo.pop()
            for i in n.inputs:
                for lk in i.links:
                    if lk.from_node.name not in upstream:
                        upstream.add(lk.from_node.name)
                        todo.append(lk.from_node)
        cands = [n for n in cands if n.name in upstream] or cands
    return cands[0].inputs[name] if cands else None


def lining(name, tint):
    """Single-layer fabric shows its printed outside on its backfaces when it flies up: the inside
    gets the outside's colour multiplied by `tint` instead."""
    m = bpy.data.materials.get(name)
    if m is None or m.node_tree is None:
        print(f'[stage] lining: no material {name}')
        return
    nt = m.node_tree
    if nt.nodes.get('Lining_Backfacing'):
        return
    dst = colour_input(nt, 'Base Color')
    if dst is None:
        print(f'[stage] lining: {name} has no linked Base Color input')
        return
    src = dst.links[0].from_socket
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    geo.name = 'Lining_Backfacing'
    inner = nt.nodes.new('ShaderNodeMix')
    inner.data_type, inner.blend_type = 'RGBA', 'MULTIPLY'
    inner.inputs['Factor'].default_value = 1.0
    nt.links.new(src, inner.inputs['A'])
    inner.inputs['B'].default_value = tuple(tint) + (1,)
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type, mix.blend_type = 'RGBA', 'MIX'
    nt.links.new(geo.outputs['Backfacing'], mix.inputs['Factor'])
    nt.links.new(src, mix.inputs['A'])
    nt.links.new(inner.outputs['Result'], mix.inputs['B'])
    nt.links.new(mix.outputs['Result'], dst)


def swap_textures(cfg):
    """Cleaned copies of the character's textures (`stage.textures`: image name -> file)."""
    for name, path in cfg.stage.textures.items():
        img = bpy.data.images[name]
        img.filepath = cfg.resolve(path)
        img.reload()


def render_settings(cfg):
    r = cfg.render
    sc = bpy.context.scene
    sc.render.engine = r.engine
    if r.engine == 'BLENDER_EEVEE':
        e = sc.eevee
        e.taa_render_samples = r.samples
        e.use_shadows = True
        e.shadow_ray_count = 2
        e.shadow_step_count = 8
        e.use_raytracing = r.raytracing
        e.ray_tracing_method = 'SCREEN'
        e.ray_tracing_options.resolution_scale = '1'
        e.ray_tracing_options.trace_max_roughness = r.trace_max_roughness
        e.use_fast_gi = r.fast_gi
        e.shadow_pool_size = r.shadow_pool
    elif r.engine == 'CYCLES':
        sc.cycles.samples = r.samples
    sc.render.filter_size = r.filter_size
    sc.render.film_transparent = False
    sc.view_settings.view_transform = r.view_transform
    sc.view_settings.look = r.look
    sc.view_settings.exposure = r.exposure
    sc.render.use_motion_blur = r.motion_blur > 0
    if r.motion_blur > 0:
        sc.render.motion_blur_shutter = r.motion_blur
    sc.render.resolution_x, sc.render.resolution_y = cfg.camera.resolution
    sc.render.resolution_percentage = 100


def run(cfg):
    coll = collection('Stage')
    clear_collection(coll)
    world(cfg)
    mod = load_stage_module(cfg)
    if cfg.stage.builder == 'set':
        set_stage(coll, cfg)
    elif mod is None:
        default_stage(coll, cfg)
    else:
        mod.build(coll, cfg)
    lights(cfg)
    if cfg.stage.glow:
        glow(cfg)
    render_settings(cfg)
    for path in cfg.stage.steps:                  # project code on the built character
        print(f'[stage] step {path}')
        project_module(cfg, path).run(cfg, coll)
    swap_textures(cfg)
    for name, tint in cfg.stage.lining.items():
        lining(name, tint)
    if cfg.camera.track and cfg.camera.track_dancer:     # last: earlier stages need the rig at the origin
        track_dancer(cfg, np.load(cfg.path('camera.track')))
    if cfg.stage.key_follow:
        key_follow(cfg)
    if mod is not None and hasattr(mod, 'finish'):
        mod.finish(coll, cfg)
