"""Build the animated scene for a project (run inside Blender).

  blender -b <character.blend> --python build.py -- <project.toml> [--resim] [--resample]
          [--until N] [--stages motion,camera,...]

or simply `python -m mmdance build <project.toml>`, which finds the character .blend in the
config. The character file is only read; the result is saved to paths.blend.

Stages, in order: motion, camera, rig, physics, face, stage. Caches live in paths.cache and are
keyed by their inputs, so a rebuild only recomputes what changed:
  --resim      recompute the cloth/hair simulation even if a matching cache exists
  --resample   re-sample the body track used by the simulation
  --until N    simulate only the first N frames and stop (quick physics checks; nothing is saved)
  --stages     run only these stages (the scene is saved unless --until is given)
"""
import importlib
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mmdance import config, motion  # noqa: E402

STAGES = ['motion', 'camera', 'rig', 'physics', 'face', 'stage']


def parse(argv):
    args = argv[argv.index('--') + 1:] if '--' in argv else []
    if not args or args[0].startswith('--'):
        sys.exit(__doc__)
    flags = {'resim': '--resim' in args, 'resample': '--resample' in args, 'until': 0, 'stages': STAGES}
    if '--until' in args:
        flags['until'] = int(args[args.index('--until') + 1])
    if '--stages' in args:
        flags['stages'] = args[args.index('--stages') + 1].split(',')
    return args[0], flags


def finalize(cfg):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = cfg.project.frame_start, cfg.project.frame_end
    sc.render.fps = cfg.project.fps
    r = sc.render
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    r.image_settings.color_depth = '8'
    r.image_settings.compression = cfg.render.png_compression
    blend = cfg.path('paths.blend')
    frames = cfg.path('paths.frames')
    trail = '/' if cfg.paths.frames.endswith(('/', '\\')) else ''
    try:                             # relative to the .blend, so the project folder can move
        r.filepath = '//' + os.path.relpath(frames, os.path.dirname(blend)).replace('\\', '/') + trail
    except ValueError:               # another drive
        r.filepath = frames + trail
    r.use_overwrite = False          # resumable, and several Blender processes can share the range
    r.use_placeholder = True
    r.use_file_extension = True
    if cfg.audio.file:
        # the song, for previewing in Blender (the MP4 is muxed from the PNGs + audio with ffmpeg)
        if sc.sequence_editor is None:
            sc.sequence_editor_create()
        seqs = sc.sequence_editor.strips if hasattr(sc.sequence_editor, 'strips') else sc.sequence_editor.sequences
        for st in list(seqs):
            if st.name == 'Song':
                seqs.remove(st)
        seqs.new_sound('Song', cfg.path('audio.file'), 1, cfg.project.frame_start)
        sc.use_audio_scrub = True
        sc.sync_mode = 'AUDIO_SYNC'
    r.use_sequencer = False          # render the 3D scene, not the sound strip
    sc.frame_set(cfg.project.frame_start)


def run():
    path, flags = parse(sys.argv)
    cfg = config.load(path)
    cfg.flags = flags
    t_all = time.time()
    motion.resolve(cfg)
    print(f'[build] {cfg.project.name}: frames {cfg.project.frame_start}-{cfg.project.frame_end}, '
          f'scale {cfg.motion.scale} m/MMD unit')
    for name in STAGES:
        if name not in flags['stages']:
            continue
        t0 = time.time()
        print(f'[build] ---- {name}')
        importlib.import_module('mmdance.' + name).run(cfg)
        print(f'[build] ---- {name} done in {time.time() - t0:.0f}s')
        if flags['until'] and name == 'physics':
            print('[build] --until: stopping after the partial simulation (nothing saved)')
            return
    finalize(cfg)
    out = cfg.path('paths.blend')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, relative_remap=True)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile()
    print(f'[build] saved {out} ({time.time() - t_all:.0f}s)')


if __name__ == '__main__':
    run()
