"""Stage: facial animation from the VMD morph track.

mode = "atlas": for a painted face texture. The face material composites expression tiles
  (per eye: blink 1/3, blink 2/3, closed, smile ^^; mouth: a/i/u/e/o at three openings, wa x2,
  smirk) from two atlases (made by face_atlas.py) over the base painting. The tile per region is
  an integer object property on the body (face_eyeL / face_eyeR / face_mouth), keyed per frame.
mode = "shapekeys": VMD morph weights drive shape keys directly (face.shapekeys.map).
"""
import json
import os
import subprocess

import bpy
import numpy as np

from . import config, vmd
from .util import new_action, put_curve, rig_and_body

HERE = os.path.dirname(os.path.abspath(__file__))


def facial_vmd(cfg):
    return cfg.path('face.vmd') if cfg.face.vmd else cfg.path('motion.vmd')


def morph_curves(cfg, names):
    """Per-frame weights (linear interpolation between VMD morph keys)."""
    v = vmd.read_vmd(facial_vmd(cfg))
    f0, f1 = cfg.project.frame_start, cfg.project.frame_end
    out = {}
    for n in names:
        keys = sorted((f, w) for m, f, w in v['morphs'] if m == n)
        if not keys:
            out[n] = np.zeros(f1 - f0 + 1)
            continue
        fr = np.array([k[0] for k in keys], float)
        ws = np.array([k[1] for k in keys], float)
        out[n] = np.interp(np.arange(f0, f1 + 1), fr, ws)
    return out


def states(cfg, w, nf):
    mo = cfg.face.morphs
    # atlas 'L' = image-left eye = the character's RIGHT eye
    blink = w[mo.blink]
    close_L = np.maximum(blink, w[mo.wink_right])
    close_R = np.maximum(blink, w[mo.wink_left])
    smile = w[mo.smile]

    def eye(close, base):
        # tiles per eye: 0 open, 1 blink 1/3, 2 blink 2/3, 3 closed, 4 smile ^^
        s = np.zeros(nf, int)
        s[close >= 0.2] = 1
        s[close >= 0.5] = 2
        s[close >= 0.8] = 3
        s[(smile >= 0.5) & (close < 0.8)] = 4
        return s + base
    eL, eR = eye(close_L, 0), eye(close_R, 5)
    vow = np.stack([w[mo.a], w[mo.i], w[mo.u], w[mo.e], w[mo.o]])
    vi = vow.argmax(0)
    vw = vow.max(0)
    mouth = np.zeros(nf, int)
    lvl = np.where(vw < 0.4, 1, np.where(vw < 0.7, 2, 3))
    talking = vw >= 0.12
    mouth[talking] = 1 + vi[talking] * 3 + (lvl[talking] - 1)
    wa = w[mo.wa]
    big = (wa >= 0.3) & (wa >= vw)
    mouth[big] = np.where(wa[big] < 0.7, 16, 17)
    smirk = (w[mo.smirk] >= 0.5) & ~talking & ~big
    mouth[smirk] = 18
    return eL, eR, mouth


def min_hold(a, hold=2):
    """Replace state runs shorter than `hold` frames with the preceding state (no 1-frame flicker)."""
    a = a.copy()
    fixed = 0
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and a[j + 1] == a[i]:
            j += 1
        if j - i + 1 < hold and i > 0:
            a[i:j + 1] = a[i - 1]
            fixed += 1
        i = j + 1
    return a, fixed


def face_nodes(cfg, mat):
    """(uv node, base image node, shader node, shader input name) of the face material."""
    fa = cfg.face.atlas
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    inp = fa.shader_input
    found = mat.get('mmdance_face_nodes')          # remembered once the expression nodes are in
    if found:
        return nodes[found[0]], nodes[found[1]], nodes[found[2]], inp
    if fa.shader_node:
        shader = nodes[fa.shader_node]
    else:
        shader = next(n for n in nodes if inp in n.inputs and n.inputs[inp].is_linked)
    if fa.base_node:
        base = nodes[fa.base_node]
    else:
        base = shader.inputs[inp].links[0].from_node
        if base.bl_idname != 'ShaderNodeTexImage':
            raise RuntimeError(f'face.atlas: {mat.name}: {inp} is not fed by an image node; set face.atlas.base_node')
    if fa.uv_node:
        uvn = nodes[fa.uv_node]
    else:
        uvn = next((n for n in nodes if n.bl_idname == 'ShaderNodeUVMap'), None)
        if uvn is None:
            uvn = nodes.new('ShaderNodeUVMap')
            uvn.name = 'FX_UV'
            links.new(uvn.outputs['UV'], base.inputs['Vector'])
    return uvn, base, shader, inp


def build_shader(cfg, mat, meta, eyes_img, mouth_img):
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    for n in list(nodes):
        if n.name.startswith('FX_') and n.name != 'FX_UV':
            nodes.remove(n)
    uvn, base, shader, inp = face_nodes(cfg, mat)
    S = float(meta['size'])

    def node(kind, name, loc, **kw):
        n = nodes.new(kind)
        n.name = n.label = 'FX_' + name
        n.location = loc
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    sep = node('ShaderNodeSeparateXYZ', 'uvsep', (-900, -400))
    links.new(uvn.outputs['UV'], sep.inputs[0])
    current = base.outputs['Color']

    def math(op, a, b, name, loc):
        m = node('ShaderNodeMath', name, loc, operation=op)
        for i, v in enumerate((a, b)):
            if hasattr(v, 'is_linked') or hasattr(v, 'node'):
                links.new(v, m.inputs[i])
            else:
                m.inputs[i].default_value = v
        return m.outputs[0]

    def region(tag, rect, prop, img, cols, rows, tile_px, color_in, yloc, none_mod):
        x0, y0, x1, y1 = rect
        u0, u1 = x0 / S, x1 / S
        vt, vb = 1 - y0 / S, 1 - y1 / S
        lx = math('DIVIDE', math('SUBTRACT', sep.outputs['X'], u0, tag + 'sx', (-700, yloc)), u1 - u0, tag + 'lx', (-550, yloc))
        ly = math('DIVIDE', math('SUBTRACT', vt, sep.outputs['Y'], tag + 'sy', (-700, yloc - 60)), vt - vb, tag + 'ly', (-550, yloc - 60))
        attr = node('ShaderNodeAttribute', tag + 'attr', (-900, yloc - 160), attribute_type='OBJECT', attribute_name=prop)
        t = attr.outputs['Fac']
        col = math('FLOORED_MODULO', t, cols, tag + 'col', (-700, yloc - 160))
        row = math('FLOOR', math('DIVIDE', t, cols, tag + 'rdiv', (-700, yloc - 220)), 0, tag + 'row', (-550, yloc - 220))
        W, H = tile_px
        au = math('DIVIDE', math('ADD', math('MULTIPLY', col, W, tag + 'cw', (-400, yloc - 160)),
                                  math('MULTIPLY', lx, x1 - x0, tag + 'lxp', (-400, yloc)), tag + 'aup', (-250, yloc)),
                  cols * W, tag + 'au', (-100, yloc))
        av_top = math('DIVIDE', math('ADD', math('MULTIPLY', row, H, tag + 'rh', (-400, yloc - 220)),
                                      math('MULTIPLY', ly, y1 - y0, tag + 'lyp', (-400, yloc - 60)), tag + 'avp', (-250, yloc - 60)),
                      rows * H, tag + 'avt', (-100, yloc - 60))
        av = math('SUBTRACT', 1.0, av_top, tag + 'av', (50, yloc - 60))
        comb = node('ShaderNodeCombineXYZ', tag + 'uv', (200, yloc))
        links.new(au, comb.inputs[0])
        links.new(av, comb.inputs[1])
        tex = node('ShaderNodeTexImage', tag + 'atlas', (350, yloc), image=img, interpolation='Linear', extension='CLIP')
        links.new(comb.outputs[0], tex.inputs['Vector'])
        # inside the region and a tile selected
        inx = math('MULTIPLY', math('GREATER_THAN', lx, 0.0, tag + 'gx0', (50, yloc - 140)),
                   math('LESS_THAN', lx, 1.0, tag + 'lx1', (50, yloc - 200)), tag + 'inx', (200, yloc - 160))
        iny = math('MULTIPLY', math('GREATER_THAN', ly, 0.0, tag + 'gy0', (50, yloc - 260)),
                   math('LESS_THAN', ly, 1.0, tag + 'ly1', (50, yloc - 320)), tag + 'iny', (200, yloc - 280))
        sel = math('GREATER_THAN', math('FLOORED_MODULO', t, none_mod, tag + 'tmod', (50, yloc - 380)), 0.5, tag + 'sel', (200, yloc - 380))
        fac = math('MULTIPLY', math('MULTIPLY', inx, iny, tag + 'in', (350, yloc - 220)),
                   math('MULTIPLY', sel, tex.outputs['Alpha'], tag + 'sa', (350, yloc - 300)), tag + 'fac', (500, yloc - 220))
        mix = node('ShaderNodeMix', tag + 'mix', (650, yloc), data_type='RGBA', blend_type='MIX')
        links.new(fac, mix.inputs['Factor'])
        links.new(color_in, mix.inputs['A'])
        links.new(tex.outputs['Color'], mix.inputs['B'])
        return mix.outputs['Result']

    ea = meta['eyes_atlas']
    current = region('eyeL', meta['eyes']['L']['rect'], 'face_eyeL', eyes_img, ea['cols'], ea['rows'], meta['eyes']['L']['tile_px'], current, -500, ea['cols'])
    current = region('eyeR', meta['eyes']['R']['rect'], 'face_eyeR', eyes_img, ea['cols'], ea['rows'], meta['eyes']['R']['tile_px'], current, -1000, ea['cols'])
    ma = meta['mouth_atlas']
    mr = meta['mouth']['rect']
    current = region('mouth', mr, 'face_mouth', mouth_img, ma['cols'], ma['rows'], [mr[2] - mr[0], mr[3] - mr[1]], current, -1500, 1000)
    links.new(current, shader.inputs[inp])
    mat['mmdance_face_nodes'] = [uvn.name, base.name, shader.name]


def source_texture(cfg, mat):
    if cfg.face.atlas.texture:
        return cfg.path('face.atlas.texture')
    _, base, _, _ = face_nodes(cfg, mat)
    return bpy.path.abspath(base.image.filepath, library=base.image.library)


def ensure_atlas(cfg, mat):
    """Build the atlases with face_atlas.py (system Python) unless they match the config already."""
    src = source_texture(cfg, mat)
    key = cfg.key(config.file_key(src), dict(cfg.face.atlas))
    meta_path = cfg.textures('face_atlas.json')
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            if json.load(f).get('key') == key:
                return meta_path
    cmd = [cfg.tools.python, os.path.join(HERE, 'face_atlas.py'), cfg['_file'], src, key]
    print('[face] building atlases:', ' '.join(cmd))
    subprocess.run(cmd, check=True)
    return meta_path


def run_atlas(cfg, body, w, nf):
    mat = bpy.data.materials[cfg.face.atlas.material]
    meta_path = ensure_atlas(cfg, mat)
    with open(meta_path) as f:
        meta = json.load(f)
    tex = cfg.textures()
    eyes_img = bpy.data.images.load(os.path.join(tex, 'Face_Eyes_Atlas.png'), check_existing=True)
    mouth_img = bpy.data.images.load(os.path.join(tex, 'Face_Mouth_Atlas.png'), check_existing=True)
    for im in (eyes_img, mouth_img):
        im.alpha_mode = 'STRAIGHT'
        im.colorspace_settings.name = 'sRGB'
    if meta.get('clean'):
        # the painting with its projection halos removed (made by face_atlas.py)
        clean = bpy.data.images.load(os.path.join(tex, meta['clean']), check_existing=True)
        face_nodes(cfg, mat)[1].image = clean
    build_shader(cfg, mat, meta, eyes_img, mouth_img)
    eL, eR, mouth = states(cfg, w, nf)
    # eyes keep their one-frame in-between blink states (they make blinks smooth); the mouth holds
    # each shape a few frames so lip-sync never flickers
    mouth, fm = min_hold(mouth, cfg.face.atlas.mouth_min_hold)
    print(f'[face] removed short mouth flickers: {fm}')
    for k in ('face_eyeL', 'face_eyeR', 'face_mouth'):
        body[k] = 0
    act, cbag = new_action(body, cfg.project.name + '_Face')
    frames = np.arange(cfg.project.frame_start, cfg.project.frame_end + 1, dtype=np.float32)
    for k, arr in (('face_eyeL', eL), ('face_eyeR', eR), ('face_mouth', mouth)):
        put_curve(cbag, f'["{k}"]', 0, frames, arr.astype(np.float32), interp=0)
    print('[face] eye states L', np.bincount(eL, minlength=5), 'R', np.bincount(eR - 5, minlength=5),
          'mouth tiles used', np.bincount(mouth, minlength=19))


def run_shapekeys(cfg, body):
    ob = bpy.data.objects[cfg.face.shapekeys.object] if cfg.face.shapekeys.object else body
    keys = ob.data.shape_keys
    mapping = cfg.face.shapekeys.get('map') or {}
    if keys is None or not mapping:
        raise RuntimeError(f'face.mode = "shapekeys": {ob.name} has no shape keys or face.shapekeys.map is empty')
    v = vmd.read_vmd(facial_vmd(cfg))
    act, cbag = new_action(ob, cfg.project.name + '_Face', id_type='KEY', id_data=keys)
    done = 0
    for morph, sk in mapping.items():
        if sk not in keys.key_blocks:
            print(f'[face] shape key {sk!r} not found on {ob.name}: skipped')
            continue
        ks = sorted((f, w) for m, f, w in v['morphs'] if m == morph)
        if not ks:
            continue
        fr = np.array([k[0] for k in ks], np.float32)
        ws = np.array([k[1] for k in ks], np.float32)
        put_curve(cbag, f'key_blocks["{sk}"].value', 0, fr, ws, group='Face', interp=1)
        done += 1
    print(f'[face] {done} shape keys keyed from {len(mapping)} mapped morphs')


def run(cfg):
    if cfg.face.mode == 'none':
        return
    _, body = rig_and_body(cfg)
    if cfg.face.mode == 'shapekeys':
        return run_shapekeys(cfg, body)
    mo = cfg.face.morphs
    names = [mo.blink, mo.wink_left, mo.wink_right, mo.smile, mo.a, mo.i, mo.u, mo.e, mo.o, mo.wa, mo.smirk]
    nf = cfg.project.frame_end - cfg.project.frame_start + 1
    run_atlas(cfg, body, morph_curves(cfg, names), nf)
