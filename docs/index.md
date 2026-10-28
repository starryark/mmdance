---
title: "mmdance: MMD dances on any Mixamo-rigged Blender character"
description: "Open-source Blender pipeline: AI-generated (Tripo, Meshy) or Mixamo characters dance MMD (VMD) motions, with skirt and hair physics, faces, camera and video."
image: /media/claude-chika-kick.jpg
---

**mmdance** makes a Mixamo-rigged character perform a **MikuMikuDance (MMD)** dance in
**Blender**. It works with AI-generated (image-to-3D) characters from Tripo or Meshy, with Mixamo
and AccuRig rigs, or with your own rig mapped by bone name. You give it the character's `.blend`
and an MMD motion package: the VMD dance, the VMD camera, the facial VMD and the song. It retargets
the motion to your rig, simulates the skirt and hair, animates the face, and renders a finished
video with the original camera and music. It runs headless, everything is set in one config file,
and every step is cached by its inputs, so a production rebuilds reproducibly. Code:
**[github.com/starryark/mmdance](https://github.com/starryark/mmdance)** (MIT).

[![A Tripo-generated anime character with long orange hair dances an MMD motion in Blender, kicking one leg out while her simulated white and black ball gown flares](media/claude-chika-kick.jpg)](https://github.com/starryark/mmdance#demo)

*The first production: a Tripo-generated character dances a 94 s MMD motion with the
package's camera, facial track and song, the gown and hair simulated.
[Watch the demo videos on GitHub](https://github.com/starryark/mmdance#demo): this one, and two
characters taking turns in a 15 s meme on a set from another `.blend`, filmed by a camera solved
from the reference video.*

## What it does
- **VMD → Mixamo retargeting.** MMD Tools evaluates the VMD on a proxy MMD skeleton built at your
  rig's joints. The motion is transferred in world space relative to MMD's A-pose, twist bones
  are shared between upper arm and forearm, and the legs are solved with a two-bone IK to MMD's
  foot targets.
- **The MMD camera**, plus custom shots where the original camera doesn't fit your model.
- **Skirt, layered gown, long-hair and tail physics.** Bone chains are laid through the mesh
  (for hair, one per lock if you like) and simulated with a position-based solver: jointed
  chains with angular limits, as in MMD rigid-body skirts and DynamicBone, with body capsule
  colliders and furniture boxes. The result is baked to keyframes.
- **Facial animation** from the VMD morphs, on shape keys or on *painted* faces through expression
  atlases made from the texture.
- **Repairs for auto-rigged meshes:**
  - hands rebuilt from the finger bones;
  - hair ripped free of the clothing;
  - rigid boot weights;
  - cross-side leg weights cleaned up.
- **Stage, EEVEE render** (resumable, parallel) and **video encoding** with the song.
- **Recreating a dance video:** a camera keyed from a track solved from the reference footage, a
  set appended from another `.blend`, motion blur, and two characters taking turns in one video.
- **Rendering elsewhere:** a packed, self-contained copy of the scene, and scripts for headless
  EEVEE on a Linux cloud GPU (RunPod).
- **Your own code on the built character** (a rebuilt face, sleeves, wings, a prop), shared
  between projects by path.

## Quick start
```
python -m mmdance new projects/my_dance
python -m mmdance inspect projects/my_dance/character/character.blend
python -m mmdance build  projects/my_dance/project.toml
python -m mmdance render projects/my_dance/project.toml --jobs 2
python -m mmdance encode projects/my_dance/project.toml
```
Requirements:
- Blender 5.2+ with the MMD Tools extension;
- Python 3.11+ with numpy, scipy, opencv-python, scikit-image, pillow and matplotlib;
- ffmpeg.

## Documentation
- [Walkthrough: a new character or dance](new-character.html)
- [How it works: retargeting, physics, face, render](how-it-works.html)
- [Every config key, with defaults](https://github.com/starryark/mmdance/blob/main/mmdance/defaults.toml)
- [The full example project](https://github.com/starryark/mmdance/tree/main/projects/claude_chika),
  and [the other productions](https://github.com/starryark/mmdance/tree/main/projects)
- [FAQ](https://github.com/starryark/mmdance#faq)
- [llms.txt](llms.txt), a documentation index for LLMs and AI agents

## Common questions
**Can a VMD motion drive a non-MMD model, without converting it to PMX?**
Yes. That is the core of mmdance: the motion is evaluated on a proxy MMD skeleton and transferred
to your Mixamo-named bones. Rigs with other bone names are mapped in `[bones.map]`.

**Does it import PMX or PMD models?**
No. For native MMD models use [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools) or
[SekaiBlender](https://github.com/ShiJieWorld/SekaiBlender).

**How do I add skirt or hair physics to a Tripo or Meshy character for an MMD dance?**
Enable `[skirt]`, `[overskirt]` or `[hair]` in `project.toml` and set the joint heights, which
`inspect` suggests. The chains are simulated and baked; see [How it works](how-it-works.html#physics).

**How do I get blinks and lip sync from the facial VMD?**
Map the VMD morphs (まばたき, あ, い, う, え, お, ...) to shape keys with `face.mode = "shapekeys"`,
or use `face.mode = "atlas"` for a painted face texture. A painted face on a sculpted head is
better rebuilt as geometry, with a mouth opening and eyes in layers; see
[A new character](new-character.html).

**Can I recreate a dance video with the camera moves of the reference footage?**
Yes: `camera.track` keys the camera on every frame from a track file (solved outside mmdance, for
example from the reference video). The
[DreamWings project](https://github.com/starryark/mmdance/tree/main/projects/dreamwings) recreates
a 15 s meme this way, with two characters taking turns on a set from another `.blend`.

**Can it render on a cloud GPU?**
Yes. `python -m mmdance pack` writes a self-contained copy of the built scene; the scripts in
`tools/remote` set up headless EEVEE on a Linux GPU, check that it got the GPU, and split the
frames over several Blender processes. See [rendering elsewhere](new-character.html#5-render).

**Status.** Built for, and verified against, one 94 s production with a Tripo-generated character,
which it reproduces exactly. Since then it has made videos with three Tripo characters (a layered
ball gown; an apron and a tail; wings, a tail and bell sleeves) and two dances, one of them a
motion-capture meme on a set from another `.blend`. Each added opt-in options. Builds were run on
Windows 11 with Blender 5.2, renders on Windows and on a Linux cloud GPU. No characters, motions
or music are distributed.
