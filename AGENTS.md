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
To check frames: build, render a few frames from the built scene with
`blender -b <built.blend> -o <dir>/chika_#### -f 50,900,1560,2600`, and diff them against the same
frames of the original render (on the owner's machine, beside the motion's `source/` folder in
`render/frames/`). A build log that says `reusing sim_…` and skips the face atlas means those keys
did not change.

## Conventions
- **Config:** one `project.toml` per animation, merged over `mmdance/defaults.toml`, then
  `project.local.toml` (gitignored, for machine paths). Every new setting gets a default and a
  comment in `defaults.toml`. Code reads `cfg.section.key`, and paths go through
  `cfg.path('section.key')`.
- **Bones:** names are Mixamo *roles* (`Hips`, `LeftUpLeg`, ...). Resolve them with
  `cfg.bone(role)`, never by string concatenation with a prefix.
- **Rig convention:** T-pose, Z up, facing -Y, metres. Numeric defaults suit a ~1 m character.
- **Caches:** file names carry `cfg.key(...)` of their inputs. A new cached step must include
  everything it depends on in its key. A new option for an existing step enters the key only when
  it is set (see `face.atlas_key`, `physics.sim_params`, `thumb_rest` in the body-track key), so
  other projects keep their caches; keys applied after a step (`smooth_frames`) stay out of it.
- **Character-specific code:** stage builders and the like live in the project folder and are
  loaded through config (`stage.builder = "room.py"`), not in `mmdance/`. A builder's
  `finish(collection, cfg)` runs last and is where project code on the built character goes (face
  rebuild, sleeves, wings, a solved camera).
- **Style:** match the surrounding code (numpy-vectorised, short docstrings saying what and why,
  comments only where the reason isn't obvious).

## Pitfalls met so far
- **bmesh faces are created flat.** Set `face.smooth = True` before `normals_split_custom_set`:
  custom normals do not show on flat faces, and turning faces smooth afterwards scrambles them.
- **Create bmesh custom-data layers first.** Adding a vertex layer (`layers.float.new`, ...)
  after taking `BMVert` references leaves those references invalid.
- **Seen from the front, a character's outlines can cross themselves** where the surface folds
  (beside the eyes on a face). Anything meshed or tested in that 2D view (triangulation,
  point-in-polygon) needs the outline untangled first.
- **A stray dark line on the body** is often the outline shell at a crease. Render with the body's
  outline modifier off to tell it from the texture.
- **Check faces at several angles and expressions**, not only straight on.
- **Long builds and renders** (20 min, 2–3 h) should run detached from the agent's shell
  (`Start-Process` on Windows, `nohup`/`setsid` elsewhere). Shells an agent leaves in the background
  can be killed.
- **Blender exits 0 after a Python error** in a `--python` script unless it gets
  `--python-exit-code 1`. `mmdance build` passes it; pass it in your own Blender commands too,
  or a failed stage looks like success.
- **`--until N` never writes the simulation cache**, so a partial run cannot pass for the full one.
- **The toon face's shading follows the key sun** through a driver that reads the sun's
  `rotation_euler` x and z. Animate that sun in XYZ Euler with y = 0.
- **Scaling a set** (an appended `.blend`) by s: point, spot and area light energy goes by s²,
  soft shadow size by s. Sun and world strength stay.
- **Headless EEVEE on a Linux GPU** needs the driver's graphics libraries: the container needs
  `NVIDIA_DRIVER_CAPABILITIES=all`, plus the EGL/GL/Vulkan client packages.
- **Facial tracks from motion capture can be wrong** (a squint read as closed eyes). Check
  `python -m mmdance vmd <facial.vmd>` before blaming the face code.
- **Project code is copied, not shared, between projects.** `projects/dreamwings/claude/face_*.py`
  and `projects/dreamwings/chatgpt/{sleeves,wings}.py` are copies of claude_chika_v3's and
  chatgpt_chika's, with a deeper `sys.path` to the repo root. A fix to one belongs in the other.

## Never commit
`.blend`, `.vmd`, `.pmx`, audio, video, images, caches, renders or `*.local.toml`. The
`.gitignore` enforces this; the one exception is the README and docs-site stills in `docs/media`. Characters, MMD motions and songs belong to their authors.
