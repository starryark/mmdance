# mmdance: MMD dances on any Mixamo-rigged Blender character

[![tests](https://github.com/starryark/mmdance/actions/workflows/tests.yml/badge.svg)](https://github.com/starryark/mmdance/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Blender 5.2+](https://img.shields.io/badge/Blender-5.2%2B-orange.svg)](https://www.blender.org/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](requirements.txt)

**mmdance makes a Mixamo-rigged character perform a MikuMikuDance (MMD) dance in Blender.** It
works with characters from Tripo, Meshy, Mixamo or AccuRig, or your own rig mapped by bone name.
You give it the character's `.blend` and an MMD motion package: the VMD dance motion, the VMD
camera, the facial VMD and the song. It builds the animated scene and renders a finished 1080p
video, headless, from one config file.

If you have an AI-generated or auto-rigged anime character and an MMD/VMD dance you want it to
perform, this is the pipeline for that. It retargets MMD motion to a non-MMD rig, adds skirt and
hair physics, animates the face, and renders with the original camera and music. It handles:

- **Motion retargeting.** The VMD is imported with mmd_tools onto a proxy MMD skeleton built from
  your rig's proportions. It is then mapped onto your bones in world space, with twist bones shared
  between upper arm and forearm. MMD's foot IK is solved by an analytic two-bone leg IK.
- **The MMD camera** (`camera.vmd`), plus optional custom shots for stretches where the original
  camera doesn't suit your model.
- **Secondary motion** for skirts, layered gowns and long hair. Bone chains are laid through the
  mesh automatically and simulated with a position-based solver:
  - jointed chains with angular limits, as in MMD rigid-body skirts and DynamicBone;
  - capsule colliders measured from the body;
  - furniture box colliders and inelastic contacts.
  
  The result is baked to keyframes, so the final scene needs no add-on.
- **Facial animation** from the VMD morph track. It works on shape keys, or on a *painted* face
  texture (common for image-to-3D characters) through expression atlases built from the painting
  itself.
- **Repairs for auto-rigged meshes:**
  - rebuilding fused finger blobs as real hands from the finger bones;
  - ripping hair from clothing;
  - rigid boot weights;
  - cross-side leg weight cleanup.
- **Stage, lighting, render** (EEVEE), resumable parallel rendering, and encoding with the song.
  Picture and sound fade out together.

Everything is generated from your untouched character file by `build.py`. Every stage caches its
results, keyed by its inputs, so a rebuild only recomputes what changed.

## Status
This was built for one production: a Tripo-generated 1 m toon character dancing a 94 s MMD motion
([projects/claude_chika](projects/claude_chika)). The engine (retargeting, camera, chains and
physics, face states, render, encode) is generic and config-driven, and it reproduces that
production's output exactly: every cache, the face atlases and the rendered frames match. The
generic path was also smoke-tested on the same character: the default stage, a follow camera,
shape-key faces, no repairs, and a range starting mid-dance. So far it has only been run on that one
character. Expect to tune the lattice heights and physics for a new outfit. The face atlas needs
measured guide curves for each painted face. Stage builders like the example room are per project.
Tested on Windows 11 only, with Blender 5.2.

## Requirements
- **Blender 5.2+** with the **MMD Tools** extension (Edit › Preferences › Get Extensions ›
  "MMD Tools"; tested with 4.5.14).
- **Python 3.11+** (system) with `numpy scipy opencv-python scikit-image pillow matplotlib`. These
  run the hand and face-atlas builders (Blender's bundled Python lacks them), encoding and QA.
- **ffmpeg** on `PATH`.

```
pip install -r requirements.txt
```

## Quick start
```
python -m mmdance new projects/my_dance          # copies the template
#   character/  <- your rigged .blend (Mixamo bone names, T-pose, Z up, facing -Y)
#   source/     <- motion.vmd, camera.vmd, (facial.vmd), song.wav
python -m mmdance inspect projects/my_dance/character/character.blend   # rig check + heights + suggestions
#   edit projects/my_dance/project.toml
python -m mmdance build  projects/my_dance/project.toml
python -m mmdance stills projects/my_dance/project.toml 100,600,1200 cam,front    # quick check renders
python -m mmdance render projects/my_dance/project.toml --jobs 2
python -m mmdance encode projects/my_dance/project.toml
```
A project is one `project.toml`; [mmdance/defaults.toml](mmdance/defaults.toml) documents every key.
Put machine-specific paths in a `project.local.toml` next to it; it is merged on top and never
committed. See [docs/new-character.md](docs/new-character.md) for the walkthrough and
[docs/how-it-works.md](docs/how-it-works.md) for the methods.

## Layout
| | |
|---|---|
| `build.py` | Blender entry point: runs the stages motion → camera → rig → physics → face → stage and saves the scene |
| `mmdance/` | The pipeline: `motion` (retarget), `camera`, `rig` (chains, weights, repairs), `layers` (gown layer split), `physics` + `solver` (simulation and bake), `face` + `face_atlas`, `hands` + `hand_sdf`, `stage`, `encode`, `config`, `vmd` (parser) |
| `tools/` | `inspect_character`, `stills` (check renders), `physics_qa` (motion / hem-lag metrics), `plot_character` |
| `projects/template/` | Starting point for a new project |
| `projects/claude_chika/` | The full example: config, the room stage builder, notes and limits |
| `tests/` | Unit tests that run in system Python (`python -m unittest`) |

## Assets and licence
The code is MIT licensed. **No characters, motions, music or renders are included or redistributed.**
MMD motions and songs carry their authors' terms. Read and follow them, credit the authors, and
check whether derivative videos are allowed before you publish one. The `.gitignore` keeps `.blend`,
`.vmd`, audio, video, images and caches out of the repository.

## FAQ

**How do I make a Tripo, Meshy or Mixamo character dance an MMD motion in Blender?**
- **Character:** export it rigged with Mixamo bone names, in a T-pose, Z up and facing -Y, and
  save it as a `.blend`.
- **Motion:** get an MMD motion package with the dance `.vmd` and, ideally, `camera.vmd`, a
  facial `.vmd` and the song.
- **Run it:**
  1. `python -m mmdance new projects/x` starts a project.
  2. `python -m mmdance inspect <character.blend>` checks the rig and suggests settings.
  3. `build`, `render` and `encode` make the video.

  See the [walkthrough](docs/new-character.md).

**Can a VMD motion drive a non-MMD model, without converting it to PMX?**
Yes, that is what mmdance is for. The VMD is evaluated by MMD Tools on a proxy MMD skeleton built
at your rig's joint positions. The resulting world-space rotations are transferred to your bones
relative to MMD's A-pose (`motion.arm_angle`, 37° by default). MMD's foot IK is solved with an
analytic two-bone leg IK, and `motion.scale` converts MMD units to metres; by default it is worked
out from the leg length.

**Does it import PMX or PMD models?**
No. For native MMD models use [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools) or
[SekaiBlender](https://github.com/ShiJieWorld/SekaiBlender). mmdance is for characters that are
*not* MMD models.

**My rig doesn't use Mixamo bone names (VRoid/VRM, Unreal mannequin, a custom rig).**
- Set `[bones] prefix`, or map each Mixamo role to your bone in `[bones.map]`, for example
  `Hips = "pelvis"`.
- The rest pose must be a T-pose facing -Y.
- Map the deform bones. Control rigs such as Rigify's are not driven directly.

**How do I add skirt, dress or long-hair physics to an auto-rigged character for the dance?**
- Enable `[skirt]`, `[overskirt]` (a second, open gown layer) and/or `[hair]`, and give the joint
  heights (`rows_z`). `inspect` suggests them.
- Bone chains are laid through the mesh, simulated with a position-based solver (jointed chains
  with angular limits, body capsule colliders, furniture boxes), and baked to keyframes.
- Tuning is described in [how it works](docs/how-it-works.md#physics).

**How do I get blinking and lip sync from the facial VMD?**
- `face.mode = "shapekeys"` with a `map` from VMD morph names (まばたき, あ, い, う, え, お, 笑い, ...)
  to your shape keys.
- Painted-face characters (common from image-to-3D) have no shape keys. For those, `face.mode =
  "atlas"` builds blink, smile and mouth tiles from the face texture itself.

**The MMD camera clips into my character or frames it badly.**
Add `[[camera.shots]]`: a camera of your own over a frame range, which replaces the MMD camera
there. Without any `camera.vmd`, a front camera follows the dancer.

**My generated character's hands are fused blobs.**
`[hands] enabled = true` rebuilds them from the finger bones (implicit surface + marching cubes) in
the hands' material slot, weighted with joint blends.

**Does it run headless or on a render server?**
Yes. Everything runs through `blender -b`. It has been tested on Windows 11 with an EEVEE GPU
render. `render.engine = "CYCLES"` is accepted but untested, and the example's toon shaders are
EEVEE-only.

**How long does it take?**
For the 94 s example on the development machine:

| Step | Time |
|---|---|
| First build (physics simulation 15–20 min) | about 25 min |
| Rebuild from cache | about 4 min |
| Render at 1080p with two Blender processes | about 2 h |
| Encode | under a minute |

**Where do MMD motions come from, and can I publish the result?**
Motion authors share packages on sites such as BowlRoll and on niconico. Each package has its own
terms for use, credit and posting videos. mmdance ships no motions and no music; check the terms
before publishing a video.

**Can an AI coding agent use this repo?**
Yes. [AGENTS.md](AGENTS.md) has the commands, tests and conventions, and [llms.txt](llms.txt)
indexes the documentation for LLMs.

## Related work
- [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools): imports PMX/PMD models and
  VMD motions into Blender; mmdance uses its VMD importer.
- [CosMMD](https://github.com/CyclopsRay/CosMMD): one photo → Tripo 3D → a 12 s MMD dance clip,
  agent-guided. It focuses on preserving the character's look; it has no cloth physics, facial
  animation, camera or audio.
- [Blender VMD Retargeting](https://github.com/butaixianran/Blender-Vmd-Retargeting): an add-on
  that retargets VMD body, facial and camera motion onto Daz and Character Creator rigs.
- [SekaiBlender](https://github.com/ShiJieWorld/SekaiBlender): a Blender build for native PMX
  models, with MMD IK and Bullet physics.
- Bone-chain physics add-ons (Wiggle, Spring Bones and others) provide interactive secondary
  motion. mmdance bakes its own simulation, so builds are reproducible and run headless.
