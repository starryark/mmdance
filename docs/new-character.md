# A new character or dance

## 1. The character file
mmdance reads a `.blend` with one armature and one main skinned mesh, and never modifies it. The
pipeline assumes:
- **Mixamo bone names** (`mixamorig:Hips`, `mixamorig:LeftUpLeg`, ...). Tripo, Meshy, Mixamo and
  AccuRig exports use them. For other names, set `[bones] prefix` or map each Mixamo role in
  `[bones.map]`. The fingers need three bones each, plus an end bone if you rebuild the hands.
- **Rest pose:** a T-pose with the arms along ±X, Z up, the character facing -Y, standing on Z = 0.
- **Units:** metres. The shipped defaults suit a character about 1 m tall; see step 3 for other
  sizes.

Shading is up to you; the pipeline keeps whatever materials the file has. A toon shader with
outlines suits MMD motions. The example character uses an EEVEE toon node group and a
geometry-nodes outline.

## 2. Inspect it
```
python -m mmdance inspect character/my_character.blend inspect/
```
This prints `report.json` and writes `inspect/character.png`, front and side views with a 5 cm
height grid coloured by material. The report contains:
- **Problems:** missing bone roles, the wrong facing direction, or a rest pose that isn't a T-pose.
- **Measurements:** height, hip, knee and neck heights, and leg length.
- **Suggested values:** `motion.scale`, the hair material and rows, and the skirt top and rows.

The suggestions are starting points, read off the mesh by simple rules.

## 3. Write project.toml
Start from `python -m mmdance new projects/<name>`. Only set what differs from
`mmdance/defaults.toml`.

**Skirt** (`[skirt]`):
- `top` is the height below which non-hair cloth counts as skirt.
- `rows_z` are the joint heights from the waist to the hem, usually 7–9 rows.
- `columns` is 24 for a full skirt; fewer suits a short, stiff one.
- If the legs are not their own mesh island, set `skirt.materials` to the skirt's material so the
  legs are left out.

**Overskirt** (`[overskirt]`): turn it on only for a real second layer, such as open panels or a
peplum over the skirt. `rig` prints how many vertices it found on the outer layer and the panel
columns.

**Hair** (`[hair]`):
- `material` is required.
- `rows_z` run from just below the head to the hair tips.
- `phi_range` is the arc round the head that has long hair, with 0 at the back.
- `rip_below` should sit a little below the nape.

**Other sizes:** for a character H metres tall, multiply these by H:
- the heights in `[skirt]`, `[hair]` and `[legs]`;
- `physics.skirt.radius` and `physics.overskirt.radius`.

The physics stiffnesses are ratios and need no scaling; gravity follows `motion.scale`
automatically.

**Repairs** (`[fixes]`) are opt-in, for errors auto-riggers make: hair/cloth seams pulled by the
arms, waist vertices that follow the thighs, weights that bleed between legs that touch, boots that
crumple. Turn one on only when you see the problem in a still.

**Hands** (`[hands]`): use these only if the hands are fused blobs and have their own material
slot. The replacement is a clean stylised hand built from the bones. `skin_color` sets its flat
colour.

**Face** (`[face]`):
- `"shapekeys"` with a `map` from VMD morph names to your shape keys. VMD morph names are Japanese:
  `python -m mmdance vmd facial.vmd` lists them.
- `"atlas"` for a painted face. Measure the guide curves on the face texture in pixels:
  - `lash_top` and `lash_bot`: the upper and lower edges of the painted lash band;
  - `lower`: the lower lid line;
  - the mouth's centre and a rectangle round it.

  10–13 points per curve, from the inner to the outer corner, are enough. Open the texture in an
  image editor with a pixel grid and check the result with `textures/atlas_eyes_preview.png`.

**Camera:**
- `camera.vmd`: the MMD camera. Each MMD motion usually ships one tuned for a standard model.
- `[[camera.shots]]`: replaces it over a frame range when it doesn't suit your model, for instance
  when the lens ends up inside a big skirt.
- `camera.resolution`: the output size.

**Stage:**
- `builder = "default"` gives a floor and a flat backdrop.
- For a set, write a builder: copy the shape of `projects/claude_chika/room.py`. Furniture the
  dance touches should also be returned from `colliders(cfg)` as boxes `(x0, x1, y0, y1, top)`.

## 4. Build, look, iterate
```
python -m mmdance build  projects/<name>/project.toml
python -m mmdance stills projects/<name>/project.toml 120,480,900 cam,front,side
python -m mmdance stills projects/<name>/project.toml 480 bone=LeftHand=0.25,face 800
python -m mmdance qa     projects/<name>/project.toml 1540 1600      # a spin: hem lag, frames to check
```
- **Retargeting:** the build log reports the IK over-reach frames.
- **Rig stage:** it reports vertex counts per part and the hair chain lengths.
- **Physics:** every collider radius is printed, measured or clamped.

Simulation first: `--until 300` simulates only the first 300 frames, so a parameter change can be
judged in a minute. A full simulation of a 90 s dance takes 15–20 minutes, rendering about
2 hours at 1080p.

Things to check in stills:
- **Skirt passes through the legs in kicks:** lower `stiff_lim` in the middle rows, or enlarge the
  thigh capsules.
- **Skirt looks rigid in turns:** lower `elastic`, or raise `stiff_lim` toward the hem.
- **Fabric jitters against the body:** raise `physics.skirt.absorb` (default 0.85) or
  `physics.substeps`.
- **Feet float in hops:** the motion asks for a longer leg than the character has. A slightly
  smaller `motion.scale` shortens the reach, but it also shrinks the travel across the floor.

## 5. Render
```
python -m mmdance render projects/<name>/project.toml --jobs 2
python -m mmdance encode projects/<name>/project.toml
```
Rendering skips frames that already exist and writes placeholders, so processes can share the
range and a stopped render resumes. Delete the frames folder to re-render from scratch. `encode`
refuses to run while frames are missing or still placeholders.
