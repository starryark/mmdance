"""Report on a rigged character for setting up a new project (run inside Blender).

  python -m mmdance inspect character.blend [out_dir]

Checks what the pipeline assumes (one armature, Mixamo-style bone names, Z up, facing -Y, T-pose),
measures the heights the skirt/hair lattices need, and writes:
  out_dir/report.json   objects, materials, bone mapping, measurements, suggested config values
  out_dir/mesh.npz      vertex positions + material per vertex (for plot_character.py)
"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance.solver import TRACK  # noqa: E402

out = sys.argv[sys.argv.index('--') + 1]
os.makedirs(out, exist_ok=True)
REQUIRED = sorted(set(TRACK + ['Spine', 'Spine2', 'Neck', 'Head'] +
                      [s + n for s in ('Left', 'Right') for n in
                       ['Shoulder', 'Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase'] +
                       [f'Hand{f}{k}' for f in ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky') for k in (1, 2, 3)]]))
report = {'file': bpy.data.filepath, 'problems': []}
arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
report['armatures'] = [o.name for o in arms]
if len(arms) != 1:
    report['problems'].append(f'{len(arms)} armatures: set character.rig')
rig = arms[0]
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and
          (o.parent is rig or any(m.type == 'ARMATURE' and m.object is rig for m in o.modifiers))]
report['meshes'] = {o.name: len(o.data.vertices) for o in meshes}
body = max(meshes, key=lambda o: len(o.data.vertices))
report['body'] = body.name

# bone naming: find the prefix in front of 'Hips'
names = [b.name for b in rig.data.bones]
hips = [n for n in names if n.lower().endswith('hips')]
prefix = hips[0][:-4] if hips else ''
missing = [r for r in REQUIRED if prefix + r not in names]
report['bones'] = {'count': len(names), 'prefix': prefix, 'missing_roles': missing}
if missing:
    report['problems'].append(f'bones not found for roles {missing}: map them in [bones.map]')

me = body.data
co = np.array([body.matrix_world @ v.co for v in me.vertices])
mat_of_vert = np.full(len(co), -1)
for p in me.polygons:
    mat_of_vert[list(p.vertices)] = p.material_index
mats = [m.name if m else '' for m in me.materials]
report['materials'] = {}
for i, m in enumerate(mats):
    sel = mat_of_vert == i
    if sel.any():
        report['materials'][m] = dict(vertices=int(sel.sum()), z=[round(float(co[sel, 2].min()), 3), round(float(co[sel, 2].max()), 3)],
                                      x=[round(float(co[sel, 0].min()), 3), round(float(co[sel, 0].max()), 3)])
height = float(co[:, 2].max() - co[:, 2].min())
report['height'] = round(height, 4)

if not missing:
    B = rig.data.bones

    def h(n):
        return np.array(rig.matrix_world @ B[prefix + n].head_local)
    meas = {n: round(float(h(n)[2]), 4) for n in ('Hips', 'Spine', 'Neck', 'Head', 'LeftUpLeg', 'LeftLeg', 'LeftFoot')}
    leg = np.linalg.norm(h('LeftLeg') - h('LeftUpLeg')) + np.linalg.norm(h('LeftFoot') - h('LeftLeg'))
    meas['leg_length'] = round(float(leg), 4)
    report['heights'] = meas
    # conventions
    if h('LeftToeBase')[1] > h('LeftFoot')[1]:
        report['problems'].append('the toes point +Y: the character must face -Y')
    arm_dir = h('LeftForeArm') - h('LeftArm')
    arm_dir /= np.linalg.norm(arm_dir)
    if arm_dir[0] < 0.9:
        report['problems'].append(f'the left arm is not along +X (direction {arm_dir.round(2).tolist()}): '
                                  'the rest pose must be a T-pose with the character facing -Y')
    if h('Head')[2] < h('Hips')[2]:
        report['problems'].append('the head is below the hips: Z must be up')
    # suggestions (metres, rest pose)
    hip_z, knee_z = meas['Hips'], meas['LeftLeg']
    sug = {'motion.scale': round(float(leg) / 9.42, 4)}
    hair = [m for m in report['materials'] if 'hair' in m.lower()]
    if hair:
        hz = report['materials'][hair[0]]['z']
        neck = meas['Neck']
        sug['hair.material'] = hair[0]
        sug['hair.rip_below'] = round(neck - 0.03 * height, 3)
        sug['hair.rows_z'] = [round(float(z), 3) for z in np.linspace(neck - 0.03 * height, max(hz[0], 0.02) + 0.02 * height, 7)]
    # skirt: non-hair cloth well outside the legs below the hips
    r = np.hypot(co[:, 0], co[:, 1] - h('Hips')[1])
    wide = (co[:, 2] < hip_z) & (r > 0.16 * height)
    if wide.sum() > 200:
        hem = float(np.percentile(co[wide, 2], 1))
        top = hip_z + 0.04 * height
        sug['skirt.top'] = round(top, 3)
        sug['skirt.rows_z'] = [round(float(z), 3) for z in np.linspace(top - 0.02 * height, hem + 0.01 * height, 9)]
        sug['skirt.enabled'] = True
    sug['legs.min_top'] = round(knee_z, 3)
    report['suggested'] = sug
np.savez(os.path.join(out, 'mesh.npz'), co=co, mat=mat_of_vert, mats=np.array(mats))
with open(os.path.join(out, 'report.json'), 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=1, ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
