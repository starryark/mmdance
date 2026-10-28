"""Stage: the set, lighting and render settings.

`stage.builder = "default"` makes a floor under a flat backdrop. A project can instead point it
at its own module (e.g. "room.py") defining build(collection, cfg), and optionally colliders(cfg)
returning box colliders (x0, x1, y0, y1, top) for the cloth and hair, and finish(collection, cfg),
called last to adjust the lights, shading and render settings for the project's look.
"""
import math

import bpy

from .physics import load_stage_module
from .util import collection


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


def lights(cfg):
    st = cfg.stage
    if st.sun:
        sun = bpy.data.objects[st.sun]
    else:                                         # the character file's own sun, if it has one
        sun = next((o for o in bpy.data.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)
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
        e.ray_tracing_options.trace_max_roughness = 0.4
        e.use_fast_gi = False
    elif r.engine == 'CYCLES':
        sc.cycles.samples = r.samples
    sc.render.filter_size = r.filter_size
    sc.render.film_transparent = False
    sc.view_settings.view_transform = r.view_transform
    sc.view_settings.look = 'None'
    sc.render.resolution_x, sc.render.resolution_y = cfg.camera.resolution
    sc.render.resolution_percentage = 100


def run(cfg):
    coll = collection('Stage')
    clear_collection(coll)
    world(cfg)
    mod = load_stage_module(cfg)
    if mod is None:
        default_stage(coll, cfg)
    else:
        mod.build(coll, cfg)
    lights(cfg)
    if cfg.stage.glow:
        glow(cfg)
    render_settings(cfg)
    if mod is not None and hasattr(mod, 'finish'):
        mod.finish(coll, cfg)
