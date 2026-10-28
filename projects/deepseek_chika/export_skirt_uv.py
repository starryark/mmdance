"""Export the skirt's triangles for skirt_texture.py (run inside Blender on the character file).

  blender -b character.blend --python export_skirt_uv.py -- project.toml skirt_uv.npz

Writes the skirt's rest-pose triangles (tail and legs excluded, as the rig stage sees them), their
UVs, whether each faces outward, its apron (outer layer) label, and the UVs of every triangle
that uses the same texture (so the cleanup knows which texels are free gutter).
"""
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from mmdance import config, layers, rig  # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
cfg = config.load(args[0])
ob = bpy.data.objects[cfg.character.body]
me = ob.data
co, hair, skirt, legs, seam = rig.classify(cfg, ob)
if cfg.tail.enabled:
    skirt &= ~rig.tail_island(cfg, ob, co)
sk_phi = rig.sk_phi_fn(cfg.skirt.axis)
a0, a1 = np.radians(cfg.overskirt.phi_range)
allow = (sk_phi(co[:, :2]) >= a0) & (sk_phi(co[:, :2]) <= a1) & (co[:, 2] >= cfg.overskirt.zbottom)
lab, _ = layers.classify_layers(ob, np.nonzero(skirt)[0], cfg.overskirt.ztop, tuple(cfg.skirt.axis), allow)
me.calc_loop_triangles()
uvl = me.uv_layers.active.data
cloth = [m.name for m in me.materials].index(next(iter(cfg.stage.lining)))     # the skirt's material
image = next(n for n in me.materials[cloth].node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage').image
users = {i for i, m in enumerate(me.materials) if m and m.node_tree and any(
    n.bl_idname == 'ShaderNodeTexImage' and n.image == image for n in m.node_tree.nodes)}
ax = np.array(cfg.skirt.axis)
tris, uvs, facing, apron = [], [], [], []
for t in me.loop_triangles:
    vs = list(t.vertices)
    if t.material_index != cloth or not skirt[vs].all():
        continue
    tris.append(co[vs])
    uvs.append([uvl[li].uv[:] for li in t.loops])
    c = co[vs].mean(0)
    r = np.array([c[0] - ax[0], c[1] - ax[1], 0.0])
    facing.append(float(np.dot(np.array(t.normal), r / (np.linalg.norm(r) + 1e-9))))
    apron.append(float(lab[vs].mean()))
all_uv = np.array([[uvl[li].uv[:] for li in t.loops] for t in me.loop_triangles if t.material_index in users])
np.savez(args[1], all_uv=all_uv, tris=np.array(tris), uvs=np.array(uvs), facing=np.array(facing),
         apron=np.array(apron), axis=ax, image=bpy.path.abspath(image.filepath))
print(f'exported {len(tris)} skirt triangles, {len(all_uv)} triangles on {image.name}')
