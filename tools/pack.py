"""A self-contained copy of the built scene, to render on another machine (run inside Blender).

  python -m mmdance pack project.toml [out.blend] [--samples N]

* every image is packed into the file and the remaining paths made absolute; anything still
  outside it (libraries, caches) is reported;
* the song's preview strip is dropped (`encode` adds the song afterwards);
* the frames are written next to the copy (frames/<prefix>####.png), resumable as at home: no
  overwrite, placeholders on, so several processes share the range;
* PNG compression is raised: smaller files to download, and saving is a small part of a frame.

On the render machine: `blender -b scene.blend -a`, several processes at once
(tools/remote/render_job.sh). Copy the frames back into paths.frames and run `encode`.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config  # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
cfg = config.load(args[0])
out = args[1]
samples = int(args[args.index('--samples') + 1]) if '--samples' in args else cfg.render.samples
sc = bpy.context.scene
if sc.sequence_editor is not None:
    strips = sc.sequence_editor.strips if hasattr(sc.sequence_editor, 'strips') else sc.sequence_editor.sequences
    for st in list(strips):
        strips.remove(st)
for snd in list(bpy.data.sounds):
    bpy.data.sounds.remove(snd)
bpy.ops.file.make_paths_absolute()
bpy.ops.file.pack_all()
outside = [img.name for img in bpy.data.images
           if img.source in ('FILE', 'SEQUENCE', 'TILED') and img.packed_file is None and img.users]
outside += ['library ' + lib.filepath for lib in bpy.data.libraries]
outside += ['cache ' + c.filepath for c in bpy.data.cache_files]
if sc.render.engine == 'BLENDER_EEVEE':
    sc.eevee.taa_render_samples = samples
else:
    sc.cycles.samples = samples
sc.render.resolution_x, sc.render.resolution_y = cfg.camera.resolution
sc.render.resolution_percentage = 100
prefix = '' if cfg.paths.frames.endswith(('/', '\\')) else os.path.basename(cfg.paths.frames)
sc.render.filepath = '//frames/' + prefix
sc.render.use_overwrite = False
sc.render.use_placeholder = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGB'
sc.render.image_settings.color_depth = '8'
sc.render.image_settings.compression = 60
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True, relative_remap=False)
print('[pack]', out, '| images', len(bpy.data.images), '| outside the file:', outside or 'nothing',
      '| camera', sc.camera.name, '| view', sc.view_settings.view_transform, '| samples', samples,
      '| motion blur', sc.render.use_motion_blur, '| frames', sc.frame_start, sc.frame_end)
