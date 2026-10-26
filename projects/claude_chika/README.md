# Example: Claude — Chika Dance

The project this pipeline was built for: a Tripo-generated, toon-shaded anime character (1 m tall,
Mixamo rig, a layered ball gown and long hair) dancing akomni's MMD motion **チカっとチカ千花っ♡**
([niconico sm34597101](https://www.nicovideo.jp/watch/sm34597101)), with that package's camera,
facial track and song, in a rebuilt version of the original video's student-council room.
94 s at 1920×1080, 30 fps.

No assets are included. To rebuild it you need the character file and the MMD motion package
(see [credits](#credits)); put them where `project.toml` expects them, or point to them from a
`project.local.toml` next to it:

```
python -m mmdance build  projects/claude_chika/project.toml
python -m mmdance render projects/claude_chika/project.toml --jobs 2     # ~2 h on one GPU (EEVEE, 48 samples)
python -m mmdance encode projects/claude_chika/project.toml
```

## What each part does here
| | |
|---|---|
| `project.toml` | Everything character- and dance-specific: lattice heights, the measured face guides, weight repairs, the intro shot |
| `room.py` | The student-council room as original geometry (stage builder): walls, windows, curtains, harlequin floor, the desk she lies on and the sofa she sits on, which are also cloth/hair colliders |

**Gown: layered, jointed fabric instead of one rigid cone.**
- *Two layers.* A raycast pass splits the gown into the inner pleated skirt and the open-front
  overskirt, made of side and back panels. The panels get their own 21 bone chains and simulate on
  top of the skirt, kept outside it. They are only loosely tied to each other, so each panel
  swings by itself.
- *Jointed chains.* Each joint springs toward its rest angle relative to its simulated parent,
  with a hard angular limit, under real gravity (as MMD rigid-body skirts and DynamicBone do).
  The hem trails the hips in turns (measured 30–60° behind in the spins) and cannot invert or wind up.
- A 24 × 9 lattice, bending stiffness down each chain, and inelastic contacts: a limb pushing the
  fabric does not make it bounce. Rounded-box colliders give the desk and sofa edges a smooth push.

**Hands rebuilt.** Tripo's hands were fused finger blobs that no weighting could turn into
gestures. New hands are generated from the rig's own finger bones: an implicit surface with a palm,
a thumb that melts into the palm and separate tapered fingers, meshed with marching cubes, weighted
per part with short blends at the joints and hidden under the sleeve cuffs.

**Boots.** Re-weighted as stiff pieces: the shaft follows the shin, the foot the foot bone, the toe
cap the toe bone, with short blends at knee, ankle and toe, so the boot does not crumple when the
foot points.

**Face.** Expressions are made the way Live2D riggers animate painted eyes: blinks slide the painted
lash band down over a lid filled with skin colour sampled right beside it (two in-between steps, a
closed state and a ^^ smile). Every overlay carries only the pixels that change, so no patches show.
Grey halos left by the original texture projection at the left eye's corner are repainted in a
cleaned copy of the face texture. Mouth shapes are redrawn with a shaded opening, tongue and teeth.

**Cameras.** The MMD camera is used throughout except frames 0–109: there the original's opening shot
would sit inside the gown, so a separate camera looks down on her at the desk (`[[camera.shots]]`).
The video holds the final pose for the last 2.1 s of the song and fades out with it.

## Limits
- On high kicks the gown tents over the knee and the stocking shows below the hem; the leg never
  goes through the fabric.
- The original's white beret prop, which she puts on mid-dance, is not recreated. Her hands mime
  with nothing in them.
- A few hops ask the leg to reach 1–2 cm further than its length, so the foot leaves the floor slightly.
- Finger poses switch in 1–2 frames, as in the source motion.
- Eye-direction and angry-brow morphs are not used: the eyes are painted, and the brows sit under the bangs.

## Credits
- Motion, camera, facial track: akomni — [bowlroll 189318](https://bowlroll.net/file/189318);
  original video [sm34597101](https://www.nicovideo.jp/watch/sm34597101). The original stage
  (niconico Seiga im6619632) is no longer available; `room.py` is our own geometry modelled on the video.
- Song: チカっとチカ千花っ♡ (Kaguya-sama: Love Is War).
- None of these are distributed here. Use them under their authors' terms.
