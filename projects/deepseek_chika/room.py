"""The student-council room from the original video (akomni, sm34597101), rebuilt as our own
geometry, lit by the afternoon sun through its windows.

Wood-panelled walls with a pink wainscot, tall white-framed windows onto a blue sky, dark maroon
curtains gathered with gold tiebacks under a valance, a dark cornice, a red/pink harlequin floor,
a dark writing desk with a diagonal cloth, brass lamp and books, a red upholstered chair behind it
and a green chesterfield sofa. Scaled to the character (1 m tall); the desk is the collider the
dance lies on, the sofa the one she sits on.

The set is the claude_chika room with its light reworked (see README.md):
* the back wall has real openings: a sun outside shines in through the windows, casting the
  window bars, curtains, furniture and the dancer across the floor, with beams in a haze that
  thickens toward the windows;
* the set has soft-lit shading that follows the light that arrives (Room_Shade); the dancer keeps
  her cel shading, with a warm sunlit tone where the window sun reaches her;
* over the song the sun sinks and warms and its strength follows the music (CUES);
* desk props sit where the dance leaves room on the desk.

A project stage builder for mmdance (stage.builder = "room.py"): build(collection, cfg) makes the
set, colliders(cfg) gives the desk and sofa boxes to the cloth/hair simulation, finish(collection,
cfg) sets the light. The desk, sofa and props are placed from [stage] desk / sofa / props in
project.toml (motion scales differ a little between characters). Needs a character file with the
AIG_Toon group (the polished Tripo characters have it).

Shared: chatgpt_chika and claude_chika_v3 use this file too (stage.builder =
"../deepseek_chika/room.py"). The character's own steps (face, cap, sleeves), cleaned textures and
lining are run by the stage before finish() (stage.steps, stage.textures, stage.lining).
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

# desk the intro is danced on (box collider + prop): x0, x1, y0, y1, top
BED = (-0.22, 0.62, -0.34, 0.22, 0.48)
# sofa she sits on around 46-48 s: x0, x1, y0 (front edge), y1 (seat back), seat top
SOFA = (0.84, 1.96, -1.24, -0.82, 0.29)


# desk props: where the dance leaves room on this desk (x, y; laptop and lamp also a yaw in degrees)
PROPS = {'laptop': (0.555, 0.10, -14.0), 'lamp': (0.40, 0.15), 'phone': (0.60, -0.06)}


def _place(cfg):
    global BED, SOFA, PROPS
    BED = tuple(cfg.stage.get('desk', BED))
    SOFA = tuple(cfg.stage.get('sofa', SOFA))
    PROPS = dict(cfg.stage.get('props', PROPS))


def colliders(cfg):
    """Every box the gown and hair collide with: (x0, x1, y0, y1, top)."""
    _place(cfg)
    return [BED,
            (SOFA[0] - 0.10, SOFA[1] + 0.10, SOFA[2], SOFA[3] + 0.12, SOFA[4]),            # seat
            (SOFA[0] - 0.10, SOFA[1] + 0.10, SOFA[3], SOFA[3] + 0.12, SOFA[4] + 0.30),     # back
            (SOFA[0] - 0.10, SOFA[0], SOFA[2], SOFA[3] + 0.12, SOFA[4] + 0.13),            # arms
            (SOFA[1], SOFA[1] + 0.10, SOFA[2], SOFA[3] + 0.12, SOFA[4] + 0.13)]

WALL_Y = 0.86           # back wall
WALL_X0, WALL_X1 = -3.2, 3.8
FRONT_Y = -4.6
H = 2.02                 # ceiling
WIN_SILL, WIN_TOP, WIN_W = 0.50, 1.80, 0.86      # tall, wide windows as in the original
WIN_XS = [-0.50, 0.62, 1.74, 2.86]
DOOR_X, DOOR_W, DOOR_H = -1.62, 0.62, 1.52        # a glazed wooden door on the left
PLANT_XY = (2.22, 0.50)                            # a tall potted plant behind the sofa's right end


def srgb(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def link(nt, a, b):
    nt.links.new(a, b)


def room_shade_group():
    """Soft-lit shading for the set (the character keeps the AIG_Toon cel shading).

    The colour follows the light that actually arrives (its colour too), with a soft shoulder, over
    a tinted ambient floor: sunlight through the windows makes warm pools, the furniture and the
    dancer cast shadows, and walls turned away from the light fall off. Same inputs as AIG_Toon, so
    the materials below can use either."""
    ng = bpy.data.node_groups.get('Room_Shade')
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new('Room_Shade', 'ShaderNodeTree')
    for name, kind, val in (('Base Color', 'NodeSocketColor', (0.8, 0.8, 0.8, 1)), ('Shadow Tint', 'NodeSocketColor', (0.8, 0.75, 0.85, 1)),
                            ('Deep Shadow Tint', 'NodeSocketColor', (0.7, 0.65, 0.75, 1)), ('Threshold', 'NodeSocketFloat', 0.3),
                            ('Softness', 'NodeSocketFloat', 0.05), ('Deep Threshold', 'NodeSocketFloat', 0.05),
                            ('Terminator Strength', 'NodeSocketFloat', 0.0), ('Rim Color', 'NodeSocketColor', (1, 1, 1, 1)),
                            ('Rim Strength', 'NodeSocketFloat', 0.0), ('Rim Width', 'NodeSocketFloat', 0.3),
                            ('Lit Boost', 'NodeSocketFloat', 1.0), ('Use Light Dir', 'NodeSocketFloat', 0.0),
                            ('Ambient', 'NodeSocketFloat', 0.2)):
        sk = ng.interface.new_socket(name, in_out='INPUT', socket_type=kind)
        sk.default_value = val
    ng.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    N = ng.nodes
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')
    dif = N.new('ShaderNodeBsdfDiffuse')
    dif.inputs['Color'].default_value = (1, 1, 1, 1)
    s2r = N.new('ShaderNodeShaderToRGB')
    link(ng, dif.outputs[0], s2r.inputs[0])

    def vmath(op, a, b, c=None):
        n = N.new('ShaderNodeVectorMath')
        n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, tuple):
                n.inputs[i].default_value = v
            else:
                link(ng, v, n.inputs[i])
        return n.outputs[0]
    knee = 2.4                                   # soft shoulder: light L -> L / (1 + L / knee)
    light = s2r.outputs['Color']
    soft = vmath('DIVIDE', light, vmath('MULTIPLY_ADD', light, (1 / knee,) * 3, (1.0, 1.0, 1.0)))
    amb = vmath('SCALE', gin.outputs['Shadow Tint'], None)
    amb.node.inputs['Scale'].default_value = 0.48
    lit = vmath('MULTIPLY_ADD', soft, (0.80, 0.80, 0.80), amb)
    col = vmath('MULTIPLY', gin.outputs['Base Color'], lit)
    lw = N.new('ShaderNodeLayerWeight')
    link(ng, gin.outputs['Rim Width'], lw.inputs['Blend'])
    rim = vmath('SCALE', gin.outputs['Rim Color'], None)
    link(ng, math_node(ng, 'MULTIPLY', lw.outputs['Facing'], math_node(ng, 'MULTIPLY', gin.outputs['Rim Strength'], 0.2)),
         rim.node.inputs['Scale'])
    grade = N.new('ShaderNodeRGB')
    grade.name = grade.label = 'Light_Grade'
    grade.outputs[0].default_value = (1, 1, 1, 1)
    out = vmath('MULTIPLY', vmath('ADD', col, rim), grade.outputs[0])
    em = N.new('ShaderNodeEmission')
    link(ng, out, em.inputs['Color'])
    link(ng, gin.outputs['Lit Boost'], em.inputs['Strength'])
    link(ng, em.outputs[0], gout.inputs[0])
    return ng


def toon(name, base, shadow, rim=0.05, thr=0.30, base_socket=None):
    """Toon material driven by the character's AIG_Toon group. Returns (material, group node)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    g = nt.nodes.new('ShaderNodeGroup')
    g.node_tree = room_shade_group()
    g.inputs['Base Color'].default_value = srgb(base) + (1,)
    g.inputs['Shadow Tint'].default_value = shadow + (1,)
    g.inputs['Deep Shadow Tint'].default_value = tuple(c * 0.86 for c in shadow) + (1,)
    g.inputs['Threshold'].default_value = thr
    g.inputs['Softness'].default_value = 0.06
    g.inputs['Deep Threshold'].default_value = 0.05
    g.inputs['Terminator Strength'].default_value = 0.0
    g.inputs['Rim Color'].default_value = (1, 0.95, 0.88, 1)
    g.inputs['Rim Strength'].default_value = rim
    g.inputs['Rim Width'].default_value = 0.3
    g.inputs['Lit Boost'].default_value = 1.0
    g.inputs['Use Light Dir'].default_value = 0.0
    g.inputs['Ambient'].default_value = 0.2
    link(nt, g.outputs[0], out.inputs['Surface'])
    return m, g


def ink_mat(name='Room_Ink', color=(0.16, 0.07, 0.06)):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = color + (1,)
    link(nt, em.outputs[0], out.inputs['Surface'])
    m.use_backface_culling = True
    return m


def outline(ob, thickness=0.0035):
    ob.data.materials.append(ink_mat())
    md = ob.modifiers.new('Ink', 'SOLIDIFY')
    md.thickness = thickness
    md.offset = 1.0
    md.use_flip_normals = True
    md.use_rim = False
    md.material_offset = len(ob.data.materials) - 1


def new_obj(name, me, coll):
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    return o


def box(name, coll, x0, x1, y0, y1, z0, z1, mat, bevel=0.0, seg=2, smooth=False):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector(((x0 + x1) / 2 + v.co.x * (x1 - x0), (y0 + y1) / 2 + v.co.y * (y1 - y0), (z0 + z1) / 2 + v.co.z * (z1 - z0)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = new_obj(name, me, coll)
    me.materials.append(mat)
    if bevel:
        b = o.modifiers.new('Bevel', 'BEVEL')
        b.width = bevel
        b.segments = seg
        b.limit_method = 'ANGLE'
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return o


def tex_coord_nodes(nt):
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    link(nt, tc.outputs['Object'], sep.inputs[0])
    return sep


def math_node(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            link(nt, v, n.inputs[i])
    return n.outputs[0]


def mix_rgb(nt, fac, a, b, blend='MIX'):
    n = nt.nodes.new('ShaderNodeMix')
    n.data_type = 'RGBA'
    n.blend_type = blend
    for sock, v in (('Factor', fac), ('A', a), ('B', b)):
        if isinstance(v, tuple):
            n.inputs[sock].default_value = v
        elif isinstance(v, (int, float)):
            n.inputs[sock].default_value = v
        else:
            link(nt, v, n.inputs[sock])
    return n.outputs['Result']


# ------------------------------------------------------------------ materials
def plank_material(name, base, dark, shadow, period, axis='X', wood=True):
    """Vertical planks: colour stripes every `period` m along an axis, thin dark joints, soft grain."""
    m, g = toon(name, base, shadow)
    nt = m.node_tree
    sep = tex_coord_nodes(nt)
    coord = sep.outputs[axis]
    t = math_node(nt, 'DIVIDE', coord, period)
    fr = math_node(nt, 'FRACT', t)
    joint = math_node(nt, 'LESS_THAN', fr, 0.035)
    flo = math_node(nt, 'FLOOR', t)
    # per-plank tone variation
    h = math_node(nt, 'SINE', math_node(nt, 'MULTIPLY', flo, 12.9898))
    h = math_node(nt, 'FRACT', math_node(nt, 'MULTIPLY', h, 437.585))
    tone = mix_rgb(nt, math_node(nt, 'MULTIPLY', h, 0.35), srgb(base) + (1,), srgb(dark) + (1,))
    col = tone
    if wood:
        noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 3.0
        noise.inputs['Detail'].default_value = 3.0
        mp = nt.nodes.new('ShaderNodeMapping')
        mp.inputs['Scale'].default_value = (40.0, 40.0, 1.5) if axis == 'X' else (1.5, 40.0, 40.0)
        tc = nt.nodes.new('ShaderNodeTexCoord')
        link(nt, tc.outputs['Object'], mp.inputs['Vector'])
        link(nt, mp.outputs['Vector'], noise.inputs['Vector'])
        grain = math_node(nt, 'MULTIPLY', math_node(nt, 'SUBTRACT', noise.outputs['Fac'], 0.5), 0.25)
        col = mix_rgb(nt, math_node(nt, 'ABSOLUTE', grain), col, srgb(dark) + (1,))
    col = mix_rgb(nt, math_node(nt, 'MULTIPLY', joint, 0.7), col, srgb(dark) + (1,))
    # walls darken toward the ceiling (the room is lit from the windows, not from above)
    up = nt.nodes.new('ShaderNodeMapRange')
    up.inputs['From Min'].default_value = 1.0
    up.inputs['From Max'].default_value = 2.0
    up.inputs['To Max'].default_value = 0.45
    tcw = nt.nodes.new('ShaderNodeTexCoord')
    sepw = nt.nodes.new('ShaderNodeSeparateXYZ')
    link(nt, tcw.outputs['Object'], sepw.inputs[0])
    link(nt, sepw.outputs['Z'], up.inputs['Value'])
    col = mix_rgb(nt, up.outputs['Result'], col, srgb((0.30, 0.13, 0.09)) + (1,))
    link(nt, col, g.inputs['Base Color'])
    return m


def carpet_material():
    """Dark red carpet, matte, with a faint pile texture."""
    m, g = toon('Room_Floor', (0.40, 0.05, 0.07), (0.78, 0.66, 0.74), rim=0.0, thr=0.26)
    nt = m.node_tree
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 60.0
    noise.inputs['Detail'].default_value = 6.0
    col = mix_rgb(nt, math_node(nt, 'MULTIPLY', noise.outputs['Fac'], 0.18), srgb((0.40, 0.05, 0.07)) + (1,),
                  srgb((0.22, 0.02, 0.04)) + (1,))
    link(nt, col, g.inputs['Base Color'])
    return m


def harlequin_material():
    m, g = toon('Room_Floor', (0.62, 0.10, 0.16), (0.78, 0.66, 0.74), rim=0.0, thr=0.26)
    nt = m.node_tree
    sep = tex_coord_nodes(nt)
    s = 1.0 / 0.30                       # diamond size
    u = math_node(nt, 'MULTIPLY', math_node(nt, 'ADD', sep.outputs['X'], sep.outputs['Y']), s * 0.7071)
    v = math_node(nt, 'MULTIPLY', math_node(nt, 'SUBTRACT', sep.outputs['X'], sep.outputs['Y']), s * 0.7071)
    a = math_node(nt, 'FLOOR', u)
    b = math_node(nt, 'FLOOR', v)
    par = math_node(nt, 'FLOORED_MODULO', math_node(nt, 'ADD', a, b), 2.0)
    col = mix_rgb(nt, par, srgb((0.46, 0.04, 0.09)) + (1,), srgb((0.78, 0.33, 0.42)) + (1,))
    # faint gloss variation so the floor is not flat
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 1.2
    col = mix_rgb(nt, math_node(nt, 'MULTIPLY', noise.outputs['Fac'], 0.12), col, (1, 0.9, 0.9, 1), 'SCREEN')
    link(nt, col, g.inputs['Base Color'])
    # soft reflection (polished floor)
    out = [n for n in nt.nodes if n.bl_idname == 'ShaderNodeOutputMaterial'][0]
    gl = nt.nodes.new('ShaderNodeBsdfGlossy')
    gl.inputs['Roughness'].default_value = 0.18
    lw = nt.nodes.new('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.4
    fac = math_node(nt, 'MULTIPLY', lw.outputs['Fresnel'], 0.35)
    mx = nt.nodes.new('ShaderNodeMixShader')
    link(nt, fac, mx.inputs['Fac'])
    link(nt, g.outputs[0], mx.inputs[1])
    link(nt, gl.outputs[0], mx.inputs[2])
    link(nt, mx.outputs[0], out.inputs['Surface'])
    return m


def sky_material():
    m = bpy.data.materials.get('Room_Sky') or bpy.data.materials.new('Room_Sky')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    sep = tex_coord_nodes(nt)
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    zn = math_node(nt, 'DIVIDE', math_node(nt, 'SUBTRACT', sep.outputs['Z'], WIN_SILL), WIN_TOP - WIN_SILL)
    link(nt, zn, ramp.inputs[0])
    ramp.color_ramp.elements[0].color = srgb((0.95, 0.98, 1.0)) + (1,)
    ramp.color_ramp.elements[1].color = srgb((0.72, 0.88, 0.98)) + (1,)
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 2.2
    noise.inputs['Detail'].default_value = 5.0
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (1.0, 1.0, 2.4)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    link(nt, mp.outputs['Vector'], noise.inputs['Vector'])
    cl = nt.nodes.new('ShaderNodeMapRange')
    cl.inputs['From Min'].default_value = 0.52
    cl.inputs['From Max'].default_value = 0.66
    link(nt, noise.outputs['Fac'], cl.inputs['Value'])
    col = mix_rgb(nt, cl.outputs['Result'], ramp.outputs['Color'], (1, 1, 1, 1))
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Strength'].default_value = 2.2
    link(nt, col, em.inputs['Color'])
    link(nt, em.outputs[0], out.inputs['Surface'])
    return m


# ------------------------------------------------------------------ room shell
def shell(coll):
    wood, _ = toon('Room_Plaster', (0.94, 0.91, 0.87), (0.80, 0.74, 0.80), rim=0.0)          # cream plaster above
    wains = plank_material('Room_Wainscot', (0.36, 0.15, 0.09), (0.20, 0.08, 0.05), (0.78, 0.64, 0.66), 0.11)
    dark, _ = toon('Room_DarkWood', (0.20, 0.08, 0.06), (0.75, 0.62, 0.66))
    ceil, _ = toon('Room_Ceiling', (0.16, 0.07, 0.06), (0.9, 0.85, 0.85))
    floor_m = carpet_material()
    WAIN = 0.46
    parts = []
    # floor
    parts.append(box('Room_Floor', coll, WALL_X0, WALL_X1, FRONT_Y, WALL_Y, -0.02, 0.0, floor_m))
    # walls: back, left, right, front (the front one is behind the camera)
    walls = [('Back', (WALL_X0, WALL_X1, WALL_Y, WALL_Y + 0.05)), ('Left', (WALL_X0 - 0.05, WALL_X0, FRONT_Y, WALL_Y)),
             ('Right', (WALL_X1, WALL_X1 + 0.05, FRONT_Y, WALL_Y)), ('Front', (WALL_X0, WALL_X1, FRONT_Y - 0.05, FRONT_Y))]
    for nm, (x0, x1, y0, y1) in walls:
        if nm == 'Back':                  # the back wall has real openings: the sun comes in through them
            parts += back_wall(coll, x0, x1, y0, y1, WAIN, wood)
        else:
            parts.append(box(f'Room_Wall{nm}_Upper', coll, x0, x1, y0, y1, WAIN, H, wood))
        parts.append(box(f'Room_Wall{nm}_Wainscot', coll, x0, x1, y0, y1, 0.0, WAIN, wains))
    # trims on the back wall: baseboard, chair rail, cornice band
    yb = WALL_Y - 0.012
    parts.append(box('Room_Baseboard', coll, WALL_X0, WALL_X1, yb - 0.01, WALL_Y, 0.0, 0.05, dark, 0.004))
    parts.append(box('Room_ChairRail', coll, WALL_X0, WALL_X1, yb - 0.014, WALL_Y, WAIN - 0.012, WAIN + 0.016, dark, 0.004))
    parts.append(box('Room_Cornice', coll, WALL_X0, WALL_X1, yb - 0.09, WALL_Y, H - 0.16, H, dark, 0.006))
    parts.append(box('Room_Ceiling', coll, WALL_X0, WALL_X1, FRONT_Y, WALL_Y, H, H + 0.03, ceil))
    for p in parts:
        if p.name.startswith(('Room_WallFront', 'Room_WallLeft', 'Room_WallRight', 'Room_Ceiling')):
            p.visible_shadow = False          # the sun shines in; only the back wall and floor take shadows
    return parts


def back_wall(coll, x0, x1, y0, y1, wain, mat):
    """The upper back wall in pieces round the window openings."""
    parts = [box('Room_WallBack_Below', coll, x0, x1, y0, y1, wain, WIN_SILL, mat),
             box('Room_WallBack_Above', coll, x0, x1, y0, y1, WIN_TOP, H, mat)]
    edges = [x0] + [e for xc in WIN_XS for e in (xc - WIN_W / 2, xc + WIN_W / 2)] + [x1]
    for i in range(0, len(edges), 2):
        parts.append(box(f'Room_WallBack_Pier{i // 2}', coll, edges[i], edges[i + 1], y0, y1, WIN_SILL, WIN_TOP, mat))
    return parts


def windows(coll):
    white, _ = toon('Room_WindowFrame', (0.66, 0.50, 0.80), (0.80, 0.74, 0.86), rim=0.0)       # violet, as in the original
    sky = sky_material()
    parts = []
    y = WALL_Y - 0.004
    for i, xc in enumerate(WIN_XS):
        x0, x1 = xc - WIN_W / 2, xc + WIN_W / 2
        # the sky hangs outside, behind the opening (seen through it at any camera angle)
        pane = box(f'Room_Sky{i}', coll, x0 - 0.45, x1 + 0.45, WALL_Y + 0.40, WALL_Y + 0.402, WIN_SILL - 0.45, WIN_TOP + 0.45, sky)
        pane.visible_shadow = False
        parts.append(pane)
        f = 0.028     # frame
        for nm, bx in (('L', (x0 - f, x0 + 0.004, WIN_SILL - f, WIN_TOP + f)), ('R', (x1 - 0.004, x1 + f, WIN_SILL - f, WIN_TOP + f)),
                       ('B', (x0 - f, x1 + f, WIN_SILL - f, WIN_SILL + 0.006)), ('T', (x0 - f, x1 + f, WIN_TOP - 0.006, WIN_TOP + f))):
            parts.append(box(f'Room_Win{i}{nm}', coll, bx[0], bx[1], y - 0.025, y, bx[2], bx[3], white, 0.003))
        # a centre post and a transom high up
        m = 0.012
        parts.append(box(f'Room_Win{i}C', coll, xc - m, xc + m, y - 0.02, y, WIN_SILL, WIN_TOP, white))
        zz = WIN_SILL + 0.78 * (WIN_TOP - WIN_SILL)
        parts.append(box(f'Room_Win{i}H', coll, x0, x1, y - 0.02, y, zz - m, zz + m, white))
        # sill ledge
        parts.append(box(f'Room_Win{i}Sill', coll, x0 - 0.05, x1 + 0.05, y - 0.06, y, WIN_SILL - 0.04, WIN_SILL - f, white, 0.004))
    return parts


def curtain_panel(name, coll, x_wall, side, mat, width=0.20, top=1.80, tie=0.95, tie_w=0.07, folds=7):
    """A heavy drape: pleated (sine cross-section), gathered at a tieback, flaring to the floor."""
    nz, nu = 64, 48
    verts, faces = [], []
    y_wall = WALL_Y - 0.03
    for i in range(nz + 1):
        z = 0.0 + (top - 0.0) * i / nz
        # width profile: full at top, pinched at the tieback, flaring out to the floor
        if z >= tie:
            w = tie_w + (width - tie_w) * ((z - tie) / (top - tie)) ** 0.6
        else:
            w = tie_w + (width * 0.95 - tie_w) * ((tie - z) / max(tie, 1e-6)) ** 0.8
        # the drape is pulled sideways toward the wall at the tieback
        for j in range(nu + 1):
            u = j / nu
            x = x_wall + side * u * w
            amp = 0.012 + 0.010 * (w / width)
            dy = amp * math.sin(u * folds * 2 * math.pi) - 0.035 * (1 - abs(2 * u - 1) * 0.3)
            verts.append((x, y_wall + dy, z))
    for i in range(nz):
        for j in range(nu):
            a = i * (nu + 1) + j
            faces.append((a, a + 1, a + nu + 2, a + nu + 1) if side > 0 else (a, a + nu + 1, a + nu + 2, a + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    for p in me.polygons:
        p.use_smooth = True
    o = new_obj(name, me, coll)
    me.materials.append(mat)
    so = o.modifiers.new('Thick', 'SOLIDIFY')
    so.thickness = 0.008
    return o


def curtains(coll):
    drape, dg = toon('Room_Curtain', (0.44, 0.52, 0.49), (0.70, 0.66, 0.78), rim=0.06, thr=0.32)
    gold, _ = toon('Room_Gold', (0.92, 0.70, 0.30), (0.78, 0.58, 0.55), rim=0.2)
    parts = []
    for i, xc in enumerate(WIN_XS):
        for side, x_edge in ((-1, xc - WIN_W / 2 + 0.03), (1, xc + WIN_W / 2 - 0.03)):
            # the panel hangs from just inside the window edge outward over the wall
            p = curtain_panel(f'Room_Curtain{i}{"L" if side < 0 else "R"}', coll, x_edge, side, drape,
                              width=0.26, top=1.86, tie=0.0, tie_w=0.25, folds=8)
            parts.append(p)
            continue
            # gold tieback rope: a torus loop round the gathered drape
            tx = x_edge + side * 0.035
            bpy.ops.mesh.primitive_torus_add(major_radius=0.05, minor_radius=0.007, major_segments=32, minor_segments=8,
                                             location=(tx, WALL_Y - 0.06, 0.95), rotation=(0, math.radians(90), 0))
            t = bpy.context.object
            t.name = f'Room_Tieback{i}{side}'
            t.scale = (1.0, 0.7, 1.0)
            for c in t.users_collection:
                c.objects.unlink(t)
            coll.objects.link(t)
            t.data.materials.append(gold)
            for pp in t.data.polygons:
                pp.use_smooth = True
            parts.append(t)
        continue
        # valance: a gathered pelmet across the top of the window
        x0, x1 = xc - WIN_W / 2 - 0.10, xc + WIN_W / 2 + 0.10
        nu = 80
        verts, faces = [], []
        for j in range(nu + 1):
            u = j / nu
            x = x0 + (x1 - x0) * u
            dy = 0.012 * math.sin(u * 22 * math.pi)
            drop = 0.05 * (0.5 + 0.5 * math.cos(u * 2 * math.pi * 3))   # three soft swags
            verts.append((x, WALL_Y - 0.09 + dy, H - 0.16))
            verts.append((x, WALL_Y - 0.09 + dy, H - 0.33 - drop))
        for j in range(nu):
            a = 2 * j
            faces.append((a, a + 2, a + 3, a + 1))
        me = bpy.data.meshes.new(f'Room_Valance{i}')
        me.from_pydata(verts, [], faces)
        for p in me.polygons:
            p.use_smooth = True
        v = new_obj(f'Room_Valance{i}', me, coll)
        me.materials.append(drape)
        so = v.modifiers.new('Thick', 'SOLIDIFY')
        so.thickness = 0.008
        parts.append(v)
        # gold curtain rod end caps
        parts.append(box(f'Room_Rod{i}', coll, x0 - 0.02, x1 + 0.02, WALL_Y - 0.05, WALL_Y - 0.03, H - 0.20, H - 0.185, gold))
    return parts


# ------------------------------------------------------------------ furniture
def desk(coll):
    x0, x1, y0, y1, top = BED
    wood, _ = toon('Room_DeskWood', (0.24, 0.10, 0.06), (0.74, 0.60, 0.66), rim=0.10)
    brass, _ = toon('Room_Brass', (0.86, 0.62, 0.26), (0.78, 0.58, 0.55), rim=0.25)
    cloth, _ = toon('Room_DeskCloth', (0.40, 0.24, 0.18), (0.76, 0.62, 0.66), rim=0.06)
    parts = []
    parts.append(box('Desk_Top', coll, x0 - 0.02, x1 + 0.02, y0 - 0.02, y1 + 0.02, top - 0.035, top, wood, 0.006))
    parts.append(box('Desk_Apron', coll, x0 + 0.02, x1 - 0.02, y0 + 0.01, y1 - 0.01, top - 0.11, top - 0.035, wood, 0.004))
    # pedestal of drawers on the right, slender legs on the left
    parts.append(box('Desk_Pedestal', coll, x1 - 0.26, x1 - 0.01, y0 + 0.015, y1 - 0.015, 0.03, top - 0.035, wood, 0.006))
    for k in range(3):
        z0 = 0.06 + k * 0.12
        parts.append(box(f'Desk_Drawer{k}', coll, x1 - 0.245, x1 - 0.025, y0 + 0.005, y0 + 0.016, z0, z0 + 0.105, wood, 0.003))
        parts.append(box(f'Desk_Knob{k}', coll, x1 - 0.145, x1 - 0.125, y0 - 0.006, y0 + 0.006, z0 + 0.045, z0 + 0.06, brass, 0.003))
    for xx in (x0 + 0.015, x0 + 0.055):
        pass
    for xx, yy in ((x0 + 0.02, y0 + 0.02), (x0 + 0.02, y1 - 0.02)):
        parts.append(box('Desk_Leg', coll, xx - 0.022, xx + 0.022, yy - 0.022, yy + 0.022, 0.0, top - 0.035, wood, 0.006))
    parts += desk_props(coll, top)
    return parts


def desk_props(coll, top):
    """On the desk, where the dance leaves room (her body, hair and gown checked over the whole
    dance): an open laptop and a green banker's lamp at the back right, a black telephone."""
    parts = []
    shell_m, _ = toon('Room_Laptop', (0.52, 0.50, 0.62), (0.80, 0.76, 0.86), rim=0.15)
    screen_m, _ = toon('Room_LaptopScreen', (0.16, 0.16, 0.22), (0.85, 0.85, 0.9), rim=0.05)
    lx, ly, lyaw = PROPS['laptop']
    base = box('Desk_LaptopBase', coll, -0.085, 0.085, -0.06, 0.06, 0.0, 0.008, shell_m, 0.002)
    lid = box('Desk_LaptopLid', coll, -0.085, 0.085, -0.004, 0.004, 0.0, 0.115, shell_m, 0.002)
    scr = box('Desk_LaptopScreen', coll, -0.078, 0.078, -0.0045, -0.003, 0.008, 0.108, screen_m)
    for o in (lid, scr):
        o.location = (0, 0.058, 0.006)
        o.rotation_euler = (math.radians(-12), 0, 0)
        o.parent = base
    base.location = (lx, ly, top)
    base.rotation_euler = (0, 0, math.radians(lyaw))
    parts += [base, lid, scr]
    green, _ = toon('Room_LampGreen', (0.08, 0.36, 0.20), (0.72, 0.70, 0.80), rim=0.25)
    brass, _ = toon('Room_Brass', (0.86, 0.62, 0.26), (0.78, 0.58, 0.55), rim=0.25)
    bx, by = PROPS['lamp']
    parts.append(box('Desk_LampBase', coll, bx - 0.04, bx + 0.04, by - 0.025, by + 0.025, top, top + 0.012, brass, 0.004))
    parts.append(box('Desk_LampStem', coll, bx - 0.005, bx + 0.005, by - 0.005, by + 0.005, top, top + 0.10, brass))
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.026, depth=0.12, location=(bx, by - 0.01, top + 0.115),
                                        rotation=(0, math.radians(90), 0))
    shade = bpy.context.object
    shade.name = 'Desk_LampShade'
    shade.scale = (1.0, 1.0, 1.0)
    for c in list(shade.users_collection):
        c.objects.unlink(shade)
    coll.objects.link(shade)
    shade.data.materials.append(green)
    for pp in shade.data.polygons:
        pp.use_smooth = True
    parts.append(shade)
    if 'phone' not in PROPS:
        return parts
    black, _ = toon('Room_Phone', (0.04, 0.04, 0.05), (0.85, 0.85, 0.9), rim=0.3)
    px, py = PROPS['phone']
    parts.append(box('Desk_PhoneBase', coll, px - 0.04, px + 0.04, py - 0.045, py + 0.045, top, top + 0.035, black, 0.012, 3, True))
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.012, depth=0.10, location=(px, py, top + 0.05),
                                        rotation=(0, math.radians(90), 0))
    hand = bpy.context.object
    hand.name = 'Desk_PhoneHandset'
    for c in list(hand.users_collection):
        c.objects.unlink(hand)
    coll.objects.link(hand)
    hand.data.materials.append(black)
    parts.append(hand)
    return parts


def door(coll):
    """A glazed wooden double door in the back wall, left of the windows."""
    wood, _ = toon('Room_DoorWood', (0.46, 0.24, 0.10), (0.76, 0.62, 0.64), rim=0.1)
    glass, _ = toon('Room_DoorGlass', (0.98, 0.82, 0.46), (0.95, 0.85, 0.7), rim=0.0)
    y = WALL_Y - 0.005
    parts = []
    x0, x1 = DOOR_X - DOOR_W / 2, DOOR_X + DOOR_W / 2
    parts.append(box('Room_DoorFrame', coll, x0 - 0.05, x1 + 0.05, y - 0.03, y, 0.0, DOOR_H + 0.07, wood, 0.006))
    for k, (a, b) in enumerate(((x0, DOOR_X - 0.004), (DOOR_X + 0.004, x1))):
        parts.append(box(f'Room_DoorLeaf{k}', coll, a, b, y - 0.045, y - 0.03, 0.0, DOOR_H, wood, 0.004))
        for r in range(3):
            z0 = 0.62 + r * 0.29
            parts.append(box(f'Room_DoorPane{k}{r}', coll, a + 0.05, b - 0.05, y - 0.05, y - 0.044, z0, z0 + 0.24, glass))
        parts.append(box(f'Room_DoorPanel{k}', coll, a + 0.05, b - 0.05, y - 0.05, y - 0.044, 0.08, 0.52, wood, 0.004))
        hx = b - 0.04 if k == 0 else a + 0.04
        parts.append(box(f'Room_DoorKnob{k}', coll, hx - 0.01, hx + 0.01, y - 0.07, y - 0.045, 0.74, 0.76, glass))
    return parts


def plant(coll):
    """A tall potted plant with long arching leaves."""
    pot_m, _ = toon('Room_Pot', (0.70, 0.66, 0.60), (0.78, 0.72, 0.76), rim=0.1)
    leaf_m, _ = toon('Room_Leaf', (0.16, 0.40, 0.14), (0.62, 0.70, 0.66), rim=0.15, thr=0.35)
    leaf_m.use_backface_culling = False
    x, y = PLANT_XY
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=0.13, depth=0.34, location=(x, y, 0.17))
    pot = bpy.context.object
    pot.name = 'Room_Pot'
    for c in list(pot.users_collection):
        c.objects.unlink(pot)
    coll.objects.link(pot)
    pot.data.materials.append(pot_m)
    for pp in pot.data.polygons:
        pp.use_smooth = True
    parts.append(pot)
    rng = np.random.default_rng(7)
    verts, faces = [], []
    for k in range(26):
        az = rng.uniform(0, 2 * math.pi)
        lean = rng.uniform(0.15, 0.9)
        length = rng.uniform(0.55, 1.05)
        width = rng.uniform(0.035, 0.06)
        n = 14
        base_i = len(verts)
        d = Vector((math.cos(az), math.sin(az), 0))
        side = Vector((-math.sin(az), math.cos(az), 0))
        for j in range(n + 1):
            t = j / n
            # rises, then arches over and droops at the tip
            r = length * t * math.sin(lean) * (0.6 + 0.4 * t)
            z = 0.32 + length * (math.cos(lean) * t - 0.55 * t * t * math.sin(lean))
            w = width * math.sin(math.pi * min(t * 1.15, 1.0)) + 0.002
            c = Vector((x, y, 0)) + d * r + Vector((0, 0, z))
            verts += [tuple(c - side * w), tuple(c + side * w)]
            if j:
                a = base_i + 2 * (j - 1)
                faces.append((a, a + 1, a + 3, a + 2))
    me = bpy.data.meshes.new('Room_PlantLeaves')
    me.from_pydata(verts, [], faces)
    for pp in me.polygons:
        pp.use_smooth = True
    leaves = new_obj('Room_PlantLeaves', me, coll)
    me.materials.append(leaf_m)
    parts.append(leaves)
    return parts


def chair(coll, x=0.20, y=0.44):
    wood, _ = toon('Room_ChairWood', (0.22, 0.08, 0.05), (0.74, 0.60, 0.66), rim=0.12)
    red, _ = toon('Room_ChairRed', (0.62, 0.08, 0.10), (0.72, 0.50, 0.58), rim=0.12, thr=0.32)
    parts = []
    seat = 0.28
    parts.append(box('Chair_Seat', coll, x - 0.13, x + 0.13, y - 0.12, y + 0.12, seat - 0.03, seat + 0.025, red, 0.02, 4, True))
    parts.append(box('Chair_SeatFrame', coll, x - 0.135, x + 0.135, y - 0.125, y + 0.125, seat - 0.05, seat - 0.025, wood, 0.006))
    for dx in (-0.11, 0.11):
        for dy in (-0.10, 0.10):
            parts.append(box('Chair_Leg', coll, x + dx - 0.016, x + dx + 0.016, y + dy - 0.016, y + dy + 0.016, 0.0, seat - 0.05, wood, 0.006))
    # high back: wooden frame with an upholstered oval panel
    for dx in (-0.11, 0.11):
        parts.append(box('Chair_Post', coll, x + dx - 0.015, x + dx + 0.015, y + 0.10, y + 0.13, seat, seat + 0.36, wood, 0.006))
    parts.append(box('Chair_Crest', coll, x - 0.13, x + 0.13, y + 0.10, y + 0.135, seat + 0.33, seat + 0.38, wood, 0.012, 3))
    parts.append(box('Chair_BackPad', coll, x - 0.095, x + 0.095, y + 0.095, y + 0.125, seat + 0.05, seat + 0.32, red, 0.02, 4, True))
    return parts


def sofa(coll):
    x0, x1, y0, y1, seat = SOFA
    green, _ = toon('Room_SofaGreen', (0.10, 0.26, 0.14), (0.66, 0.64, 0.74), rim=0.12, thr=0.30)
    trim, _ = toon('Room_SofaTrim', (0.80, 0.62, 0.28), (0.78, 0.58, 0.55), rim=0.2)
    wood, _ = toon('Room_SofaWood', (0.20, 0.08, 0.05), (0.74, 0.60, 0.66))
    parts = []
    back_y = y1 + 0.12
    parts.append(box('Sofa_Base', coll, x0 - 0.10, x1 + 0.10, y0, back_y, 0.06, seat - 0.08, green, 0.02, 3, True))
    parts.append(box('Sofa_Cushion', coll, x0, x1, y0 - 0.01, y1, seat - 0.09, seat, green, 0.035, 5, True))
    parts.append(box('Sofa_Back', coll, x0 - 0.10, x1 + 0.10, y1, back_y, seat - 0.08, seat + 0.30, green, 0.05, 5, True))
    for xa in (x0 - 0.10, x1):
        parts.append(box('Sofa_Arm', coll, xa, xa + 0.10, y0, back_y, seat - 0.08, seat + 0.13, green, 0.045, 5, True))
    # gold piping along the seat front and the arm tops
    parts.append(box('Sofa_Piping', coll, x0 - 0.10, x1 + 0.10, y0 - 0.004, y0 + 0.004, seat - 0.10, seat - 0.092, trim))
    for xx in (x0 - 0.08, x1 + 0.08):
        for yy in (y0 + 0.03, back_y - 0.03):
            parts.append(box('Sofa_Foot', coll, xx - 0.02, xx + 0.02, yy - 0.02, yy + 0.02, 0.0, 0.06, wood, 0.006))
    # loose cushions on the right end, clear of where she sits
    for k, (cxp, rot) in enumerate(((x1 - 0.16, -12), (x1 - 0.36, 8))):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(cxp, y1 + 0.02, seat + 0.13), rotation=(math.radians(-14), 0, math.radians(rot)))
        c = bpy.context.object
        c.name = f'Sofa_Pillow{k}'
        c.scale = (0.20, 0.07, 0.20)
        bv = c.modifiers.new('Bevel', 'BEVEL')
        bv.width = 0.04
        bv.segments = 5
        sd = c.modifiers.new('Sub', 'SUBSURF')
        sd.levels = sd.render_levels = 2
        for cc in c.users_collection:
            cc.objects.unlink(c)
        coll.objects.link(c)
        c.data.materials.append(green)
        for pp in c.data.polygons:
            pp.use_smooth = True
        parts.append(c)
    return parts


def build(coll, cfg):
    _place(cfg)
    if bpy.data.node_groups.get('Room_Shade'):        # rebuilt with the materials (stage re-runs)
        bpy.data.node_groups.remove(bpy.data.node_groups['Room_Shade'])
    parts = shell(coll) + windows(coll) + curtains(coll) + desk(coll) + sofa(coll) + door(coll) + plant(coll)
    for p in parts:
        if p.name.startswith(('Desk_', 'Sofa_', 'Room_Curtain', 'Room_Door', 'Room_Pot', 'Room_PlantLeaves')) and p.type == 'MESH':
            outline(p, 0.003)
    return parts


# ------------------------------------------------------------------ light
# The afternoon sun comes in through the back windows: it casts the window panes, curtains and
# her shadow across the floor, lights her from behind and shows as beams in a light haze. Over
# the song it sinks and warms, and its strength follows the music (from the song's loudness):
# a quiet intro on the desk, the band coming in at ~300, a breakdown round the sofa (1230-1450),
# the long chorus run, a last peak at ~2450-2560 and the outro at sunset.
#   frame, elevation, azimuth (deg; + = from her right), energy, colour (K), haze density (by the windows),
#   sunlit gain, grade (rgb), rim
CUES = [
    (0,    40, -16, 3.3, 5400, 0.050, 1.10, (0.96, 0.98, 1.04), 0.75),
    (285,  40, -16, 3.3, 5400, 0.050, 1.10, (0.96, 0.98, 1.04), 0.75),
    (340,  38, -14, 5.4, 5000, 0.090, 1.22, (1.00, 1.00, 1.00), 1.00),
    (1200, 34, -8, 5.7, 4700, 0.100, 1.24, (1.00, 0.99, 0.98), 1.00),
    (1265, 33, -6, 3.9, 4300, 0.120, 1.16, (1.02, 0.97, 0.95), 0.85),
    (1430, 32, -4, 3.9, 4200, 0.120, 1.16, (1.02, 0.97, 0.95), 0.85),
    (1500, 31, -2, 6.0, 4300, 0.100, 1.28, (1.01, 0.99, 0.96), 1.15),
    (2170, 28, 4, 6.0, 3900, 0.110, 1.28, (1.02, 0.98, 0.94), 1.15),
    (2235, 27, 5, 4.5, 3800, 0.130, 1.20, (1.02, 0.97, 0.93), 0.95),
    (2450, 25, 8, 6.9, 3400, 0.150, 1.34, (1.04, 0.96, 0.89), 1.30),
    (2560, 24, 9, 6.6, 3200, 0.150, 1.32, (1.04, 0.95, 0.88), 1.25),
    (2620, 23, 10, 4.8, 2900, 0.130, 1.24, (1.05, 0.93, 0.87), 1.05),
    (2755, 22, 11, 4.2, 2700, 0.120, 1.20, (1.05, 0.92, 0.86), 1.00),
]


def kelvin(t):
    """Blackbody colour (linear RGB, max 1) of a temperature in kelvin (fit by Tanner Helland)."""
    t = t / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = srgb(tuple(min(max(v, 0.0), 255.0) / 255.0 for v in (r, g, b)))
    return tuple(v / max(c) for v in c)


def sun_rotation(elev, az):
    """A sun shining from behind the back wall: elevation and azimuth in degrees."""
    el, a = math.radians(elev), math.radians(az)
    d = Vector((math.sin(a) * math.cos(el), -math.cos(a) * math.cos(el), -math.sin(el)))
    return d.to_track_quat('-Z', 'Y').to_euler()


def keyed(socket, frame, value):
    socket.default_value = value
    socket.keyframe_insert('default_value', frame=frame)


def toon_light_terms():
    """Add a sunlit tone, a grade and a rim multiplier to the shared AIG_Toon group.

    Where the light is much stronger than the key alone gives (the window sun), the toon colour
    turns brighter and takes the sun's colour; the face keeps its clean driver shading (its
    `Sun Band` input is 0). The grade tints the whole picture and follows the time of day.
    Returns the animated nodes. Re-running starts again from the group as the character file
    had it (kept as AIG_Toon_base), so the stage can be rebuilt on a built scene."""
    nt = bpy.data.node_groups['AIG_Toon']
    base = bpy.data.node_groups.get('AIG_Toon_base')
    if base is None:
        base = nt.copy()
        base.name = 'AIG_Toon_base'
        base.use_fake_user = True
    else:
        fresh = base.copy()
        nt.user_remap(fresh)
        bpy.data.node_groups.remove(nt)
        fresh.name = 'AIG_Toon'
        nt = fresh
    N = nt.nodes
    if 'Sun Band' not in [i.name for i in nt.interface.items_tree]:
        s = nt.interface.new_socket('Sun Band', in_out='INPUT', socket_type='NodeSocketFloat')
        s.default_value = 1.0
    gin = next(n for n in N if n.bl_idname == 'NodeGroupInput')
    emis = next(n for n in N if n.bl_idname == 'ShaderNodeEmission')
    bw = next(n for n in N if n.bl_idname == 'ShaderNodeRGBToBW')
    toon_col = emis.inputs['Color'].links[0].from_socket
    rim_mul = N.new('ShaderNodeValue')
    rim_mul.name = rim_mul.label = 'Light_RimMul'
    rim_target = next(l.to_socket for l in nt.links if l.from_node == gin and l.from_socket.name == 'Rim Strength')
    link(nt, math_node(nt, 'MULTIPLY', gin.outputs['Rim Strength'], rim_mul.outputs[0]), rim_target)
    # sunlit band: a smooth step of the raw light level above what the key + ambient reach
    band = N.new('ShaderNodeMapRange')
    band.interpolation_type = 'SMOOTHSTEP'
    band.inputs['From Min'].default_value = 1.30
    band.inputs['From Max'].default_value = 1.55
    link(nt, bw.outputs['Val'], band.inputs['Value'])
    fac = math_node(nt, 'MULTIPLY', band.outputs['Result'], gin.outputs['Sun Band'])
    tint = N.new('ShaderNodeRGB')
    tint.name = tint.label = 'Light_SunTint'
    gain = N.new('ShaderNodeValue')
    gain.name = gain.label = 'Light_SunGain'
    sunlit = mix_rgb(nt, 1.0, toon_col, tint.outputs[0], 'MULTIPLY')
    sc = N.new('ShaderNodeVectorMath')
    sc.operation = 'SCALE'
    link(nt, sunlit, sc.inputs[0])
    link(nt, gain.outputs[0], sc.inputs['Scale'])
    lit = mix_rgb(nt, fac, toon_col, sc.outputs[0])
    grade = N.new('ShaderNodeRGB')
    grade.name = grade.label = 'Light_Grade'
    link(nt, mix_rgb(nt, 1.0, lit, grade.outputs[0], 'MULTIPLY'), emis.inputs['Color'])
    return dict(tint=tint, gain=gain, grade=grade, rim=rim_mul)


def haze(coll):
    """Thin haze filling the room: the sunbeams show in it."""
    m = bpy.data.materials.get('Room_Haze') or bpy.data.materials.new('Room_Haze')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    sc = nt.nodes.new('ShaderNodeVolumeScatter')
    sc.inputs['Color'].default_value = (1.0, 0.97, 0.93, 1)
    sc.inputs['Anisotropy'].default_value = 0.55
    link(nt, sc.outputs[0], out.inputs['Volume'])
    # thickest by the windows, clearing toward the camera side of the room
    dens = nt.nodes.new('ShaderNodeValue')
    dens.name = dens.label = 'Haze_Density'
    sep = tex_coord_nodes(nt)
    fall = nt.nodes.new('ShaderNodeMapRange')
    fall.interpolation_type = 'SMOOTHSTEP'
    fall.inputs['From Min'].default_value = -2.2
    fall.inputs['From Max'].default_value = 0.4
    fall.inputs['To Min'].default_value = 0.12
    link(nt, sep.outputs['Y'], fall.inputs['Value'])
    link(nt, math_node(nt, 'MULTIPLY', fall.outputs['Result'], dens.outputs[0]), sc.inputs['Density'])
    o = box('Room_Haze', coll, WALL_X0 + 0.01, WALL_X1 - 0.01, FRONT_Y + 0.01, WALL_Y - 0.01, 0.002, H - 0.01, m)
    o.visible_shadow = False
    return o, dens.outputs[0]


def finish(coll, cfg):
    """Light the room from its windows (called by the stage after the lights and render settings)."""
    terms = toon_light_terms()
    face = bpy.data.materials.get(cfg.face.atlas.material) if cfg.face.atlas.material else None
    if face is not None:
        for n in face.node_tree.nodes:
            if n.bl_idname == 'ShaderNodeGroup' and n.node_tree and n.node_tree.name == 'AIG_Toon':
                n.inputs['Sun Band'].default_value = 0.0
    bpy.data.objects[cfg.stage.sun].data.volume_factor = 0.0      # the key lights her, not the haze
    for name in ('Room_WindowSun',):
        if bpy.data.lights.get(name):
            bpy.data.lights.remove(bpy.data.lights[name])
    ld = bpy.data.lights.new('Room_WindowSun', 'SUN')
    sun = bpy.data.objects.new('Room_WindowSun', ld)
    coll.objects.link(sun)
    ld.angle = math.radians(1.2)
    ld.use_shadow = True
    _, scatter = haze(coll)
    room_grade = room_shade_group().nodes['Light_Grade']
    sky = bpy.data.materials['Room_Sky'].node_tree.nodes.get('Emission')
    for f, el, az, en, kv, dens, gain, grade, rim in CUES:
        col = kelvin(kv)
        sun.rotation_euler = sun_rotation(el, az)
        sun.keyframe_insert('rotation_euler', frame=f)
        ld.energy = en
        ld.keyframe_insert('energy', frame=f)
        ld.color = col
        ld.keyframe_insert('color', frame=f)
        keyed(scatter, f, dens)
        keyed(room_grade.outputs[0], f, tuple(grade) + (1,))
        keyed(terms['tint'].outputs[0], f, tuple(0.55 + 0.45 * c for c in col) + (1,))
        keyed(terms['gain'].outputs[0], f, gain)
        keyed(terms['grade'].outputs[0], f, tuple(grade) + (1,))
        keyed(terms['rim'].outputs[0], f, rim)
        if sky is not None:
            keyed(sky.inputs['Strength'], f, 1.9 + 0.08 * en)
    e = bpy.context.scene.eevee
    e.volumetric_tile_size = '2'
    e.volumetric_samples = 64
    e.volumetric_start = 0.05
    e.volumetric_end = 12.0
    print('[stage] window sun, haze and toon light terms set')
