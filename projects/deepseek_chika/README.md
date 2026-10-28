# Example: Deepseek — Chika Dance

A second production on the same dance as [claude_chika](../claude_chika): a Tripo-generated,
toon-shaded whale maid (1 m tall, Mixamo rig) with an apron, a long skirt over a frilled petticoat,
long wavy hair and a whale tail, dancing akomni's MMD motion **チカっとチカ千花っ♡**
([niconico sm34597101](https://www.nicovideo.jp/watch/sm34597101)) with that package's camera,
facial track and song, in the student-council room, now lit by the sun through its windows.
94 s at 1920×1080, 30 fps.

No assets are included. Put the character file and the MMD motion package where `project.toml`
expects them, or point to them from a `project.local.toml` next to it:

```
# once: the cleaned skirt panel (system Python: numpy, scipy, opencv, pillow)
blender -b <character.blend> --python projects/deepseek_chika/export_skirt_uv.py -- projects/deepseek_chika/project.toml projects/deepseek_chika/build/skirt_uv.npz
python projects/deepseek_chika/skirt_texture.py projects/deepseek_chika/build/skirt_uv.npz projects/deepseek_chika/textures/Deepseek_Body_D_clean.png

python -m mmdance build  projects/deepseek_chika/project.toml
python -m mmdance render projects/deepseek_chika/project.toml --jobs 2
python -m mmdance encode projects/deepseek_chika/project.toml
```

## What each part does here
| | |
|---|---|
| `project.toml` | Everything character- and dance-specific: lattice heights, the apron and tail, the measured face guides, the repairs, the intro shot, furniture placed for this motion scale |
| `room.py` | The claude_chika room with real window openings, soft-lit set shading, sunbeams in haze and lighting cues that follow the song (stage builder with `finish()`) |
| `skirt_texture.py`, `export_skirt_uv.py` | Redraw the skirt's blue front panel in the body texture |
| `hat.py` | The red cap of the original: on the desk, picked up, worn, taken off and thrown into the lens (called from `room.py`) |
| `face_shape.py` | Reshapes the jaw and lips in depth only, so the front-projected face painting holds from every angle |

## Model repairs (Tripo's rig and mesh)
- **Hands** rebuilt from the finger bones, as in claude_chika. Her hands share their material with
  her neck and chest, so only the faces past the wrists are replaced (`hands.select = "wrist"`),
  and the new hands take a clean texel of neck skin (`hands.skin_uv`), so the chest keeps its
  painting. The rig's wrists sit 1 cm apart left to right; one hand size for both (`hands.scale`).
- **The tail** was weighted to the left thigh, so it swung with her leg. It is its own island; it
  now has two chains of 9 joints laid along it by surface distance from the root, the first two
  inside her riding the hips, simulated as a muscular tail that is kept outside the skirt.
- **Hair curls with the cloth material.** Seven curls inside the hair mass had the cloth material
  and head weights; the lower ones would have followed the skirt. They join the hair chains
  (`hair.adopt_head_islands`).
- **Eight face vertices had no weights** and stayed at the rest pose as she moved: long streaks
  across the frame. They take their nearest neighbour's weights (`fixes.unweighted`).
- **Shoe buckles and straps** are separate little islands that the skirt claimed; they now follow
  the feet (`legs.attach`). The leg mesh reaches up to the pelvis, which the rigid-boot repair gave
  to one thigh; it blends into the hips there (`fixes.rigid_boots_hips`).
- Nape seam, cross-side leg weights and rigid shoes as in claude_chika.

## Skirt
- **Texture.** The blue front panel came out of the concept-sheet projection as smeared streaks
  and blotches. `skirt_texture.py` unrolls the skirt's outer surface into a panorama (angle ×
  height, where the UV islands' seams vanish), redraws the panel there as its own smooth shading
  plus crisp pinstripes at constant angle (they run straight down the fabric and converge toward
  the waist, like the concept), keeps the gold embroidery, bows and trims, and writes the result
  back into the 8K texture, gutter texels included so no seams show.
- **Lining.** The skirt is a single surface; when it flies up its inside showed the outside print.
  Backfaces now take a darker navy shade of it (`stage.lining`).
- **Layers.** The apron is the one real second layer (the navy overskirt is painted on): it hangs
  on its own chains in front (`overskirt.phi_range`, `zbottom`) and flutters separately from the
  skirt, while the gold bows below it stay sewn to the skirt.

## v2 (after the original ED)
- **Face:** the jaw and lips reshaped in depth only (`face_shape.py`); eye states drawn over an
  eye-less copy of the painting (`face.atlas.lids = "inpaint"`).
- **Cap:** `hat.py`, frames from the original video (its audio leads the song by 3.91 s).
- **Hair:** one chain per lock (`hair.mode = "locks"`), jointed-chain physics.
- **Skirt:** less stretch, more damping, `smooth_frames`; **tail:** freer toward the fluke, `tail.sway`.
- **Heart hands:** `motion.thumb_rest`, `motion.hands_apart`.
- **Room:** the original's violet-framed windows, sage curtains, cream walls over dark panelling,
  red carpet, door, plant, desk props.

## Light
The sun is outside the back windows, the side the camera looks toward. It shines in through real
openings in the wall: the window bars, curtains, desk, sofa and the dancer are cast across the
floor in warm pools, and beams show in a light haze that thickens toward the windows. The set has
soft-lit shading that follows the light arriving (colour included); the dancer keeps her cel
shading (and her face its own clean shading from the key light), with a warm sunlit tone where
the window sun reaches her. Over the song the sun sinks from 40° to 22° and warms from 5400 K to
2700 K, so the pools stretch across the floor, and its strength follows the music: soft for the
intro on the desk, up when the band comes in, down for the breakdown on the sofa, strongest for the
last chorus, then sunset for the outro.

## Limits
- Hands are stylised (no fingernails); the hand material is a flat skin texel.
- The tail passes through the back of the skirt where it leaves the body, as on the model.
- On the sofa (~46 s) her knees are up and the skirt rides over them: the hem stretches and a small
  gap opens at her side, a limit of the lattice cloth.
- Where the apron's frilled hem lies on the skirt, a few faint marks of the original texture remain.
- A few hops ask the leg to reach further than its length, so the foot leaves the floor slightly.
- The original's beret prop is not recreated.

## Credits
- Motion, camera, facial track: akomni — [bowlroll 189318](https://bowlroll.net/file/189318);
  original video [sm34597101](https://www.nicovideo.jp/watch/sm34597101).
- Song: チカっとチカ千花っ♡ (Kaguya-sama: Love Is War).
- None of these are distributed here. Use them under their authors' terms.
