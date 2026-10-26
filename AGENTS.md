# Notes for coding agents

mmdance is a Blender pipeline: an MMD (VMD) dance on a Mixamo-rigged character, with physics,
facial animation, stage, render and encode. Read README.md first, then docs/how-it-works.md.

## Running things
- Everything goes through `python -m mmdance <command> <project.toml>`:
  - `new`, `inspect`, `vmd`: start a project and look at a character or VMD;
  - `build`, `stills`, `render`, `encode`, `qa`: make and check the video.
- The Blender side runs as `blender -b <character.blend> --python build.py -- <project.toml> [flags]`.
  The CLI finds Blender via `$BLENDER`, `tools.blender`, `PATH`, or the standard install folders.
- Two Pythons are involved. Modules that import `bpy` (`motion`, `camera`, `rig`, `layers`,
  `physics`, `face`, `hands`, `stage`, `util`, `tools/stills.py`, `tools/inspect_character.py`)
  run only inside Blender. `config`, `vmd`, `solver`, `encode`, `face_atlas`, `hand_sdf` and the
  QA/plot tools run in system Python. `face_atlas.py` and `hand_sdf.py` are launched from Blender
  as subprocesses (`tools.python`) because Blender's Python lacks opencv and scikit-image.
- `--until N` simulates N frames only (fast physics iteration). `--stages a,b` runs a subset.
  `--resim` and `--resample` force recomputation of cached results.

## Tests and lint (CI runs both)
```
python -m pyflakes build.py mmdance tools projects tests
python -m unittest discover tests -v
```
Unit tests cover config, the VMD parser and the solver, without Blender. Anything touching `bpy`
must be checked with a real build. Use `python -m mmdance stills ...` to look at frames, and
`python -m mmdance qa ...` for physics metrics.

## Regression standard
`projects/claude_chika` is the production the pipeline was built for. Changes to engine code must
keep it reproducing that output:
- the caches (`proxy_*`, `body_track_*`, `lattice.npz`, `hands_*`, `sim_*`) and the face atlases
  stay bit-identical;
- rendered frames stay pixel-identical, up to ±1 GPU noise.

The assets are not in the repo. A `project.local.toml` next to the project's `project.toml`
points at them on the owner's machine. If you can't run it, say so; do not claim it passes.

## Conventions
- **Config:** one `project.toml` per animation, merged over `mmdance/defaults.toml`, then
  `project.local.toml` (gitignored, for machine paths). Every new setting gets a default and a
  comment in `defaults.toml`. Code reads `cfg.section.key`, and paths go through
  `cfg.path('section.key')`.
- **Bones:** names are Mixamo *roles* (`Hips`, `LeftUpLeg`, ...). Resolve them with
  `cfg.bone(role)`, never by string concatenation with a prefix.
- **Rig convention:** T-pose, Z up, facing -Y, metres. Numeric defaults suit a ~1 m character.
- **Caches:** file names carry `cfg.key(...)` of their inputs. A new cached step must include
  everything it depends on in its key.
- **Character-specific code:** stage builders and the like live in the project folder and are
  loaded through config (`stage.builder = "room.py"`), not in `mmdance/`.
- **Style:** match the surrounding code (numpy-vectorised, short docstrings saying what and why,
  comments only where the reason isn't obvious).

## Never commit
`.blend`, `.vmd`, `.pmx`, audio, video, images, caches, renders or `*.local.toml`. The
`.gitignore` enforces this. Characters, MMD motions and songs belong to their authors.
