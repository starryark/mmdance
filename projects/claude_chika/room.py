"""The student-council room from the original video (akomni, sm34597101), rebuilt as our own geometry.

Wood-panelled walls with a pink wainscot, tall white-framed windows onto a blue sky, dark maroon
curtains gathered with gold tiebacks under a valance, a dark cornice, a red/pink harlequin floor,
a dark writing desk with a diagonal cloth, brass lamp and books, a red upholstered chair behind it
and a green chesterfield sofa. Scaled to the character (1 m tall); the desk is the collider the
dance lies on, the sofa the one she sits on.

A project stage builder for mmdance (stage.builder = "room.py"): build(collection, cfg) makes the
set, colliders(cfg) gives the desk and sofa boxes to the cloth/hair simulation. The desk and sofa
placement come from [stage] desk / sofa in project.toml. Materials use the character's AIG_Toon
toon shader group, so this builder needs a character file that has it.
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


def _place(cfg):
    global BED, SOFA
    BED = tuple(cfg.stage.get('desk', BED))
    SOFA = tuple(cfg.stage.get('sofa', SOFA))


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
WIN_SILL, WIN_TOP, WIN_W = 0.62, 1.60, 0.46
WIN_XS = [0.20 + 0.96 * k for k in range(-3, 4)]


def srgb(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def link(nt, a, b):
    nt.links.new(a, b)


def toon(name, base, shadow, rim=0.05, thr=0.30, base_socket=None):
    """Toon material driven by the character's AIG_Toon group. Returns (material, group node)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    g = nt.nodes.new('ShaderNodeGroup')
    g.node_tree = bpy.data.node_groups['AIG_Toon']
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
    ramp.color_ramp.elements[0].color = srgb((0.82, 0.96, 1.0)) + (1,)
    ramp.color_ramp.elements[1].color = srgb((0.30, 0.78, 0.96)) + (1,)
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
    em.inputs['Strength'].default_value = 1.6
    link(nt, col, em.inputs['Color'])
    link(nt, em.outputs[0], out.inputs['Surface'])
    return m


# ------------------------------------------------------------------ room shell
def shell(coll):
    wood = plank_material('Room_WallWood', (0.84, 0.54, 0.40), (0.62, 0.34, 0.24), (0.80, 0.62, 0.66), 0.075)
    wains = plank_material('Room_Wainscot', (0.86, 0.48, 0.52), (0.62, 0.26, 0.32), (0.80, 0.62, 0.70), 0.05)
    dark, _ = toon('Room_DarkWood', (0.20, 0.08, 0.06), (0.75, 0.62, 0.66))
    ceil, _ = toon('Room_Ceiling', (0.16, 0.07, 0.06), (0.9, 0.85, 0.85))
    floor_m = harlequin_material()
    WAIN = 0.36
    parts = []
    # floor
    parts.append(box('Room_Floor', coll, WALL_X0, WALL_X1, FRONT_Y, WALL_Y, -0.02, 0.0, floor_m))
    # walls: back, left, right, front (the front one is behind the camera)
    walls = [('Back', (WALL_X0, WALL_X1, WALL_Y, WALL_Y + 0.05)), ('Left', (WALL_X0 - 0.05, WALL_X0, FRONT_Y, WALL_Y)),
             ('Right', (WALL_X1, WALL_X1 + 0.05, FRONT_Y, WALL_Y)), ('Front', (WALL_X0, WALL_X1, FRONT_Y - 0.05, FRONT_Y))]
    for nm, (x0, x1, y0, y1) in walls:
        parts.append(box(f'Room_Wall{nm}_Upper', coll, x0, x1, y0, y1, WAIN, H, wood))
        parts.append(box(f'Room_Wall{nm}_Wainscot', coll, x0, x1, y0, y1, 0.0, WAIN, wains))
    # trims on the back wall: baseboard, chair rail, cornice band
    yb = WALL_Y - 0.012
    parts.append(box('Room_Baseboard', coll, WALL_X0, WALL_X1, yb - 0.01, WALL_Y, 0.0, 0.05, dark, 0.004))
    parts.append(box('Room_ChairRail', coll, WALL_X0, WALL_X1, yb - 0.014, WALL_Y, WAIN - 0.012, WAIN + 0.016, dark, 0.004))
    parts.append(box('Room_Cornice', coll, WALL_X0, WALL_X1, yb - 0.09, WALL_Y, H - 0.16, H, dark, 0.006))
    parts.append(box('Room_Ceiling', coll, WALL_X0, WALL_X1, FRONT_Y, WALL_Y, H, H + 0.03, ceil))
    # vertical pilasters between the windows
    for i in range(len(WIN_XS) - 1):
        xm = (WIN_XS[i] + WIN_XS[i + 1]) / 2
        parts.append(box(f'Room_Pilaster{i}', coll, xm - 0.03, xm + 0.03, yb - 0.02, WALL_Y, WAIN + 0.016, H - 0.16, dark, 0.004))
    for p in parts:
        if p.name.startswith(('Room_WallFront', 'Room_WallLeft', 'Room_WallRight', 'Room_Ceiling')):
            p.visible_shadow = False          # the sun shines in; only the back wall and floor take shadows
    return parts


def windows(coll):
    white, _ = toon('Room_WindowFrame', (0.96, 0.95, 0.93), (0.80, 0.76, 0.82), rim=0.0)
    sky = sky_material()
    parts = []
    y = WALL_Y - 0.004
    for i, xc in enumerate(WIN_XS):
        x0, x1 = xc - WIN_W / 2, xc + WIN_W / 2
        pane = box(f'Room_Sky{i}', coll, x0, x1, y - 0.002, y, WIN_SILL, WIN_TOP, sky)
        pane.visible_shadow = False
        parts.append(pane)
        f = 0.028     # frame
        for nm, bx in (('L', (x0 - f, x0 + 0.004, WIN_SILL - f, WIN_TOP + f)), ('R', (x1 - 0.004, x1 + f, WIN_SILL - f, WIN_TOP + f)),
                       ('B', (x0 - f, x1 + f, WIN_SILL - f, WIN_SILL + 0.006)), ('T', (x0 - f, x1 + f, WIN_TOP - 0.006, WIN_TOP + f))):
            parts.append(box(f'Room_Win{i}{nm}', coll, bx[0], bx[1], y - 0.025, y, bx[2], bx[3], white, 0.003))
        # muntins: centre post, transom at 2/3 height, glazing bars
        m = 0.007
        parts.append(box(f'Room_Win{i}C', coll, xc - m, xc + m, y - 0.018, y, WIN_SILL, WIN_TOP, white))
        for zz in np.linspace(WIN_SILL, WIN_TOP, 5)[1:-1]:
            parts.append(box(f'Room_Win{i}H{zz:.2f}', coll, x0, x1, y - 0.016, y, zz - m * 0.8, zz + m * 0.8, white))
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
            w = tie_w + (width * 0.95 - tie_w) * ((tie - z) / tie) ** 0.8
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
    drape, dg = toon('Room_Curtain', (0.30, 0.06, 0.07), (0.70, 0.52, 0.62), rim=0.08, thr=0.32)
    gold, _ = toon('Room_Gold', (0.92, 0.70, 0.30), (0.78, 0.58, 0.55), rim=0.2)
    parts = []
    for i, xc in enumerate(WIN_XS):
        for side, x_edge in ((-1, xc - WIN_W / 2 + 0.03), (1, xc + WIN_W / 2 - 0.03)):
            # the panel hangs from just inside the window edge outward over the wall
            p = curtain_panel(f'Room_Curtain{i}{"L" if side < 0 else "R"}', coll, x_edge, side, drape)
            parts.append(p)
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
    # diagonal table cloth: a square turned 45 degrees, its corners draped over the front and back
    n = 60
    side = 0.62
    cx, cy = (x0 + x1) / 2 - 0.05, (y0 + y1) / 2
    verts, faces = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = (i / n - 0.5) * side, (j / n - 0.5) * side
            x = cx + (u - v) * 0.7071
            y = cy + (u + v) * 0.7071
            z = top + 0.002
            over = max(y0 - y, y - y1, 0.0)
            ox = max(x0 - x, x - x1, 0.0)
            ov = max(over, ox)
            if ov > 0:
                z -= ov
                y = min(max(y, y0 - 0.006), y1 + 0.006)
                x = min(max(x, x0 - 0.006), x1 + 0.006)
            verts.append((x, y, z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + 1, a + n + 2, a + n + 1))
    me = bpy.data.meshes.new('Desk_Cloth')
    me.from_pydata(verts, [], faces)
    for p in me.polygons:
        p.use_smooth = True
    c = new_obj('Desk_Cloth', me, coll)
    me.materials.append(cloth)
    so = c.modifiers.new('Thick', 'SOLIDIFY')
    so.thickness = 0.003
    parts.append(c)
    # brass lamp with a cream shade, books, a white dish
    lx, ly = x1 - 0.08, y1 - 0.08
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.045, depth=0.012, location=(lx, ly, top + 0.006))
    parts.append(bpy.context.object)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.007, depth=0.30, location=(lx, ly, top + 0.15))
    parts.append(bpy.context.object)
    arm_end = Vector((lx - 0.10, ly - 0.03, top + 0.29))
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.006, depth=0.12, location=((lx + arm_end.x) / 2, (ly + arm_end.y) / 2, top + 0.30),
                                        rotation=(0, math.radians(80), math.radians(15)))
    parts.append(bpy.context.object)
    for p in parts[-3:]:
        p.data.materials.append(brass)
    shade_m, _ = toon('Room_LampShade', (0.98, 0.88, 0.66), (0.86, 0.76, 0.66), rim=0.1)
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=0.075, radius2=0.025, depth=0.075, location=(arm_end.x, arm_end.y, top + 0.265),
                                    rotation=(0, math.radians(-12), 0))
    sh = bpy.context.object
    sh.data.materials.append(shade_m)
    parts.append(sh)
    book_cols = [(0.20, 0.26, 0.48), (0.48, 0.14, 0.14), (0.18, 0.30, 0.48), (0.40, 0.20, 0.10)]
    bx = x1 + 0.01
    for k, col in enumerate(book_cols):
        bm_, _ = toon(f'Room_Book{k}', col, (0.76, 0.62, 0.66), rim=0.05)
        w = 0.022 + 0.004 * (k % 2)
        parts.append(box(f'Desk_Book{k}', coll, bx - 0.13, bx - 0.13 + 0.10, y1 - 0.18 + k * 0.026, y1 - 0.18 + k * 0.026 + w,
                         top, top + 0.15 - 0.012 * k, bm_, 0.003))
    white, _ = toon('Room_Porcelain', (0.97, 0.96, 0.95), (0.80, 0.78, 0.86), rim=0.15)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.06, location=(x1 - 0.30, y1 - 0.10, top + 0.012))
    dish = bpy.context.object
    dish.scale = (1.0, 1.0, 0.28)
    dish.data.materials.append(white)
    parts.append(dish)
    for p in parts:
        for cc in p.users_collection:
            if cc is not coll:
                cc.objects.unlink(p)
        if coll not in p.users_collection:
            coll.objects.link(p)
        if p.type == 'MESH':
            for pp in p.data.polygons:
                pp.use_smooth = True
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
    parts = shell(coll) + windows(coll) + curtains(coll) + desk(coll) + chair(coll) + sofa(coll)
    for p in parts:
        if p.name.startswith(('Desk_', 'Chair_', 'Sofa_', 'Room_Curtain', 'Room_Valance', 'Room_Tieback')) and p.type == 'MESH':
            outline(p, 0.003)
    return parts
