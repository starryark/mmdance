"""Encode the rendered PNG frames (+ the song) into the final MP4 (system Python + ffmpeg).

  python -m mmdance encode project.toml [out.mp4]

When the song runs longer than the motion, the last frame is held and picture and sound fade out
together at the end instead of cutting the music off (`encode.song_end = "cut"` ends at the last
frame instead). `[[encode.parts]]` take the frames from another project's render from a frame on
(two characters taking turns), and `encode.copies` writes smaller copies for sharing next to it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import config, vmd  # noqa: E402


def audio_length(path):
    if path.lower().endswith('.wav'):
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def frame_files(cfg):
    """The PNG of every frame: this project's render, or a part's from its start frame on."""
    def prefix_of(p):
        full = cfg.resolve(p)
        return full + os.sep if p.endswith(('/', '\\')) else full
    f0, f1 = cfg.project.frame_start, cfg.project.frame_end
    parts = sorted(cfg.encode.parts, key=lambda p: p['start'])
    out = []
    for f in range(f0, f1 + 1):
        src = cfg.paths.frames
        for p in parts:
            if f >= p['start']:
                src = p['frames']
        out.append(f'{prefix_of(src)}{f:04d}.png')
    return out


def copy_commands(ffmpeg, e, src, out, c, duration, log):
    """The ffmpeg command(s) of a smaller copy: scaled to `height`, at `crf`, or two-pass at
    `bitrate` (or the bitrate that fits under `max_mb`). `tune` overrides encode.tune ("" = none)."""
    vf = ['-vf', f'scale=-2:{c["height"]}:flags=lanczos'] if c.get('height') else []
    tune = c.get('tune', e.tune)
    head = [ffmpeg, '-y', '-v', 'error', '-i', src] + vf + ['-c:v', 'libx264', '-preset', e.preset] + \
        (['-tune', tune] if tune else []) + ['-pix_fmt', 'yuv420p']
    abr = c.get('audio_bitrate', '128k')
    audio = ['-c:a', 'aac', '-b:a', abr, '-movflags', '+faststart']
    if not (c.get('bitrate') or c.get('max_mb')):
        return [head + ['-crf', str(c.get('crf', 20))] + audio + [out]]
    vbr = c.get('bitrate') or f"{int(c['max_mb'] * 8000 * 0.96 / duration - int(abr.rstrip('k')))}k"  # 4 % for the container
    return [head + ['-b:v', vbr, '-pass', str(n), '-passlogfile', log] + tail
            for n, tail in ((1, ['-an', '-f', 'mp4', os.devnull]), (2, audio + [out]))]


def copy(ffmpeg, e, src, out, c, duration):
    with tempfile.TemporaryDirectory() as tmp:
        for cmd in copy_commands(ffmpeg, e, src, out, c, duration, os.path.join(tmp, 'pass')):
            subprocess.run(cmd, check=True)
    print('wrote', out, f'{os.path.getsize(out) / 1e6:.2f} MB')


def main(cfg_path, out=None):
    cfg = config.load(cfg_path)
    if cfg.project.frame_end < 0:
        cfg.project.frame_end = max(b[1] for b in vmd.read_vmd(cfg.path('motion.vmd'))['bones'])
    f0, fps = cfg.project.frame_start, cfg.project.fps
    files = frame_files(cfg)
    missing = [p for p in files if not os.path.exists(p)]
    small = [p for p in files if p not in missing and os.path.getsize(p) < 1000]   # placeholders
    if missing or small:
        sys.exit(f'frames incomplete: {len(missing)} missing {missing[:5]}, '
                 f'{len(small)} placeholders of unfinished/crashed renders {small[:5]}')
    out = out or cfg.path('paths.video')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    e = cfg.encode
    video_len = len(files) / fps
    tmp = None
    if cfg.encode.parts:                     # one numbered sequence from several folders (links, else copies)
        tmp = tempfile.mkdtemp(prefix='mmdance_enc_')
        for f, src in zip(range(f0, f0 + len(files)), files):
            dst = os.path.join(tmp, f'f_{f:04d}.png')
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy(src, dst)
        pattern = os.path.join(tmp, 'f_%04d.png')
    else:
        prefix = cfg.path('paths.frames')
        if cfg.paths.frames.endswith(('/', '\\')):
            prefix += os.sep
        pattern = os.path.join(os.path.dirname(prefix), os.path.basename(prefix) + '%04d.png')
    cmd = [cfg.tools.ffmpeg, '-y', '-framerate', str(fps), '-start_number', str(f0), '-i', pattern]
    song = cfg.path('audio.file')
    if song:
        audio_len = audio_length(song)
        total = max(audio_len, video_len) if e.song_end == 'hold' else video_len
        hold = max(0.0, total - video_len)
        fade_start = max(0.0, total - e.fade)
        vfade = f',fade=t=out:st={fade_start:.3f}:d={e.fade}' if e.fade_picture else ''
        trim = f'atrim=0:{total:.4f},' if total < audio_len else ''
        cmd += ['-i', song, '-filter_complex',
                f'[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f}{vfade}[v];'
                f'[1:a]{trim}afade=t=out:st={fade_start:.3f}:d={e.fade}[a]',
                '-map', '[v]', '-map', '[a]', '-c:a', 'aac', '-b:a', e.audio_bitrate, '-t', f'{total:.3f}']
    else:
        audio_len, hold, total = 0.0, 0.0, video_len
        if e.fade_picture:
            cmd += ['-vf', f'fade=t=out:st={max(0.0, video_len - e.fade):.3f}:d={e.fade}']
    cmd += ['-c:v', 'libx264', '-preset', e.preset, '-crf', str(e.crf), '-tune', e.tune, '-pix_fmt', 'yuv420p',
            '-profile:v', 'high', '-r', str(fps), '-movflags', '+faststart', out]
    print(' '.join(cmd))
    try:
        subprocess.run(cmd, check=True)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print('wrote', out, f'({len(files)} frames, video {video_len:.2f}s + hold {hold:.2f}s, audio {audio_len:.2f}s)')
    stem, ext = os.path.splitext(out)
    for c in e.copies:
        copy(cfg.tools.ffmpeg, e, out, stem + c['suffix'] + ext, c, total)


if __name__ == '__main__':
    main(*sys.argv[1:3])
