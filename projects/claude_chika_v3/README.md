# Claude — Chika Dance, v3 / v4

The [claude_chika](../claude_chika) production redone with what the
[deepseek_chika](../deepseek_chika) production taught, plus anatomical hands and (v4) a face rebuilt
as 3D anime faces are made. `claude_chika` stays as it was: it is the pipeline's regression standard.

```
python -m mmdance build  projects/claude_chika_v3/project.toml        # ~28 min with the simulation, 15-20 cached
python -m mmdance render projects/claude_chika_v3/project.toml --jobs 2   # ~2.5 h
python -m mmdance encode projects/claude_chika_v3/project.toml
```
The stage takes about 10 minutes of a cached build (the face rebuild and the room), against 1 for
claude_chika.
[dreamwings](../dreamwings) runs this character setup on another dance.

| | |
|---|---|
| `project.toml` | claude_chika's settings, plus: hair per lock, the calmer gown, `hands.phalanges` / `hands.spread`, the thumb rest and the heart's wrist spread, the cap, desk props, the rebuilt face (`[stage.face_rebuild]`) |
| `stage.builder` | `../deepseek_chika/room.py`: the room after the original ED, sun through the windows, haze, cues on the song; desk props placed from `[stage] props` |
| `stage.steps` | `face_rebuild.py`, then `../deepseek_chika/hat.py`: the red cap, on the desk, picked up, worn, thrown into the lens |
| `face_rebuild.py` | v4: the face rebuilt: clean surface, a real mouth (opening, lip line, inside, teeth, tongue), eyes in layers, shape keys keyed from the facial track |
| `face_textures.py` | v4: the clean skin and the eye layers made from the painting (system Python) |
| `face_shape.py` | v3's face (relief smoothed in depth, proxy normals); v4 still uses its `adopt_islands` |

## Face, v4 (`face_rebuild.py`, `face_textures.py`)
In v3 the painted face sat on Tripo's realistic sculpt, and the two showed at once: the outline shell
caught the sculpted mouth slit as a second mouth under the painted one, and the eye sockets made their
own creases. v4 builds the face the way anime character models are built (Arknights: Endfield's rigs
in the user's references, Genshin, Gakumas, MMD/VRoid: the mouth is geometry, not a texture):
1. The old face (Tripo's ~30 pieces inside the face outline: eyeballs, lids, lips, nose tip) is
   removed and the outline is filled with a new surface: the old depth blurred (`smooth_mm`), 30% of
   the nose kept, the old surface itself at the outline so it meets the head. No outline shell inside
   the face (`outline_fade_mm` from its edge); shading normals from an ellipsoid as before.
2. The mouth is an opening in it: a closed line at rest, a lip-coloured strip round the rim, and behind
   it the inside of the mouth (a dark bowl), the upper teeth and the tongue. Shape keys `a i u e o wa
   smirk` (あ い う え お ワ にやり), sized from the expression tiles v3 drew, move the rim, the rings round
   it (more below: the jaw), the teeth band and the tongue.
3. The eyes are layers over the surface: the eyeball (white, iris, highlights; carried on under the
   lids by inpainting), an upper lid with the lash band and a lower lid with the lid line, faded out at
   their edges. `eye_close_L/R` bring the lash band down over the lower lid; `eye_smile_L/R` lower it
   and raise the lower lid behind it (^^). Both eyes are the clean painted eye; the other painted eye's
   outer corner was damaged, so it is that one mirrored about the face's symmetry plane (x = 0).
4. The skin is the painting's skin colour field (blush kept; projected hair strands, painted eyes,
   mouth line and halos gone), with the small painted nose moved onto the centre line.
5. The facial track keys the shape keys directly (`face.mode = "none"`): each eye closes with
   まばたき or its wink and smiles with 笑い while open; the vowels share the mouth (scaled when they
   add past 1); にやり only with the mouth closed.

## Face, v3 (`face_shape.py`)
The face painting is an exact front projection (u, v linear in x, z), so vertices may move in depth
without breaking it. As 3D anime faces are made (Guilty Gear Xrd's edited normals, Blue Protocol,
Gakumas), the face is not lit as the realistic sculpt Tripo made:
1. *Adopt* patches of other materials set into the face (`adopt_max_polys`, `adopt_ratio`). Here
   the mouth slit and the eye corners were cloth. They take the face material and UVs from its
   projection, so the painting and the mouth drawings reach them.
2. *Smooth the relief* in depth only (Laplacian on y, `smooth_iters`), keeping `detail` of it,
   faded in over `ramp` from the face region's edge.
3. *Proxy normals*: custom normals from an ellipsoid (`normal_center`, `normal_radii`) round the
   head, blended by the same fade. The face's toon shading uses them, so the light/shadow edge
   crosses it as one curve.

## Hands
`hands.phalanges = [1.0, 0.62, 0.55]` re-places each finger's joints (the auto-rig spaced them
1 : 0.95 : 0.95; an MMD reference measures about 1 : 0.6 : 0.55), and `hands.spread = 1.25` widens
the knuckle row (0.47 of the palm length; 0.64 on the reference). Fingertips stay put. This runs on
the rig before the motion is retargeted (`hands.finger_bones`), so the generated hands and the MMD
finger keys both use the new joints.

## Limits
- The eyes and mouth follow the head as drawn features do. There is no per-angle correction, such
  as the mouth sliding toward the near cheek in profile, which some productions add.
- On high kicks the gown tents over the knee. A few hops ask the leg to reach further than its
  length, so the foot leaves the floor slightly.
- Hands are stylised (no fingernails), with one flat skin colour.
