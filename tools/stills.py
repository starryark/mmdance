"""Quick check renders of a built scene (run inside Blender).

  python -m mmdance stills project.toml 300,1068,1565 [views] [size]
  blender -b scene.blend --python tools/stills.py -- project.toml out_dir frames [views] [size] [engine]

views (comma separated): cam (the scene camera, default), front, side, back, left, top, iso
(cameras that follow the hips), face (a close-up that follows the head), bone=Name=dist (a
close-up on a bone, e.g. bone=LeftHand=0.25). engine: EEVEE (8 samples) or WORKBENCH.
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config  # noqa: E402
from mmdance.util import rig_and_body  # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
cfg = config.load(args[0])
outdir, frames = args[1], [int(x) for x in args[2].split(',')]
views = args[3].split(',') if len(args) > 3 else ['cam']
res = int(args[4]) if len(args) > 4 else 600
engine = args[5] if len(args) > 5 else 'EEVEE'

sc = bpy.context.scene
sc.render.resolution_percentage = 100
sc.render.use_overwrite = True
if engine == 'WORKBENCH':
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'TEXTURE'
else:
    sc.eevee.taa_render_samples = 8

shots = sorted(((m.frame, m.camera) for m in sc.timeline_markers if m.camera), key=lambda t: t[0])
if any(v != 'cam' for v in views):
    for m in list(sc.timeline_markers):      # markers would re-bind the scene camera on every frame
        m.camera = None
cam_data = bpy.data.cameras.new('Stills_Cam')
cam = bpy.data.objects.new('Stills_Cam', cam_data)
sc.collection.objects.link(cam)
rig, _ = rig_and_body(cfg)
scene_cam = sc.camera
dirs = {'front': (0, -1, 0.15), 'side': (1, 0, 0.15), 'back': (0, 1, 0.15), 'top': (0.001, -0.3, 1.0),
        'iso': (0.8, -0.8, 0.5), 'left': (-1, 0, 0.15)}
os.makedirs(outdir, exist_ok=True)


def aim(target, location, lens, clip):
    cam.location = location
    cam.rotation_euler = (target - location).to_track_quat('-Z', 'Y').to_euler()
    cam_data.lens = lens
    cam_data.clip_start = clip
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res, res


for f in frames:
    sc.frame_set(f)
    hips = rig.matrix_world @ rig.pose.bones[cfg.bone('Hips')].head
    for v in views:
        if v.startswith('bone='):
            _, bname, dist = v.split('=')
            pb = rig.pose.bones[cfg.bone(bname)]
            M = rig.matrix_world @ pb.matrix
            target = M @ Vector((0, pb.length * 0.6, 0))
            d = (Vector(dirs['front']) * 0.7 + Vector((0.4, 0, 0.35))).normalized()
            aim(target, target + d * float(dist), 50, 0.005)
        elif v == 'face':
            hb = rig.pose.bones[cfg.bone('Head')]
            M = rig.matrix_world @ hb.matrix
            R0 = hb.bone.matrix_local.to_3x3()
            fwd = (M.to_3x3() @ (R0.inverted() @ Vector((0, -1, 0)))).normalized()
            up = (M.to_3x3() @ (R0.inverted() @ Vector((0, 0, 1)))).normalized()
            target = M.translation + up * 0.055 + fwd * 0.03
            aim(target, target + fwd * 0.42 + up * 0.02, 60, 0.01)
        elif v == 'cam':
            sc.camera = scene_cam
            for mf, mc in shots:                 # the camera the timeline markers select at this frame
                if mf <= f:
                    sc.camera = mc
            sc.render.resolution_x, sc.render.resolution_y = res * 16 // 9, res
        else:
            d = Vector(dirs[v]).normalized()
            target = Vector((hips.x, hips.y, max(hips.z * 0.8, 0.35)))
            aim(target, target + d * 2.4, 50, 0.05)
        sc.render.filepath = os.path.join(outdir, f"{f:04d}_{v.replace('=', '-')}.png")
        bpy.ops.render.render(write_still=True)
print('stills written to', outdir)
