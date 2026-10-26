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
| `body_track_<key>.npz` | world matrices of the 24 tracked body bones per frame | the above plus the rest pose |
| `hands_<key>.npz` | the generated hand meshes with part labels | hand bones and `[hands]` |
| `sim_<key>.npz` | particle positions of every lattice per frame | body track, lattice, `[physics]`, colliders |
| `lattice.npz` | the chain layout from the rig stage | (rewritten every build) |

When you edit the config, the stages that depend on the change recompute on the next build and the
rest are reused. `--resim` and `--resample` force a recompute. The face atlases in
`paths.textures` record their key in `face_atlas.json` the same way.

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
- **Weights** come from each vertex's (angle, height) position on the lattice: bilinear across
  columns and rows. Above the first joint they blend into the root bone. Only the chain vertices
  are re-weighted; the body's weights are left alone, except for the opt-in `[fixes]`.
- **Hair rip.** Edges where hair faces meet cloth faces below `hair.rip_below` are split, so the
  hair can swing without dragging the dress along.

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

## Stage and render
`stage.builder = "default"` gives a floor disc under the world colour. A project builder is a
Python file defining `build(collection, cfg)`, and optionally `colliders(cfg)` to return furniture
boxes for the physics; see `projects/claude_chika/room.py`.

The render is EEVEE with ray tracing, a fog-glow compositor pass and PNG output.
`use_overwrite = False` and placeholders are on, so several Blender processes can share the frame
range and an interrupted render resumes. `encode` muxes the frames with the song. If the song is
longer, it holds the last frame, then fades picture and sound out together.
