# Example: ChatGPT — Chika Dance

A third character on the same dance as [claude_chika](../claude_chika) and
[deepseek_chika](../deepseek_chika). She is a Tripo-generated, toon-shaded white dragon woman
(1 m tall, Mixamo rig) with horns, bat wings, a long tail, bell sleeves that hang from her
forearms, a floor-length gown with ruffled edges, and long wavy hair. She dances akomni's MMD
motion **チカっとチカ千花っ♡** ([niconico sm34597101](https://www.nicovideo.jp/watch/sm34597101))
in the deepseek_chika room.

This project was set up to test the *optimized* model: the polished file with its parts
repaired, made by `AI_girls/_pipeline/optimize` (outside this repository; see the model's
NOTES.md). It adds two things the engine has no feature for, both as project code:
sleeve physics and a wing beat.

No assets are included. Point `project.local.toml` at the character file and the MMD motion
package, then:

```
python -m mmdance build  projects/chatgpt_chika/project.toml
python -m mmdance stills projects/chatgpt_chika/project.toml 400,1000,1300 cam,front,side
```

## What each part does here
| | |
|---|---|
| `project.toml` | Skirt (the dress material only), hair locks, tail, hands, repairs, the face guides, sleeve and wing settings |
| `stage.builder` | `../deepseek_chika/room.py`: that project's room and light, shared, not copied |
| `sleeves.py` | A stage step: simulates the bell sleeves on the model's `Sleeve_L/R_cc_k` chains with mmdance's solver and bakes them. Runs on a built scene too (`--until N`) |
| `wings.py` | A stage step: a slow wing beat on `Wing_L/R_0/1`, and a sweep back against chest turns |

## What the model needed (fixed in the optimized model, not here)
- Its tail was weighted to her thighs and left toe. Its wings were weighted to the arms, shoulder
  and head.
- About 2,700 hair faces carried the dress material, and the wing roots the hair material, so
  mmdance's material-based hair and skirt detection would have mixed them up.
- The sleeves hang below the waist, and their material was the dress's: mmdance's skirt would
  have taken them. They now have their own material, and the skirt is `skirt.materials =
  ["ChatGPT_Cloth"]`.
- The tail was fused to the body; mmdance's `[tail]` needs it as its own mesh piece.
- A sleeve hem and the wing membranes touched the skirt: the skirt's motion stretched them into
  long spikes until they were cut free.
- Later, the face was rebuilt in the model, after this project was set up. Tripo had sculpted its
  own eyes, lips and nose under the painted ones, in pieces at different depths, so the painted eye
  split apart once the head turned. The concept sheet's bang strands were painted on the skin
  under the 3D bangs. Now the face is one smooth surface under the painting, the bangs carry the
  hair material, and the skin has no hair painted on it. The painted eyes and mouth kept their
  pixels, so the face guides below still fit. This project's atlases and build predate the
  rebuild; [dreamwings](../dreamwings) built her with the rebuilt face.

## Sleeves
Each sleeve is a 5 × 6 lattice of joints: columns along the forearm, rows down the bell. The
joints are jointed chains, as for the hair, but the joint springs are 10 times weaker than the
hair's (0.012 at the first joint). At the hair's strength a joint beats gravity about 9 to 1, so
the sleeve would keep its T-pose shape relative to the forearm and turn up like a board when the
forearm twists. The angle limits are wide, the tether long, and gravity is never compensated (the
rest shape already hangs straight down). A raised arm lets the sleeve fall back along it, and
outstretched arms let it hang below.

The top row rides the arm where the sleeve is sewn on, blended from the upper arm to the forearm
across the elbow (a `Lattice` subclass with two root bones). The sleeves collide with the torso,
the legs and the other arm, and are kept outside the skirt's simulated surface. The result is
cached like the skirt's.

## Face
The painted face gets an expression atlas (`face.mode = "atlas"`, lids inpainted). The lids were
inpainted because bang strands crossed both eyes on the model's first face texture. Its face
rebuild took them off the skin, and inpainting still gives the softer lids. Her eyes are tall, with
a deep lower lid, so the `lower` guides sit 8 px
below the painted lid line. The closed lash then covers that line and leaves one dark line, not
an outlined empty eye. Check `textures/atlas_eyes_preview.png` after changing the guides.

## Limits
- Hair locks are not kept out of the wings: in a big turn a lock can pass through a wing.
- Closed eyes look like outlined ovals in close-ups. The atlas places a closed lash at 92 % of the
  opening, near the deep lower lid, and the painted crease stays above it. From the dance camera
  the face is small enough that this hardly shows. A fix needs an engine option for where the
  closed lash sits.
