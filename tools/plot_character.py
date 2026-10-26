"""Front and side views of a character with a height grid, coloured by material (system Python).

  python tools/plot_character.py inspect_dir      (run by `python -m mmdance inspect`)

Read the skirt/hair joint heights off the grid; the suggested lattice rows from report.json are
drawn as dashed lines.
"""
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

d = sys.argv[1]
m = np.load(os.path.join(d, 'mesh.npz'))
with open(os.path.join(d, 'report.json'), encoding='utf-8') as f:
    rep = json.load(f)
co, mat, names = m['co'], m['mat'], list(m['mats'])
sug = rep.get('suggested', {})
fig, axes = plt.subplots(1, 2, figsize=(14, 10), sharey=True)
step = max(1, len(co) // 60000)
for ax, (i, label) in zip(axes, ((0, 'front (x)'), (1, 'side (y)'))):
    for k, n in enumerate(names):
        idx = np.nonzero(mat == k)[0][::step]
        if not len(idx):
            continue
        ax.scatter(co[idx, i], co[idx, 2], s=0.3, label=n, alpha=0.6)
    lo, hi = co[:, 2].min(), co[:, 2].max()
    for z in np.arange(np.floor(lo * 20) / 20, hi + 0.05, 0.05):
        ax.axhline(z, color='0.85', lw=0.5, zorder=0)
        ax.text(co[:, i].min(), z, f'{z:.2f}', fontsize=7, color='0.4', va='bottom')
    for key, color in (('skirt.rows_z', 'tab:red'), ('hair.rows_z', 'tab:purple')):
        for z in sug.get(key, []):
            ax.axhline(z, color=color, lw=0.8, ls='--')
    ax.set_aspect('equal')
    ax.set_title(label)
axes[0].legend(markerscale=20, fontsize=8, loc='upper right')
fig.suptitle(f"{os.path.basename(rep['file'])}: height {rep['height']} m  (dashed: suggested skirt rows red, hair rows purple)")
out = os.path.join(d, 'character.png')
fig.savefig(out, dpi=110, bbox_inches='tight')
print('wrote', out)
if rep['problems']:
    print('PROBLEMS:\n  ' + '\n  '.join(rep['problems']))
print('suggested config values:', json.dumps(sug, indent=1))
