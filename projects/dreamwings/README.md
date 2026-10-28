# DreamWings: the 梦的翅膀受了伤 meme, with Claude and ChatGPT, in the Anthropic lobby

Claude dances the first part of the meme and ChatGPT the second. The motion is 鸭梨P's MMD motion
梦的翅膀受了伤 (VMD-TDA.vmd and face.vmd, 453 frames). The camera is solved frame by frame from the
meme's reference video. The song is the 朋友的酒 DJ track, timed as in the 许家印败方MVP结算 clip.
The set is the Anthropic lobby (`Anthropic_Scene/05_output/lobby.blend`).

The analysis and the assets live outside the repository, in `Anthropic_Scene/MMD_DreamWings`
(`tools/`, `analysis/`, `audio/`, `source/`, `runpod/`). `project.local.toml` files point at them.

```
python -m mmdance build projects/dreamwings/claude/project.toml
python -m mmdance build projects/dreamwings/chatgpt/project.toml
```

| | |
|---|---|
| `claude/project.toml` | Claude: claude_chika_v3's character setup (hair locks, gown, hands, repairs, rebuilt face) on the new motion |
| `chatgpt/project.toml` | ChatGPT: chatgpt_chika's character setup (gown, hair locks, tail, hands, sleeves, wings, atlas face) on the new motion |
| `claude/face_*.py`, `chatgpt/sleeves.py`, `chatgpt/wings.py` | Copies of those projects' code (repo root paths adjusted for the deeper folder) |
| `lobby.py` | The stage: the lobby appended and scaled around the dance, the solved camera and the dancer's turn keyed, the character's key light, render settings |
| `camera/camera_track.npz` | The camera on the song's timeline, and each rig's location and yaw. It is made by `MMD_DreamWings/tools/assemble_camera.py` and is not in the repository (`*.npz` is ignored) |

## Timeline
The motion (453 frames, 30 fps) was captured from the MVP clip: its poses match that clip within a
frame (the motion runs 0.75 frame ahead), so the song is timed to the motion as the clip times it.
The DJ track is resampled to 0.8858x from 33.007 s, so its pitch drops with the speed as in the clip.
The reference video (the meme) covers the same choreography in its first 15 s:
- the black-suit dancer up to reference frame 340, with a hidden jump cut at 239|240 (about 29
  frames of the dance cut out);
- a whip pan to the white-shirt dancer, who continues the dance from 341.

Its last 8 s replay earlier black-suit footage (from reference frame 124) and go beyond the motion,
so the video is the motion's 15.1 s. Claude dances frames 0-337 and ChatGPT 338-452.

## Camera (MMD_DreamWings/tools)
1. `pose2d.py`: COCO keypoints of the dancer in every reference frame (YOLO11x-pose).
2. `costmat.py`, `match_frames.py`: the motion frame with the same pose for each reference frame
   (DTW per reference segment; A2 constrained near its linear warp).
3. `fov_from_rotation.py`: the lens from the background. Distant scenery between nearby frames
   gives f = 427 px on 1024 (100° horizontal); the phone's ultra-wide is the same for both clips.
4. `bg_rotations.py`: the camera's rotation between consecutive frames from the background (SIFT
   homographies; phase correlation on whip-pan blur).
5. `solve_camera.py`: per segment, the camera pose for every reference frame. The character's own
   rig keypoints at the matched motion frame are fitted to the detections, jointly with the
   background rotations and smooth travel. Median reprojection error is 30 px at 1024 px; the
   characters are anime-proportioned, the reference dancers are not. Check with `overlay_cam.py`.
6. `world_yaw.py`: the mocap kept the dancer facing the lens, but the real camera turned about
   270° around the rooftop. That turn is the difference between the background's and the solve's
   camera rotation.
7. `assemble_camera.py`: the output camera. Each output frame takes the relative camera of its
   reference time. The dancer's frame is turned by that yaw about the hips, with the hips moving
   along the turned heading, so the feet do not slide. The camera rides the same transform. It
   bridges the jump cut, re-times Claude's last second so the whip pan out ends at the swap, and
   places ChatGPT where the continuing whip lands.

## Stage (`lobby.py`)
- The characters are 1 m tall, the lobby real size. `Lobby_Root` scales the lobby by 0.625, so
  the characters read as 1.6 m. Point, spot and area lights are scaled by 0.625² to light it the
  same.
- `tools/place_dance.py` picked the spot: (1.0, 18.25) in the lobby, between the slatted screens
  and the wall planters, turned 180°. The dancer, with a 0.45 m reach, and the camera stay 0.9 m
  clear of everything.
- The character's key light (`AIG_Sun`, which also drives the painted face's shading) follows
  the camera, raised 35° and turned 25°. Light linking limits it to the dancer. The lobby's own
  lights light both.
- View transform: Khronos PBR Neutral. It keeps the toon colours as painted (AgX washed them out)
  and still rolls off the lobby's highlights. Motion blur is on, with shutter 0.5.

## Face
The capture's eye channels read the dancer's squinting grin as closed eyes: ウィンク is above 0.5 on
90 % of the frames. `tools/clean_face_vmd.py` writes `face_clean.vmd`:
- eyes open, with natural blinks;
- the capture's mouth openings (ワ, お) amplified;
- a light smile (にやり) in between.

## Characters
Both run their earlier projects' setups with two changes for this dance:
- **Claude's hair.** This dance twists hard all the way through: on claude_chika_v3's settings
  the locks moved a median 13 cm a frame (`qa`) against 8 on the Chika dance, and the thin
  ringlets streamed out like ribbons. More drag and stiffer joints bring that to 12, and more
  smoothing calms the rest.
- **Tempo.** ChatGPT's tail sway and wing beat are re-timed to the song's 114 bpm: two and four
  beats.

## Render
The two built scenes were packed (`MMD_DreamWings/tools/pack_for_render.py`: images packed, the
song's preview strip dropped, frames written next to the `.blend`) and rendered with EEVEE on one
RunPod L40S at 1920 × 1080, 64 samples:
- **Motion blur** (shutter 0.5) makes the render CPU-bound by the scene evaluation: about 21 s a
  frame per Blender process. Nine processes shared the GPU and took about 50 minutes.
- **The pod** needs `NVIDIA_DRIVER_CAPABILITIES=all` and the EGL/GL/Vulkan client libraries for
  headless EEVEE (`MMD_DreamWings/runpod/setup_pod.sh`). The processes start 20 s apart; the
  first one compiles the shaders (`render_job.sh`).
- **Every frame was checked:** 453 non-empty PNGs, md5-verified after the download.
- `MMD_DreamWings/tools/encode_final.py` cuts from Claude's frames to ChatGPT's at frame 338 and
  muxes `audio/song.wav`, fading it over the last 0.25 s. `mmdance encode` handles one project.

## Limits
- The characters are anime-proportioned and the reference dancers are not. The framing matches
  (median keypoint error 30 px at 1024 px wide), but limbs can sit differently in frame.
- The reference's jump cut at 8.0 s is a smooth 1 s camera move here.
- The dancer's turn is keyed on the rig object after the physics, so the simulation does not see
  it (about 270° over 15 s).
- Claude's long hair streams wide on the fastest twists.
- The lobby's hidden areas are plausible completions; the camera turns past the glazing, the
  front-left white walls and the screens.

## Credits (借物表)
- Motion and facial track: 梦的翅膀受了伤 by 鸭梨P. The package asks for a credits list when used.
- Song: 朋友的酒 (DJ version, kkr upload BV1hXbN6VEKV), timed as in 许家印败方MVP结算 (BV1g6My6AE9P).
- Camera reference: 梦的翅膀受了伤 (BV1SDK46yEZ3).
- Characters: the user's Claude and ChatGPT models.
- Set: the user's Anthropic lobby reconstruction.
