"""Rewrite a facial VMD (system Python): keep the morphs that read right, replace the ones that don't.

Facial tracks made by motion capture can misread the dancer: the DreamWings capture read a squinting
grin as closed eyes (ウィンク above 0.5 on 96 % of its keys; `python -m mmdance vmd face.vmd` shows
this). This writes a new track with only:
  * the mouth morphs you keep, each scaled, capped and renamed (`--mouth SRC:DST:GAIN:MAX`);
  * natural blinks (まばたき) every MIN to MAX frames instead of the capture's eyes (`--blinks`);
  * a light smile while the mouth is closed (`--smile NAME:LEVEL`).

  python -m mmdance facial face.vmd face_clean.vmd --blinks 75,120 --mouth ワ:あ:2.2:0.75 \\
      --mouth お:お:2.5:0.5 --smile にやり:0.65

The blinks are random but seeded (`--seed`), so the same arguments write the same file.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmdance import vmd  # noqa: E402

BLINK = (0.5, 1.0, 1.0, 0.6, 0.2)          # one blink over 5 frames: closing, closed, opening


def curve(morphs, name, n):
    """A morph's weight on every frame (linear between keys, as MMD)."""
    k = sorted((f, w) for m, f, w in morphs if m == name)
    if not k:
        return np.zeros(n)
    return np.interp(np.arange(n), [a for a, _ in k], [b for _, b in k])


def blinks(n, gap, seed, first):
    out = np.zeros(n)
    rng = np.random.default_rng(seed)
    t = first
    while t < n - len(BLINK) - 1:
        for k, w in enumerate(BLINK):
            out[t + k] = max(out[t + k], w)
        t += int(rng.uniform(*gap))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--mouth', action='append', default=[], metavar='SRC:DST:GAIN:MAX',
                    help='keep morph SRC as DST, weight x GAIN capped at MAX (repeatable)')
    ap.add_argument('--blinks', metavar='MIN,MAX', help='natural blinks every MIN to MAX frames, replacing the eyes')
    ap.add_argument('--smile', metavar='NAME:LEVEL', help='this morph at LEVEL while the mouth is closed')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--first', type=int, default=40, help='frame of the first blink')
    ap.add_argument('--model', help='model name in the file (default: the output file name)')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    v = vmd.read_vmd(a.src)
    n = 1 + max(f for _, f, _ in v['morphs'])
    tracks = {}
    if a.blinks:
        tracks['まばたき'] = blinks(n, [float(x) for x in a.blinks.split(',')], a.seed, a.first)
    mouth = np.zeros(n)
    for spec in a.mouth:
        src, dst, gain, cap = spec.split(':')
        tracks[dst] = np.clip(curve(v['morphs'], src, n) * float(gain), 0, float(cap))
        mouth = mouth + tracks[dst]
    if a.smile:
        name, level = a.smile.split(':')
        tracks[name] = float(level) * (1 - np.clip(mouth * 2.5, 0, 1))
    model = a.model or os.path.splitext(os.path.basename(a.out))[0]
    vmd.write_morphs(a.out, model, [(m, i, float(c[i])) for m, c in tracks.items() for i in range(n)])
    print('frames', n, {m: (round(float(c.max()), 2), round(float(c.mean()), 2)) for m, c in tracks.items()})


if __name__ == '__main__':
    main()
