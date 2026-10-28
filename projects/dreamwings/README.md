# DreamWings: the 梦的翅膀受了伤 meme, with Claude and ChatGPT, in the Anthropic lobby

Claude dances the first part of the meme and ChatGPT the second. The motion is 鸭梨P's MMD motion
梦的翅膀受了伤 (VMD-TDA.vmd and face.vmd, 453 frames). The camera is solved frame by frame from the
meme's reference video. The song is the 朋友的酒 DJ track, timed as in the 许家印败方MVP结算 clip.
The set is the Anthropic lobby (`Anthropic_Scene/05_output/lobby.blend`).

The analysis and the assets live outside the repository, in `Anthropic_Scene/MMD_DreamWings`
(`tools/`, `analysis/`, `audio/`, `source/`, `runpod/`). `project.local.toml` files point at them.

```
python -m mmdance build  projects/dreamwings/claude/project.toml       # ~5 min
python -m mmdance build  projects/dreamwings/chatgpt/project.toml      # ~2 min
python -m mmdance render projects/dreamwings/claude/project.toml --start 0 --end 337
python -m mmdance render projects/dreamwings/chatgpt/project.toml --start 338 --end 452
python -m mmdance encode projects/dreamwings/claude/project.toml       # the cut, the song, the copies
```
Everything but the camera solve is config: the lobby is `stage.builder = "set"`, the camera
`camera.track`, the key light `stage.key_follow`, and the characters' own code runs from their
projects' folders as `stage.steps`. Rendered elsewhere, the frames come back through
`python -m mmdance pack` (see Render).

| | |
|---|---|
| `claude/project.toml` | Claude: claude_chika_v3's character setup (hair locks, gown, hands, repairs, rebuilt face) on the new motion |
| `chatgpt/project.toml` | ChatGPT: chatgpt_chika's character setup (gown, hair locks, tail, hands, sleeves, wings, atlas face) on the new motion |
| `stage.steps` | Claude: `../../claude_chika_v3/face_rebuild.py`; ChatGPT: `../../chatgpt_chika/sleeves.py`, `wings.py`. The originals, not copies |
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

## Stage (`[stage.set]`, `[render]`)
- The characters are 1 m tall, the lobby real size. `Set_Root` scales the lobby by 0.625, so
  the characters read as 1.6 m. Point, spot and area lights are scaled by 0.625² to light it the
  same.
- `tools/place_dance.py` picked the spot: (1.0, 18.25) in the lobby, between the slatted screens
  and the wall planters, turned 180°. The dancer, with a 0.45 m reach, and the camera stay 0.9 m
  clear of everything.
- The character's key light (`AIG_Sun`, which also drives the painted face's shading) follows
  the camera, raised 35° and turned 25° (`stage.key_follow`). Light linking limits it to the
  dancer (`stage.key_link`). The lobby's own lights light both.
- The camera (`camera.track`) and the dancer's turn (`camera.track_dancer`) come from
  `camera/camera_track.npz`, with the near clip at 1 cm for the 15 mm lens.
- View transform: Khronos PBR Neutral. It keeps the toon colours as painted (AgX washed them out)
  and still rolls off the lobby's highlights. Motion blur is on, with shutter 0.5.

## Face
The capture's eye channels read the dancer's squinting grin as closed eyes: ウィンク is above 0.5 on
96 % of its keys (`python -m mmdance vmd face.vmd`). The facial track the builds read is written by
```
python -m mmdance facial face.vmd face_clean.vmd --blinks 75,120 --mouth ワ:あ:2.2:0.75 --mouth お:お:2.5:0.5 --smile にやり:0.65
```
- eyes open, with natural blinks every 75–120 frames;
- the capture's mouth openings (ワ, お) amplified;
- a light smile (にやり) in between.

It writes the `face_clean.vmd` the video was made with, byte for byte.

## Characters
Both run their earlier projects' setups with two changes for this dance:
- **Claude's hair.** This dance twists hard all the way through: on claude_chika_v3's settings
  the locks moved a median 13 cm a frame (`qa`) against 8 on the Chika dance, and the thin
  ringlets streamed out like ribbons. More drag and stiffer joints bring that to 12, and more
  smoothing calms the rest.
- **Tempo.** ChatGPT's tail sway and wing beat are re-timed to the song's 114 bpm: two and four
  beats.

## Render
The two built scenes were packed (`python -m mmdance pack <project.toml> --samples 64`: images
packed, the song's preview strip dropped, frames written next to the `.blend`) and rendered with
EEVEE on one RunPod L40S at 1920 × 1080, 64 samples:
- **Motion blur** (shutter 0.5) makes the render CPU-bound by the scene evaluation: about 21 s a
  frame per Blender process. Nine processes shared the GPU and took about 50 minutes.
- **The pod** needs `NVIDIA_DRIVER_CAPABILITIES=all` and the EGL/GL/Vulkan client libraries for
  headless EEVEE (`tools/remote/setup_linux_gpu.sh`). The processes start 20 s apart; the first
  one compiles the shaders (`tools/remote/render_job.sh`).
- **Every frame was checked:** 453 non-empty PNGs, md5-verified after the download.
- `python -m mmdance encode projects/dreamwings/claude/project.toml` cuts from Claude's frames to
  ChatGPT's at frame 338 (`[[encode.parts]]`), ends the song with the dance and fades it over
  0.25 s (`song_end = "cut"`), and writes the 720p and under-10 MB copies (`encode.copies`: CRF 20,
  and two passes at 4600 kbit/s without `-tune`). From the pod's frames it writes the released
  `DreamWings.mp4` and both copies byte for byte.

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
