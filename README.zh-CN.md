# mmdance：让任意 Mixamo 骨骼的 Blender 角色跳 MMD

[![tests](https://github.com/starryark/mmdance/actions/workflows/tests.yml/badge.svg)](https://github.com/starryark/mmdance/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Blender 5.2+](https://img.shields.io/badge/Blender-5.2%2B-orange.svg)](https://www.blender.org/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](requirements.txt)

[English](README.md) | **简体中文**

**mmdance 让绑定了 Mixamo 骨骼的角色在 Blender 里跳 MikuMikuDance（MMD）舞蹈。** 它适用于 Tripo、Meshy 等 AI 生成（图生 3D）的角色，Mixamo 和 AccuRig 绑定的角色，也可以通过骨骼名映射用于你自己的骨架。你只需提供角色的 `.blend` 和一套 MMD 动作数据包：VMD 舞蹈动作、VMD 镜头、表情 VMD 和歌曲。它会搭好动画场景，在无界面（headless）模式下按一份配置文件渲染出完整的 1080p 视频。每一步的结果都以其输入为键缓存，重新构建时只重算改动过的部分，其余结果原样复现。

## 演示

https://github.com/user-attachments/assets/532d0b6d-a07f-4ca3-ac91-04a43aa5a862

*[projects/claude_chika_v3](projects/claude_chika_v3)：一个 Tripo 生成的二次元角色身穿多层舞会礼服，跳 akomni 的 MMD 动作《チカっとチカ千花っ♡》（94 秒），使用动作包自带的镜头、表情和歌曲，场景是阳光从窗外照进来的学生会室。`build.py` 从未经改动的角色文件生成整个场景：重定向后的舞蹈、物理模拟的礼服和逐缕模拟的头发、按手绘比例调整指关节的双手、重建为几何体的脸（能张开的嘴、分层的眼睛、由表情轨道驱动的形态键），以及最后被抛向镜头的红帽子。此处为 1080p 渲染的 10 MB 以内压缩版；借物表见 [该项目](projects/claude_chika#credits)。*

| | | |
| --- | --- | --- |
| ![Blender 中的 MMD 舞蹈：Tripo 生成的橙色长发二次元角色闭着眼躺在阳光照进的房间里的书桌上唱歌，身旁放着一顶红帽子，白黑相间的多层舞会礼服垂在桌边](docs/media/claude-chika-desk.jpg) | ![使用 Mixamo 骨骼的角色在舞蹈中踢出一条腿并伸手指向前方，模拟的裙摆和外层裙在转身后扬起](docs/media/claude-chika-kick.jpg) | ![舞蹈接近尾声时，角色在阳光照进的房间里双手比心微笑，脸部已重建为几何体，长发垂落在礼服上](docs/media/claude-chika-smile.jpg) |

*开场镜头：躺在书桌上（书桌是布料碰撞体），身旁放着帽子；踢腿时的裙摆物理；结尾的比心，使用重建后的脸。这段视频的第一个版本来自 [projects/claude_chika](projects/claude_chika)（管线的回归基准），见 [0.1.0 版本发布](https://github.com/starryark/mmdance/releases/tag/v0.1.0)。*

### 两个角色、从参考视频解算的镜头：DreamWings

https://github.com/user-attachments/assets/26e7c1ac-1053-4331-812b-8187a1a2b12a

*[projects/dreamwings](projects/dreamwings)：两个 Tripo 生成的角色 Claude 和 ChatGPT 先后登场，在 Anthropic 大厅里跳鸭梨P 的 MMD 动作《梦的翅膀受了伤》（15 秒，即这个梗视频的编舞）。大厅从它自己的 `.blend` 追加进来，并围绕舞蹈缩放。镜头从梗视频的参考视频逐帧解算，连甩镜也一并还原，两位舞者的交接就在一次连续的甩镜之中。两次构建都从未改动的角色文件开始：重定向的舞蹈、物理模拟的礼服、头发、袖子和尾巴、面部表情，以及运动模糊。此处为 1080p 渲染的 10 MB 以内压缩版；借物表见 [该项目](projects/dreamwings#credits-借物表)。*

## 功能

如果你有一个 AI 生成或自动绑定的二次元角色，想让它跳一支 MMD/VMD 舞蹈，这套管线就是为此而做的。它把 MMD 动作重定向到非 MMD 骨架上，加上裙摆和头发物理，驱动面部表情，并用原版镜头和音乐渲染。具体包括：

- **动作重定向。** VMD 通过 mmd_tools 导入到一副按你的骨架比例搭建的代理 MMD 骨架上，再在世界空间中映射到你的骨骼，上臂与前臂共享扭转骨。MMD 的脚部 IK 由解析式的两骨骼腿部 IK 求解。
- **MMD 镜头**（`camera.vmd`）；原版镜头不适合你的模型时，可以在某些片段换用自定义镜头。
- **二次动态（物理）**：裙摆、多层礼服和围裙、长发（整片或逐缕）以及尾巴。骨链自动铺设到网格中，用基于位置的求解器模拟：
  - 带角度限制的关节链，类似 MMD 的刚体裙摆和 DynamicBone；
  - 根据身体测量生成的胶囊碰撞体；
  - 家具的盒形碰撞体与非弹性接触。

  结果烘焙为关键帧，最终场景不依赖任何插件。
- **面部表情**，来自 VMD 的表情（morph）轨道。可以驱动形态键；对于五官*画在贴图上*的脸（图生 3D 角色常见），则用从这张贴图本身生成的表情图集来驱动。
- **自动绑定网格的修复：**
  - 根据手指骨骼，把粘连成团的手指重建为真正的手，并把指关节移到手绘的比例；
  - 把头发从衣服上撕开，修复带着衣服材质的发卷；
  - 靴子的刚性权重；
  - 清理左右腿之间串扰的权重；
  - 没有权重的顶点。
- **舞台、灯光、渲染**（EEVEE），可断点续渲的并行渲染，以及配上歌曲的视频编码。画面与声音一起淡出。
  - 从另一个 `.blend` 追加并围绕舞蹈缩放的场景、按轨道文件逐帧驱动的镜头（例如从参考视频解算）、跟随镜头的主光、运动模糊。
  - 在构建好的角色上运行你自己的项目代码（重建的脸、道具、袖子），多个项目之间按路径共享。
  - 可拿到云 GPU 上渲染的场景打包副本、把两个角色的渲染剪进同一个视频，以及用于分享的压缩版。

一切都由 `build.py` 从你未经改动的角色文件生成。每个阶段的结果都以输入为键缓存，重新构建时只重算改动过的部分。

## 现状
它最初只为一个作品而写：一个 Tripo 生成、身高 1 米的卡通角色跳一段 94 秒的 MMD 动作（[projects/claude_chika](projects/claude_chika)；视频见 [0.1.0 版本发布](https://github.com/starryark/mmdance/releases/tag/v0.1.0)）。引擎（重定向、镜头、骨链与物理、面部状态、渲染、编码）是通用的、由配置驱动的，并且至今仍能精确复现那个作品的输出：每一份缓存、面部图集和渲染帧都一致。通用路径也在同一角色上做过冒烟测试：默认舞台、跟随镜头、形态键表情、不做修复、从舞蹈中段开始的帧范围。

此后它又用三个 Tripo 角色、两支舞做了视频。每个新模型都加入了它需要的选项，全部按需开启：
- [projects/deepseek_chika](projects/deepseek_chika)：一个鲸鱼女仆，有围裙和尾巴，手和脖子共用同一个材质。
- [projects/chatgpt_chika](projects/chatgpt_chika)：一个龙娘，有翅膀、尾巴和喇叭袖。项目代码模拟袖子并扇动翅膀。
- [projects/claude_chika_v3](projects/claude_chika_v3)：重做的第一个作品（即上面的演示），头发逐缕模拟、礼服摆动更沉稳、按手绘比例调整指关节，脸重建为几何体。
- [projects/dreamwings](projects/dreamwings)：第二支舞，一段 15 秒的动捕梗视频。Claude 和 ChatGPT 在从另一个 `.blend` 追加的场景里轮流登场，镜头从参考视频解算而来。

换一套新服装时，要调骨链格点（lattice）的高度和物理参数；换一支新舞，要调头发。面部图集需要为每张手绘的脸测量引导曲线；画在写实雕刻头部上的手绘脸最好重建为几何体（项目代码见 [projects/claude_chika_v3](projects/claude_chika_v3)，尚未成为引擎模式）。房间搭建脚本和镜头解算属于各个项目；从另一个 `.blend` 追加的场景和解算好的镜头轨道则通过配置接入。构建在 Windows 11 + Blender 5.2 上完成。DreamWings 的帧是在 Linux 云 GPU 上，用打包后的构建场景渲染的。

## 环境要求
- **Blender 5.2+**，并安装 **MMD Tools** 扩展（编辑 › 偏好设置 › 获取扩展 › 搜索 "MMD Tools"；测试版本 4.5.14）。
- **Python 3.11+**（系统 Python），安装 `numpy scipy opencv-python scikit-image pillow matplotlib`。手部和面部图集的生成（Blender 自带的 Python 缺少这些库）、视频编码和质检都用它运行。
- **ffmpeg**，需在 `PATH` 中。

```
pip install -r requirements.txt
```

## 快速开始
```
python -m mmdance new projects/my_dance          # 复制模板
#   character/  <- 绑好骨骼的 .blend（Mixamo 骨骼名、T-pose、Z 轴向上、面朝 -Y）
#   source/     <- motion.vmd, camera.vmd, (facial.vmd), song.wav
python -m mmdance inspect projects/my_dance/character/character.blend   # 检查骨架 + 测量高度 + 参数建议
#   编辑 projects/my_dance/project.toml
python -m mmdance build  projects/my_dance/project.toml
python -m mmdance stills projects/my_dance/project.toml 100,600,1200 cam,front    # 快速检查渲染
python -m mmdance render projects/my_dance/project.toml --jobs 2
python -m mmdance encode projects/my_dance/project.toml
```
一个项目就是一个 `project.toml`；[mmdance/defaults.toml](mmdance/defaults.toml) 记录了每一个配置项。与本机有关的路径写在旁边的 `project.local.toml` 里：它合并在最上层，并且永远不会提交。完整流程见 [docs/new-character.md](docs/new-character.md)，方法原理见 [docs/how-it-works.md](docs/how-it-works.md)（文档为英文）。

## 目录结构
| | |
|---|---|
| `build.py` | Blender 入口：依次运行 motion → camera → rig → physics → face → stage 各阶段并保存场景 |
| `mmdance/` | 管线本体：`motion`（重定向）、`camera`、`rig`（骨链、权重、修复）、`layers`（礼服分层）、`physics` + `solver`（模拟与烘焙）、`face` + `face_atlas`、`hands` + `hand_sdf`、`stage`、`encode`、`config`、`vmd`（解析器） |
| `tools/` | `inspect_character`、`stills`（检查渲染）、`physics_qa`（运动 / 裙摆滞后指标）、`plot_character`、`facial_vmd`（改写表情轨道）、`pack`（拿到别处渲染的副本）、`remote/`（Linux GPU 渲染机） |
| `projects/template/` | 新项目的起点 |
| `projects/claude_chika/` | 完整示例：配置、房间舞台搭建脚本、说明和局限 |
| `projects/deepseek_chika/` | 同一支舞的第二个角色：围裙层、尾巴骨链、共用材质的手、裙摆贴图清理，以及阳光透过窗户照亮的房间 |
| `projects/chatgpt_chika/` | 第三个角色：翅膀、尾巴和喇叭袖（袖子模拟和扇翅膀由项目代码实现），模型的部件事先做过修复 |
| `projects/claude_chika_v3/` | 重做的示例，即演示视频：逐缕头发、更沉稳的礼服、指关节、帽子道具，以及重建为几何体的脸（嘴、分层眼睛、形态键） |
| `projects/dreamwings/` | 第二支舞，两个角色轮流登场，只用配置：从另一个 `.blend` 追加的场景、来自解算轨道的镜头、跟随它的主光、运动模糊，两段渲染剪成一个视频 |
| `tests/` | 在系统 Python 中运行的单元测试（`python -m unittest`） |

## 素材与许可
代码采用 MIT 许可。**仓库不包含、也不再分发任何角色、动作或音乐。** 演示视频和 `docs/media` 中的截图是示例项目的渲染结果，仅用于展示管线；其中的动作和歌曲归原作者所有（见 [claude_chika](projects/claude_chika#credits) 和 [dreamwings](projects/dreamwings#credits-借物表) 的借物表）。MMD 动作和歌曲都有作者各自的使用条款：请阅读并遵守，注明作者，并在发布视频前确认是否允许二次创作。`.gitignore` 会把 `.blend`、`.vmd`、音频、视频、图片（docs 截图除外）和缓存挡在仓库之外。

## 常见问题

**如何让 Tripo、Meshy 或 Mixamo 角色在 Blender 里跳 MMD 动作？**
- **角色：** 导出带 Mixamo 骨骼名的绑定模型，T-pose、Z 轴向上、面朝 -Y，并保存为 `.blend`。
- **动作：** 准备一套 MMD 动作数据包，包含舞蹈 `.vmd`，最好还有 `camera.vmd`、表情 `.vmd` 和歌曲。
- **运行：**
  1. `python -m mmdance new projects/x` 新建项目。
  2. `python -m mmdance inspect <character.blend>` 检查骨架并给出参数建议。
  3. `build`、`render` 和 `encode` 生成视频。

  见[完整流程](docs/new-character.md)（英文）。

**VMD 动作能直接驱动非 MMD 模型吗？不用转成 PMX？** 可以，这正是 mmdance 的用途。VMD 由 MMD Tools 在一副按你的骨架关节位置搭建的代理 MMD 骨架上计算，得到的世界空间旋转再相对 MMD 的 A-pose（`motion.arm_angle`，默认 37°）转移到你的骨骼上。MMD 的脚部 IK 用解析式的两骨骼腿部 IK 求解，`motion.scale` 把 MMD 单位换算成米，默认根据腿长自动计算。

**能导入 PMX 或 PMD 模型吗？** 不能。原生 MMD 模型请用 [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools) 或 [SekaiBlender](https://github.com/ShiJieWorld/SekaiBlender)。mmdance 面向的是*不是* MMD 模型的角色。

**我的骨架不用 Mixamo 骨骼名（VRoid/VRM、Unreal 小白人、自定义骨架）。**
- 设置 `[bones] prefix`，或在 `[bones.map]` 中把每个 Mixamo 骨骼角色映射到你的骨骼，例如 `Hips = "pelvis"`。
- 静止姿势必须是面朝 -Y 的 T-pose。
- 映射的是形变骨骼。Rigify 之类的控制骨架不会被直接驱动。

**怎样给自动绑定的角色加上裙摆、连衣裙或长发物理？**
- 启用 `[skirt]`、`[overskirt]`（第二层、开襟的礼服外层）和/或 `[hair]`，并给出关节高度（`rows_z`），`inspect` 会给出建议值。
- 骨链铺设到网格中，用基于位置的求解器模拟（带角度限制的关节链、身体胶囊碰撞体、家具盒形碰撞体），再烘焙为关键帧。
- 调参方法见[工作原理](docs/how-it-works.md#physics)（英文）。

**怎样从表情 VMD 得到眨眼和口型？**
- 设 `face.mode = "shapekeys"`，再用 `map` 把 VMD 表情名（まばたき、あ、い、う、え、お、笑い……）映射到你的形态键。
- 五官画在贴图上的角色（图生 3D 常见）没有形态键。对这类角色，`face.mode = "atlas"` 会从脸部贴图本身生成眨眼、笑和口型的图块。
- 如果画出的五官叠在一张写实雕刻的脸上（有鼻子、嘴唇、眼窝），雕刻的起伏仍会透过五官显现：描边会勾出它的褶皱。这时应按二次元模型的做法重建脸：几何体的嘴、分层的眼睛和形态键。项目级示例见 [projects/claude_chika_v3](projects/claude_chika_v3)（`face_rebuild.py`），另见 [新角色指南](docs/new-character.md)（英文）。
- 动捕生成的表情轨道可能有误：有一条把舞者眯眼笑读成了闭眼，90% 的帧都是如此。`python -m mmdance vmd facial.vmd` 会显示每个表情的取值范围以及超过 0.5 的比例。如果与你的角色不符，`python -m mmdance facial` 可以写出一条清理过的轨道。

**能否还原一段舞蹈视频，连参考视频的运镜一起？**
- `camera.track` 按轨道文件逐帧驱动镜头：一个 `.npz`，包含帧号、位置、四元数、焦距和传感器尺寸。轨道本身在 mmdance 之外解算，例如从参考视频中解算。
- `camera.track_dancer` 让舞者随之转身：适用于动捕时舞者始终面向镜头、而真实镜头绕着她转的情况。
- [projects/dreamwings](projects/dreamwings) 就是这样还原了一段 15 秒的梗视频，场景从另一个 `.blend` 追加（`stage.builder = "set"`），并带运动模糊。

**两个角色能出现在同一个视频里吗？** 可以轮流出场。给每个角色各建一个项目，帧范围、镜头和歌曲相同，分别渲染。在负责编码的项目里，`[[encode.parts]]` 从指定帧起切换到另一个项目的帧；DreamWings 就在一次甩镜中途从 Claude 切到 ChatGPT。一次构建只有一个角色，所以不支持两人同时出现在画面中。

**我的角色有翅膀、袖子或尾巴。**
- 单独成块的尾巴网格会得到一条骨链：`[tail] enabled = true`，`seed` 设为尾巴附近的一点；`sway` 可以在物理之上叠加缓慢的摆尾。
- 其他部件用在构建好的角色上运行的项目代码实现（`stage.steps`）。[projects/chatgpt_chika](projects/chatgpt_chika) 就是这样模拟喇叭袖（`sleeves.py`）、扇动翅膀（`wings.py`）的，通过 `physics.body_track()` 和 `physics.sim_key()` 读取身体轨迹和模拟结果。

**我生成的角色手指粘成了一团。** `[hands] enabled = true` 会根据手指骨骼，在手部材质槽中重建双手（隐式曲面 + marching cubes），并按关节混合权重。

**输出可以复现吗？** 可以，这是设计目标。每个阶段的结果都以输入为键缓存，重新构建时只重算改动过的部分。参考作品重新构建后得到相同的缓存和相同的帧（GPU 误差 ±1）。`encode` 能从帧逐字节复现已发布的 DreamWings 视频，也能从已发布的视频逐字节复现两个作品的 720p 和 10 MB 压缩版。回归标准见 [AGENTS.md](AGENTS.md)。

**能否在无界面模式、渲染服务器或云 GPU 上运行？** 可以。一切都通过 `blender -b` 运行。构建在 Windows 11 上跑过。EEVEE 渲染在 Windows 11 和 Linux 云 GPU（RunPod 上的 L40S）上都跑过，后者用的是构建场景的打包副本（`python -m mmdance pack`）。Linux 上的无界面 EEVEE 需要显卡驱动的图形库：`tools/remote/setup_linux_gpu.sh` 负责安装，`tools/remote/gpu_check.py` 会告诉你 EEVEE 拿到的是 GPU 还是退回到了软件渲染（`llvmpipe`）。见 [在其他机器上渲染](docs/new-character.md#5-render)（英文）。`render.engine = "CYCLES"` 可以设置但未经测试，示例中的卡通着色器只适用于 EEVEE。

**需要多长时间？** 在开发机上制作 94 秒的 Chika Dance：

| 步骤 | claude_chika | claude_chika_v3（演示） |
|---|---|---|
| 首次构建（物理模拟 15–20 分钟） | 约 25 分钟 | 约 28 分钟 |
| 从缓存重新构建 | 约 4 分钟 | 15–20 分钟（重建脸和房间） |
| 两个 Blender 进程渲染 1080p | 约 2 小时 | 约 2.5 小时 |
| 编码 | 不到 1 分钟 | 不到 1 分钟 |

有运动模糊时 EEVEE 受限于 CPU。15 秒的 DreamWings 片段每个 Blender 进程约 21 秒一帧，九个进程共用一张云端 L40S，总共约 50 分钟。

**MMD 动作从哪里来？成品可以发布吗？** 动作作者会在 BowlRoll、niconico 等网站分享动作包，国内作者也常在 bilibili 配布。每个动作包都有自己关于使用、署名和投稿视频的条款。mmdance 不附带任何动作和音乐；发布视频前请先确认条款。

**AI 编程智能体能使用这个仓库吗？** 可以。[AGENTS.md](AGENTS.md) 写明了命令、测试和约定，[llms.txt](llms.txt) 为大语言模型索引了文档。

## 相关项目
- [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools)：把 PMX/PMD 模型和 VMD 动作导入 Blender；mmdance 使用它的 VMD 导入器。
- [CosMMD](https://github.com/CyclopsRay/CosMMD)：一张照片 → Tripo 3D → 一段 12 秒的 MMD 舞蹈片段，由智能体引导。它侧重保留角色外观，没有布料物理、面部表情、镜头和音频。
- [Blender VMD Retargeting](https://github.com/butaixianran/Blender-Vmd-Retargeting)：把 VMD 身体、表情和镜头动作重定向到 Daz 和 Character Creator 骨架的插件。
- [SekaiBlender](https://github.com/ShiJieWorld/SekaiBlender)：面向原生 PMX 模型的 Blender 版本，带 MMD IK 和 Bullet 物理。
- 骨链物理插件（Wiggle、Spring Bones 等）提供交互式的二次动态。mmdance 自行烘焙模拟，因此构建可复现、可在无界面模式下运行。
