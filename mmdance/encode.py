"""Encode the rendered PNG frames (+ the song) into the final MP4 (system Python + ffmpeg).

  python -m mmdance encode project.toml [out.mp4]

When the song runs longer than the motion, the last frame is held and picture and sound fade out
together at the end instead of cutting the music off.
"""
import os
import subprocess
import sys
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


def main(cfg_path, out=None):
    cfg = config.load(cfg_path)
    if cfg.project.frame_end < 0:
        cfg.project.frame_end = max(b[1] for b in vmd.read_vmd(cfg.path('motion.vmd'))['bones'])
    prefix = cfg.path('paths.frames')
    if cfg.paths.frames.endswith(('/', '\\')):
        prefix += os.sep
    folder, stem = os.path.dirname(prefix), os.path.basename(prefix)
    f0, f1, fps = cfg.project.frame_start, cfg.project.frame_end, cfg.project.fps
    names = [f'{stem}{f:04d}.png' for f in range(f0, f1 + 1)]
    missing = [n for n in names if not os.path.exists(os.path.join(folder, n))]
    small = [n for n in names if n not in missing and os.path.getsize(os.path.join(folder, n)) < 1000]   # placeholders
    if missing or small:
        sys.exit(f'frames incomplete in {folder}: {len(missing)} missing {missing[:5]}, '
                 f'{len(small)} placeholders of unfinished/crashed renders {small[:5]}')
    out = out or cfg.path('paths.video')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    e = cfg.encode
    video_len = len(names) / fps
    cmd = [cfg.tools.ffmpeg, '-y', '-framerate', str(fps), '-start_number', str(f0), '-i', os.path.join(folder, stem + '%04d.png')]
    song = cfg.path('audio.file')
    if song:
        audio_len = audio_length(song)
        total = max(audio_len, video_len)
        hold = max(0.0, audio_len - video_len)
        fade_start = max(0.0, total - e.fade)
        cmd += ['-i', song, '-filter_complex',
                f'[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f},fade=t=out:st={fade_start:.3f}:d={e.fade}[v];'
                f'[1:a]afade=t=out:st={fade_start:.3f}:d={e.fade}[a]',
                '-map', '[v]', '-map', '[a]', '-c:a', 'aac', '-b:a', e.audio_bitrate, '-t', f'{total:.3f}']
    else:
        audio_len, hold = 0.0, 0.0
        cmd += ['-vf', f'fade=t=out:st={max(0.0, video_len - e.fade):.3f}:d={e.fade}']
    cmd += ['-c:v', 'libx264', '-preset', e.preset, '-crf', str(e.crf), '-tune', e.tune, '-pix_fmt', 'yuv420p',
            '-profile:v', 'high', '-r', str(fps), '-movflags', '+faststart', out]
    print(' '.join(cmd))
    subprocess.run(cmd, check=True)
    print('wrote', out, f'({len(names)} frames, video {video_len:.2f}s + hold {hold:.2f}s, audio {audio_len:.2f}s)')


if __name__ == '__main__':
    main(*sys.argv[1:3])
