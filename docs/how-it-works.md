# How it works

`build.py` opens the untouched character file in Blender, runs six stages and saves a new scene.
Each stage reads the merged config (`defaults.toml` < `project.toml` < `project.local.toml`).

```
motion  ->  camera  ->  rig  ->  physics  ->  face  ->  stage  ->  (render, encode)
retarget    MMD cam     chains,   simulate,    morphs    set, lights,
the VMD     + shots     weights,  bake         -> tiles  render settings
                        repairs                or keys
```

## Caches
Everything slow is cached in `paths.cache`. Each file name carries a hash of its inputs:

| file | contents | key |
|---|---|---|
| `proxy_<key>.npz` | the VMD evaluated on the proxy skeleton (world rotations and positions per frame) | VMD content, scale, arm angle, frame range, proxy layout |
| `body_track_<key>.npz` | world matrices of the 24 tracked body bones per frame | the above plus the rest pose, and `motion.thumb_rest` / `hands_apart` when set |
| `hands_<key>.npz` | the generated hand meshes with part labels | hand bones and `[hands]`, except the keys that only change how the hands are merged (`select`, `wrist_margin`, `skin_uv`) or the bones (`phalanges`, `spread`: the bones are in the key) |
| `sim_<key>.npz` | particle positions of every lattice per frame | body track, lattice, `[physics]` and `[tail]` (without `smooth_frames` and `tail.sway`, applied after the simulation), colliders |
| `lattice.npz` | the chain layout from the rig stage | (rewritten every build) |

When you edit the config, the stages that depend on the change recompute on the next build and the
rest are reused. `--resim` and `--resample` force a recompute. A run with `--until N` never writes
the simulation cache, so a partial run cannot pass for the full one. The face atlases in
`paths.textures` record their key in `face_atlas.json` the same way: the painting's content and
`[face.atlas]`.

Options added after a cache was made enter its key only when they are set (`thumb_rest`,
`hands_apart`, `[tail]`, a non-default `face.atlas.lids`), so existing projects keep their caches.

## Motion
MMD motions rotate bones relative to MMD's own rest pose: an A-pose with the arms about 37° below
horizontal (`motion.arm_angle`). The motion stage builds a proxy skeleton with MMD bone names at
your rig's own joint positions, with the arms posed in that A-pose. mmd_tools then imports the VMD
onto the proxy, keeping its Bézier interpolation, IK targets and centre/groove bones.

Every frame, the proxy's world-space rotation deltas are copied onto your bones, relative to the
same A-pose:
- **Twist bones** (腕捩, 手捩) are shared half-and-half between the upper arm and the forearm.
- **Legs** are solved analytically. The thigh and shin are placed to reach the proxy's foot-IK
  target (足ＩＫ), and the knee bends toward the proxy thigh's forward direction. The foot is then
  aimed along the IK bone's toe direction (つま先ＩＫ).
- **Thumbs** (`motion.thumb_rest`). MMD thumb keys are authored for a standard MMD hand's rest
  thumb. An auto-rigged thumb often rests flatter, along the index finger, and then lands wrong in
  a fist or a pointing hand. Given that rest direction in the hand's own frame, every thumb
  thumb bone first turns from the rig's rest thumb to that direction, then takes the motion's
  rotation.
- **Hands that should touch** (`motion.hands_apart`). Hands larger than the motion's model cross
  where the original's fingertips meet, as in a closing hand heart. Over a frame range, with
  smooth ramps, the wrists are spread sideways by a two-bone arm IK.
- **Finger joints** (`hands.phalanges`, `hands.spread`, with `[hands]` on). Before anything is
  retargeted, each finger's joints are moved to drawn-hand proportions along the old finger,
  tips kept, and the knuckle row is widened. The proxy, the MMD finger keys and the rebuilt hands
  then all use the new joints.

`motion.scale` converts MMD units to metres. Auto mode takes your leg length over 9.42, a standard
MMD leg in MMD units. When the motion asks a leg to reach further than its length, the reach is
clamped; the build log counts the frames where that happened. Hops in the source then lift the
foot a little.

## Rig: chains and weights
- **Lattice.** Columns sit round a vertical axis (`skirt.axis`, `hair.axis`), and rows sit at
  fixed heights (`rows_z`). Each column becomes a bone chain parented to the hips (skirt) or
  head (hair). The joint positions come from the mesh:
  - skirt: the inner surface of the fabric in each angle/height bin, so legs collide with the
    inner layer;
  - hair: the middle of the hair mass in each bin.

  Hair chains stop where the hair ends (`min_count`).
- **Gown layers** (`[overskirt]`, `layers.py`). Each skirt vertex is tested for a layer of the
  same skirt beneath it, by casting a ray inward toward the axis. Vertices that have one belong to
  the outer layer. A majority vote over the mesh cleans up the labels, and a soft band blends
  weights across the folds where the layers meet. The outer layer gets its own panel chains,
  ordered round the back from the front opening.
  `phi_range`/`zbottom` limit the outer layer to an arc and height (an apron).
- **Tail** (`[tail]`). The tail's island is found from a seed point and taken out of the skirt.
  Surface (Dijkstra) distance from the end nearest the hips sets the joints at equal steps along
  it, at the centroid of each distance band; two columns sit either side along the normal of the
  tail's plane, so the bones carry its twist. Weights blend along the tail and across the columns.
- **Weights** come from each vertex's (angle, height) position on the lattice: bilinear across
  columns and rows. Above the first joint they blend into the root bone. Only the chain vertices
  are re-weighted; the body's weights are left alone, except for the opt-in `[fixes]`.
- **Hair locks** (`hair.mode = "locks"`). Below `split_z` the hair mesh's connected pieces are
  its locks; each gets a chain (wide ones several), joints every `joint_step` at the centroid of
  the lock's vertices. Chains of different locks are not linked by ring constraints; their bones
  take their side axis from the head. Weights follow the vertex's own lock, smoothed over the
  surface.
- **Hair rip.** Edges where hair faces meet cloth faces below `hair.rip_below` are split, so the
  hair can swing without dragging the dress along.
- **Hands** (`[hands]`, `hand_sdf.py`). Fused finger blobs are replaced by a hand built from the
  finger bones: an implicit surface of a palm, a thumb mound and separate tapered fingers that
  join the palm but never each other, meshed with marching cubes. Each vertex knows its part and
  its place along it, which gives joint-blended weights. The old hands are every face of the
  hands' material, or (`select = "wrist"`, for a material shared with the neck or arms) only the
  faces past the wrists. Then `skin_uv` points the new hands at one skin texel of the shared
  texture.
- **Vertices without weights** (`fixes.unweighted`, on by default) take the weights of the
  nearest weighted vertex. Otherwise they stay at the rest pose and streak across the frame.

## Physics
`solver.py` is a position-based (PBD) solver in numpy. The particles are the chain joints, and
each lattice's root row is pinned to its body bone. Each frame runs `physics.substeps` substeps,
with body bones interpolated in between. Each substep runs:

- **Inertia and gravity.** Inertia comes with drag. Gravity is *rest-equilibrium*: while the body
  is upright, only the change of gravity relative to the body acts, so the modelled rest shape is
  the equilibrium. As the body tips over (lying down, deep bends), real gravity and drape take
  over.
- **Joints** (`relative = true`). Every joint springs toward its rest direction relative to its
  *simulated* parent (`elastic`, per row). A hard angular limit applies: a joint may leave that
  direction by at most a chord of `stiff_lim` × its segment length. So the hem lags the hips in a
  spin but can never invert or wind up. Hair uses a softer goal spring toward the rest shape
  carried by the head (`relative = false`, `goal`).
- **Constraints:**
  - inextensible chains;
  - ring constraints between neighbouring columns, which may stretch and squash within
    `ring_min`–`ring_max`;
  - bending along the chains and round the rings;
  - a rate-limited tether to the goal.
- **Collisions:**
  - Capsules on the body. Their radii are measured from the mesh and shrunk until no particle
    starts inside one.
  - Lattice edges are tested too, through their midpoints, so a limb cannot slip between two
    particles.
  - A particle that crosses a limb is sent back out on the side it came from. Where the skirt
    surface is reliable, it always goes to the outside of the fabric (`outer_rule`).
  - The floor, and rounded box colliders for furniture.
  - Hair and panels are also kept outside the skirt surface while the body is upright.
- **Smoothing** (`smooth_frames`, after the simulation): a Gaussian low-pass of each lattice in
  its root bone's frame, before baking.
- **Inelastic contacts** (`absorb`). The displacement a collision causes is removed from the
  velocity, so fabric pushed by a knee doesn't bounce.

`physics.preroll` frames on the first pose let everything settle before the dance starts. The
result is baked as rotation and location keys on the chain bones: each bone's frame comes from its
lattice neighbours. Check it with `python -m mmdance qa project.toml [from to]`. It reports how
much the particles move relative to the body, and lists high-jerk frames to step through: fast
spins show up there as well as real pops. Given a spin's frame range, it also measures how far the
hem trails the hips.

## Face
- **`mode = "shapekeys"`** keys shape keys from the VMD morphs listed in `face.shapekeys.map`, with
  linear interpolation like MMD.
- **`mode = "atlas"`** is for painted faces. The VMD morphs become per-frame tile indices:
  - blink and wink → open, 1/3, 2/3 or closed per eye;
  - smile → ^^;
  - vowels あいうえお → three openings each;
  - ワ → a wide open mouth;
  - にやり → a smirk.

  `face_atlas.py` builds the tiles from the painting itself. The painted lash band slides down to a
  target line between its rest position and the lower lid, keeping its thickness. The lid area it
  uncovers is filled with skin colour sampled from just above it. Mouth shapes are drawn with a
  gradient interior, tongue and teeth.

  Each tile's alpha is a feathered difference mask, so only pixels that change are composited. The
  face material samples the atlases through UV maths driven by integer object properties
  (`face_eyeL`, `face_eyeR`, `face_mouth`). Mouth states are held at least `mouth_min_hold`
  frames, so the lips never flicker.
- **A face rebuilt as geometry** (project code, `projects/claude_chika_v3/face_rebuild.py`). The
  atlas suits a painted face on a smooth head. On a sculpted one the outline shell and the shading
  show the sculpt under the drawing. The rebuild works in the painting's front projection, so every
  new part keeps the painting's UVs:
  - The face polygons and the pieces inside their outline are replaced by a smooth surface: the
    old depth blurred, a little of the nose kept, and the old surface at the outline so it meets
    the head. Its shading normals come from an ellipsoid round the head, and it has no outline
    weight inside.
  - The mouth is an opening with a lip-coloured strip round the rim and rings round it. Behind it
    sit the inside of the mouth, the upper teeth and the tongue. Shape keys for あ い う え お, ワ and
    にやり move the rim, the rings (more below, as a jaw would), the teeth band and the tongue.
  - Each eye is three layers over the surface: the eyeball, an upper lid carrying the lash band and
    a lower lid carrying the lid line. Closing brings the lash band down over the lower lid. 笑い
    lowers it and raises the lower lid behind it into ^^.
  - The facial track keys the shape keys directly (`face.mode = "none"`).

## Stage and render
The stage runs in this order:
1. **The set.** `stage.builder = "default"` gives a floor disc under the world colour.
   `"set"` appends a set made in another `.blend` (below). A project builder is a Python file
   defining `build(collection, cfg)`, and optionally `colliders(cfg)` to return furniture boxes for
   the physics; see `projects/claude_chika/room.py` and `projects/deepseek_chika/room.py`.
2. The key sun, the fog glow and the render settings.
3. **Project steps** (`stage.steps`): Python files run on the built character, each defining
   `run(cfg, collection)`: the face rebuild, the cap prop, the sleeve simulation, the wing beat.
   Paths are relative to `project.toml`, so a project uses another's file instead of copying it
   (`projects/dreamwings/claude` runs `../../claude_chika_v3/face_rebuild.py`). Project code reads
   the body track and simulation through `physics.body_track()` and `physics.sim_key()`, never by
   rebuilding the cache keys itself.
4. Cleaned textures (`stage.textures`) and the lining of single-layer fabric (`stage.lining`): its
   backfaces show the print multiplied by a darker tint, not the outside print.
5. The dancer's place and heading from the camera track (`camera.track_dancer`). Object keys on the
   rig come last: until here the rig object stays at the origin, because the rig stage joins the
   rebuilt hands into the body through world matrices.
6. **The key light follows the camera** (`stage.key_follow`), if set. On a toon character the key
   also drives the face shading (a driver reads the sun's `rotation_euler` x and z), so it is keyed
   from above the camera and turned round from it, on every frame, and keeps y at 0.
   `stage.key_link` lights only the character with it (light linking); the set keeps its own
   lights.
7. The builder's `finish(collection, cfg)`, for the project's own lighting and look (sunlight
   through the windows and lighting cues in the room).

**A set from another file** (`builder = "set"`, `[stage.set]`, used by `projects/dreamwings`):
- The `.blend`'s collections are appended, not linked, and hang on one empty that scales, turns
  and places them around the dance. A set modelled at real size is shrunk by 1/1.6 so that the 1 m
  characters read as 1.6 m. Point, spot and area lights then lose power by the scale squared, and
  their soft shadow size by the scale, so the set is lit as before. Sun and world are unchanged.
- **The spot.** Place the dance where the hips' path (plus the arms' reach) and the camera's path
  stay clear of the furniture over the whole dance. DreamWings ranked every spot and turn by its
  clearance from the set's furniture, drawn as boxes on the floor plan.

**A camera from a track** (`camera.track`): an `.npz` with the camera's location and rotation on
every frame, its lens and sensor, made outside Blender (DreamWings solved one from the meme's
reference video). With `camera.track_dancer` the rig object is keyed from the same file. A motion
capture keeps the dancer facing the lens, and this turns her back with the real camera. The
simulation runs in the rig's own frame, so it does not feel that turn; keep it slow.

The render is EEVEE with ray tracing, a fog-glow compositor pass and PNG output. The view
transform is `Standard` (`render.view_transform`), so toon colours render as painted. AgX,
Blender's default, washes them out. A set lit for AgX, with bright windows and lamps, can use
`Khronos PBR Neutral`, which keeps the painted colours and still rolls off the highlights.
`render.motion_blur` (the shutter in frames) suits fast camera whips. It makes EEVEE CPU-bound by
the scene evaluation, so render with more processes per GPU.
`use_overwrite = False` and placeholders are on, so several Blender processes can share the frame
range and an interrupted render resumes. `python -m mmdance pack` writes a self-contained copy of
the built scene for another machine (`tools/remote` has the scripts for a Linux GPU).

`encode` muxes the frames with the song. If the song is longer, it holds the last frame, then
fades picture and sound out together; `encode.song_end = "cut"` ends with the dance instead.
`[[encode.parts]]` take the frames from another project's render from a frame on (two characters
taking turns), and `encode.copies` writes smaller copies (720p at a CRF, or two-pass at a bitrate
or under a size).
