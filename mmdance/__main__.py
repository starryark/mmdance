"""Command line: python -m mmdance <command> ...

  new      <folder>                        start a project folder from the template
  inspect  <character.blend> [out_dir]     rig/mesh report + measured heights for a new character
  vmd      <file.vmd> ...                  what a VMD contains (bones, morphs, camera, frame range)
  build    <project.toml> [--resim] [--resample] [--until N] [--stages a,b]
  stills   <project.toml> <frames> [views] [size]   quick EEVEE stills of the built scene
  render   <project.toml> [--jobs N] [--start F] [--end F]
  encode   <project.toml> [out.mp4]
  qa       <project.toml>                  physics checks on the cached simulation
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mmdance import config  # noqa: E402


def blender(cfg_or_none):
    """The Blender executable: $BLENDER, tools.blender, PATH, or the newest standard install."""
    exe = os.environ.get('BLENDER') or (cfg_or_none.tools.blender if cfg_or_none else 'blender')
    found = shutil.which(exe) or (exe if os.path.isfile(exe) else None)
    if not found:
        import glob
        pats = [r'C:\Program Files\Blender Foundation\Blender*\blender.exe',
                os.path.expanduser(r'~\AppData\Local\Programs\Blender Foundation\Blender*\blender.exe'),
                '/Applications/Blender*.app/Contents/MacOS/Blender', '/usr/bin/blender', '/snap/bin/blender']
        hits = [h for p in pats for h in glob.glob(p)]
        if hits:                   # newest version, e.g. "Blender 5.2" > "Blender 4.5"
            found = max(hits, key=lambda h: [int(x) for x in re.findall(r'\d+', h)])
    if not found:
        sys.exit(f'Blender not found ({exe}): put it on PATH, set BLENDER, or set tools.blender in project.toml')
    return found


def cmd_build(args):
    cfg = config.load(args[0])
    char = cfg.path('paths.character')
    if not os.path.exists(char):
        sys.exit(f'paths.character not found: {char}')
    # --python-exit-code: a Python error in a stage fails the command instead of exiting 0
    run([blender(cfg), '-b', char, '--python-exit-code', '1', '--python', os.path.join(ROOT, 'build.py'), '--',
         os.path.abspath(args[0])] + args[1:])


def cmd_render(args):
    cfg = config.load(args[0])
    opt = {'--jobs': 2, '--start': None, '--end': None}
    for k in opt:
        if k in args:
            opt[k] = int(args[args.index(k) + 1])
    jobs, start, end = opt['--jobs'], opt['--start'], opt['--end']
    blend = cfg.path('paths.blend')
    cmd = [blender(cfg), '-b', blend]
    if start is not None:
        cmd += ['-s', str(start)]
    if end is not None:
        cmd += ['-e', str(end)]
    cmd += ['-a']
    # the scene renders with use_overwrite off + placeholders, so parallel jobs share the range and a
    # rerun resumes where it stopped (delete the frames folder to re-render from scratch)
    print(f'rendering {blend} with {jobs} Blender process(es)')
    procs = [subprocess.Popen(cmd) for _ in range(jobs)]
    codes = [p.wait() for p in procs]
    if any(codes):
        sys.exit(f'render processes exited with {codes}')


def cmd_stills(args):
    cfg = config.load(args[0])
    out = os.path.join(os.path.dirname(cfg.path('paths.blend')), 'stills')
    run([blender(cfg), '-b', cfg.path('paths.blend'), '--python', os.path.join(ROOT, 'tools', 'stills.py'), '--',
         os.path.abspath(args[0]), out] + args[1:])


def cmd_inspect(args):
    out = args[1] if len(args) > 1 else os.path.join(os.getcwd(), 'inspect')
    os.makedirs(out, exist_ok=True)
    run([blender(None), '-b', args[0], '--python', os.path.join(ROOT, 'tools', 'inspect_character.py'), '--', out])
    run([sys.executable, os.path.join(ROOT, 'tools', 'plot_character.py'), out])


def cmd_new(args):
    dst = args[0]
    if os.path.exists(dst) and os.listdir(dst):
        sys.exit(f'{dst} exists and is not empty')
    os.makedirs(os.path.join(dst, 'source'), exist_ok=True)
    os.makedirs(os.path.join(dst, 'character'), exist_ok=True)
    shutil.copy(os.path.join(ROOT, 'projects', 'template', 'project.toml'), os.path.join(dst, 'project.toml'))
    print(f'created {dst}: put the character in character/, the VMDs and song in source/, then edit project.toml')


def run(cmd):
    print('>', ' '.join(cmd))
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('new', 'inspect', 'vmd', 'build', 'stills', 'render', 'encode', 'qa'):
        sys.exit(__doc__)
    c, args = sys.argv[1], sys.argv[2:]
    if c == 'encode':
        from mmdance import encode
        encode.main(*args[:2])
    elif c == 'vmd':
        run([sys.executable, os.path.join(ROOT, 'mmdance', 'vmd.py')] + args)
    elif c == 'qa':
        run([sys.executable, os.path.join(ROOT, 'tools', 'physics_qa.py')] + args)
    else:
        globals()['cmd_' + c](args)


if __name__ == '__main__':
    main()
