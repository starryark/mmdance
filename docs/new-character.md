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

**Check what moves with what.** mmdance finds the hair and the skirt by material, and the legs
and a tail as separate mesh pieces. Auto-riggers get both wrong in ways a still at rest doesn't
show. The ChatGPT model (`projects/chatgpt_chika`) needed all of these repairs. A retarget-only
build showed the wrong weights and the spikes as soon as she moved:
- **Parts weighted to the wrong bones.** The tail was weighted to the thighs and a toe, the wings
  to the arms and head, the sleeves to the arms with patches of thigh weight at the hem. The
  Deepseek tail followed one thigh too.
- **Parts with the wrong material.** The model's hair and dress were the same colour, so a
  texturing pass split them by position: 2,700 faces of hair locks carried the dress material,
  and the wing roots the hair material.
- **Fused parts.** The tail was fused to the body. A sleeve hem and the wing membranes touched the
  skirt, so the skirt's motion pulled them into long spikes.
- **Parts with no bones of their own** (wings, sleeves) ride whatever they are weighted to.

Repair these in the model: give each part its own material, cut the tail and anything touching
the skirt free, and give wings and sleeves bones. mmdance then rigs the tail (`[tail]`), and
project code can move the rest; see `projects/chatgpt_chika` (`sleeves.py`, `wings.py`). An
image-to-3D face may also carry hair: projected from a concept sheet, the bang strands are painted
on the skin under the 3D bangs and show as lines across the forehead and eyes once the head
turns.

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
For a layer covering only part of the skirt, such as an apron, give the arc it hangs in
(`phi_range`, degrees, 0 at the front) and the height it ends above (`zbottom`): bows and trims
sewn on the skirt below it then stay on the skirt.

**Tail** (`[tail]`): a tail that is its own mesh island gets two side-by-side bone chains along
it, rooted on the hips. `seed` is any point near the tail. The joints follow the surface distance
from the end nearest the hips, so a curled tail works; `pinned_rows` joints inside the body ride
the hips rigidly. Its physics is in `[tail.physics]` and it is kept outside the skirt. `sway`
adds a slow swish on top; give it a period of a whole number of the song's beats.

**Hair** (`[hair]`):
- `material` is required.
- `rows_z` run from just below the head to the hair tips.
- `phi_range` is the arc round the head that has long hair, with 0 at the back.
- `rip_below` should sit a little below the nape.
- `adopt_head_islands`: auto-riggers sometimes give hair curls the clothing material. Islands
  without hair faces whose vertices follow the head bone then join the hair chains.
- `mode = "locks"` for long hair that falls apart into separate locks or curls: one chain per
  lock (a wide sheet of fused curls gets one per `lock_width` degrees), not linked to the next
  lock, so each swings on its own, as on hand-rigged MMD and game models. Give it jointed-chain
  physics (`[physics.hair] relative = true`, with `elastic` and `stiff_lim` per joint).

**Other sizes:** for a character H metres tall, multiply these by H:
- the heights in `[skirt]`, `[hair]` and `[legs]`;
- `physics.skirt.radius` and `physics.overskirt.radius`.

The physics stiffnesses are ratios and need no scaling; gravity follows `motion.scale`
automatically.

**Smoothing.** `smooth_frames` on a physics section (skirt, overskirt, hair, tail) low-pass
filters the result in the root bone's frame: contact jitter goes, the swing stays. It is applied
after the simulation, so changing it needs no resimulation.

**Hands and fingers.** If finger poses from the motion look wrong (thumbs flat along the
fingers, a hand heart that doesn't close), set `motion.thumb_rest` to a standard MMD hand's rest
thumb direction, and `motion.hands_apart` to spread the wrists over a frame range when the
hands are larger than the motion's model and their fingers cross.

**Repairs** (`[fixes]`) are opt-in, for errors auto-riggers make: hair/cloth seams pulled by the
arms, waist vertices that follow the thighs, weights that bleed between legs that touch, boots that
crumple. Turn one on only when you see the problem in a still.

**Hands** (`[hands]`): use these only if the hands are fused blobs and have their own material
slot. The replacement is a clean stylised hand built from the bones. `skin_color` sets its flat
colour. If the hands share their material with other skin (neck, chest), set `select = "wrist"`
so only the faces past the wrists are replaced, and `skin_uv` to a clean skin spot of the
texture: the new hands take that texel and the material keeps its texture. If the rig's hand
bones differ left to right, set `scale` so both hands get the same size. Auto-riggers often space
a finger's three joints evenly and crowd the knuckles, so fingers bend in the wrong places and
grow together. `phalanges = [1.0, 0.62, 0.55]` re-places the joints at drawn-hand proportions (the
tips stay), and `spread` widens the knuckle row. Compare the rig's knuckle span with its palm
length; on an MMD model it is about 0.64. Both act on the rig before the motion is retargeted.

**Face** (`[face]`):
- `"shapekeys"` with a `map` from VMD morph names to your shape keys. VMD morph names are Japanese:
  `python -m mmdance vmd facial.vmd` lists them.
- `"atlas"` for a painted face. Measure the guide curves on the face texture in pixels:
  - `lash_top` and `lash_bot`: the upper and lower edges of the painted lash band;
  - `lower`: the lower lid line;
  - the mouth's centre and a rectangle round it.

  10–13 points per curve, from the inner to the outer corner, are enough. Open the texture in an
  image editor with a pixel grid and check the result with `textures/atlas_eyes_preview.png`.
  `lids = "inpaint"` paints the eye out of the texture before drawing the lids: softer lids, and
  hair strands drawn across the eye stay in front.
- **Look at the facial track first.** `python -m mmdance vmd facial.vmd` lists each morph with
  its range and how often it is above 0.5. Hand-keyed MMD tracks are usually fine. Tracks made from
  motion capture (ARKit-style names next to a few MMD ones) can be wrong. The DreamWings capture
  read the dancer's squinting grin as closed eyes: ウィンク was above 0.5 on 96 % of its keys. Write
  a cleaned track then; the face section of `projects/dreamwings/README.md` describes one (open
  eyes with blinks, the capture's mouth openings, a light smile between them).

**A painted face on a sculpted head.** Image-to-3D generators (Tripo) paint the face over a
realistic sculpt: a nose, lips with a mouth slit, eye sockets, often in thirty separate pieces
(eyeballs, lids, lips, the nose tip). The atlas redraws the features, but the sculpt still shows:
the outline shell catches its creases, drawing a second mouth under the painted one and lines in the
sockets, and the shading follows its relief. Anime character models are built the other way round.
The mouth is geometry: an opening, the inside of the mouth, teeth and tongue, moved by shape keys
for あ い う え お. The eyes are layers (an eyeball under the lids), and the inner face has no
outline. `projects/claude_chika_v3/face_rebuild.py` rebuilds a painted face like that from a
stage builder's `finish()`: it removes everything inside the face's outline and fills it with a
smooth surface. It cuts the mouth, layers the eyes, makes the textures from the painting
(`face_textures.py`) and keys the shape keys from the facial track; set `face.mode = "none"`.
Before you start, look at the face material's pieces: some may carry other materials, and where
one painted eye is damaged, the other can be mirrored about the face's symmetry plane.

**Camera:**
- `camera.vmd`: the MMD camera. Each MMD motion usually ships one tuned for a standard model.
- `[[camera.shots]]`: replaces it over a frame range when it doesn't suit your model, for instance
  when the lens ends up inside a big skirt.
- A dance without an MMD camera: a stage builder's `finish()` can key a camera of its own.
  `projects/dreamwings` solves one from the dance's reference video, frame by frame.
- `camera.resolution`: the output size.

**Stage:**
- `builder = "default"` gives a floor and a flat backdrop.
- For a set, write a builder: copy the shape of `projects/claude_chika/room.py`. Furniture the
  dance touches should also be returned from `colliders(cfg)` as boxes `(x0, x1, y0, y1, top)`.
- A builder can also define `finish(collection, cfg)`, run after the lights and render settings,
  for the project's own look: `projects/deepseek_chika/room.py` uses it for sunlight through the
  windows, haze, a sunlit toon tone and lighting cues that follow the song.
- A set from another `.blend` can be appended and scaled around the dance:
  `projects/dreamwings/lobby.py`, described in [how it works](how-it-works.md#stage-and-render).
  Keep `render.view_transform` at `Standard` for the toon colours, or use `Khronos PBR Neutral`
  if the set needs its highlights rolled off. AgX washes the toon colours out.

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
- **A stray line on the face:** render the same still with the body's outline modifier turned off.
  If the line goes, it is the outline shell at a crease of the sculpt, not the texture: zero the
  outline weight there, or take the crease out of the geometry.
- **The face at angles:** a face that is right from the front can fail in a 3/4 view or from below.
  Check those angles and several expressions, including in-betweens: half a blink with a vowel.
- **Hair streams out like ribbons on a new dance:** hair settings are per dance as well as per
  character. Compare `qa`'s hair move/frame median with a dance that looked right: on the
  DreamWings meme Claude's locks moved a median 13 cm a frame against 8 on the Chika dance (12
  after tuning). Raise `drag`, `elastic` and `smooth_frames`: compare the `[physics.hair]` of
  `projects/dreamwings/claude/project.toml` with `projects/claude_chika_v3`'s.

## 5. Render
```
python -m mmdance render projects/<name>/project.toml --jobs 2
python -m mmdance encode projects/<name>/project.toml
```
Rendering skips frames that already exist and writes placeholders, so processes can share the
range and a stopped render resumes. Delete the frames folder to re-render from scratch. `encode`
refuses to run while frames are missing or still placeholders.

**Motion blur** (set by a stage builder's `finish()`; shutter 0.5 frame matched the whip pans of
the DreamWings reference) makes EEVEE spend most of a frame evaluating the scene on the CPU:
about 21 s a frame per process there. Run more processes per GPU; nine shared one L40S.

**Rendering on another machine.** Render a self-contained copy of the built scene:
- pack every image into it and make the remaining paths absolute;
- drop the song's preview strip (`encode` adds the song afterwards);
- keep `use_overwrite` off and placeholders on, and write the frames next to the `.blend`.

Then check that nothing still points outside the file. On a Linux cloud GPU (RunPod), headless
EEVEE needs the driver's graphics libraries: start the container with
`NVIDIA_DRIVER_CAPABILITIES=all` and install the EGL, GL and Vulkan client libraries. Start the
Blender processes about 20 s apart, since the first one compiles the shaders. Afterwards check
every frame: the count, no empty or placeholder files, and checksums after the download.

**Two characters in one video** (DreamWings: Claude, then ChatGPT): give each character its own
project on the same frame range, camera track and song, render both, and cut between their frame
folders at the swap when encoding.

**Copies for sharing.** `encode` makes the full-quality video. The productions also made a 720p
copy and one under 10 MB with ffmpeg: scale to 1280 × 720 with lanczos; for the size limit, a
two-pass H.264 encode at the bitrate that fits (680 kbit/s for 94 s, with 112 kbit/s AAC).
