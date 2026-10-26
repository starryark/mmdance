# mmdance

Put an MMD dance on your own character in Blender: a headless, config-driven pipeline that takes a
**Mixamo-rigged character** (Tripo, Meshy, Mixamo, AccuRig, or your own) and an **MMD motion
package** (VMD dance, camera, facial track and song) and produces the animated scene and a finished
1080p video. It handles:

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
character. Expect to tune the lattice heights and physics for a new outfit. The face atlas needs measured guide curves for each
painted face. Stage builders like the example room are per project. Tested on Windows 11 only, with
Blender 5.2.

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
