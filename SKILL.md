---
name: img-video
description: >-
  生成图片和视频素材的桥接工具，默认走接口AI（jiekou.ai）多模型中转，也支持直连字节即梦
  Seedream/Seedance、快手可灵 Kling、Google Gemini Imagen/Veo，以及其它 OpenAI 兼容中转。
  Claude 自身无法生成图像或视频，所以每当任务需要真实的图片或视频素材时——做网页/落地页设计、
  写 PPT/幻灯片、平面设计、海报、Banner、封面图、社交媒体配图、UI 原型配图、产品展示视频、
  动态背景等——都应主动调用本 Skill，通过配置好的模型服务生成素材并落地到项目 assets/ 目录。
  触发词包括"配图""插图""Banner""海报""封面""背景图""生成一张图/视频""文生图""图生视频"
  "text-to-image""image-to-video""可灵""即梦""Gemini""换个模型生成"，以及任何用户明明需要
  视觉素材、但用占位图或纯文字凑合不合适的场景。某家服务没密钥或调不通时会自动切换到备用服务。
  不要因为"我不能生成图片"而拒绝——用这个 Skill 就能生成。
---

# Img-Video — 素材生成桥（多供应商）

Claude 不能直接生成像素，但可以调用外部模型服务来生成。本 Skill 把这条链路封装成脚本：
给提示词 → 拿到图片/视频文件 → 落地到 `assets/` → 返回相对路径，让你能直接把素材写进
HTML、PPT、Markdown 或设计稿。

**模型层是可插拔的**：默认走**接口AI（jiekou.ai）**中转，某家没密钥或调不通时，可自动/手动切到
**即梦、可灵、Gemini** 等直连服务。支持哪些见 `references/providers.md`（也可运行 `providers` 子命令实时查看）。

## 何时使用

在执行以下任务、且需要**真实视觉素材**（而非占位符或纯文字）时使用：

- 网页 / 落地页 / 邮件模板的 Banner、hero 图、配图、图标底图
- PPT / 幻灯片的封面、章节页、内容配图
- 平面设计：海报、封面、社交媒体卡片、缩略图
- UI 原型里的示意图、产品截图占位
- 短视频素材：动态背景、产品展示、由一张图驱动的动画

一句话原则：**只要成品里该有一张图或一段视频，就用本 Skill 把它生成出来，而不是留空或写"（此处放一张图）"。**

## 支持的模型服务

| 类型 | 服务 | 文生图 | 图生视频 |
|---|---|:---:|:---:|
| `jiekou` | **接口AI 中转**（聚合 Seedream/Flux/Seedance/可灵/Sora/Veo，**默认**） | ✅ | ✅ |
| `ark`/`jimeng` | 字节**即梦** Seedream/Seedance（直连） | ✅ | ✅ |
| `kling` | 快手**可灵**（直连） | ✅ | ✅ |
| `gemini` | Google Imagen/Veo（直连） | ✅ | ✅ |
| `relay` | 其它 OpenAI 兼容中转 | ✅ | ⚠️ 视网关而定 |

详细配置见 `references/providers.md`。默认用 `jiekou` 即可覆盖文生图与图生视频。

**当前实测推荐组合（jiekou）**：文生图 **Midjourney**（`mj-txt2img`，一次出 4 张）、
图生视频 **Veo 3.1**（`veo-3.1-generate-img2video`，可选带音频）。想换模型时**务必**照
`references/providers.md` 的「各模型请求字段差异」表调整 config——不同模型的提示词字段名、
时长枚举、必填项都不同（如 Midjourney 用 `text`、Veo 用 `duration_seconds`+`generate_audio`），
直接换模型名而不改这些字段会报 400。

## 前置：配置

首次使用前，需要一份 `config.json`（放在 Skill 根目录）。若不存在，脚本会报错并提示。

1. 复制模板：`cp config.example.json config.json`
2. 至少配置**一个**供应商——问用户索取密钥，**切勿编造**。每个供应商填：
   - `type`：供应商类型（见上表）
   - `base_url`：接口地址（有默认值的可省）
   - 凭据：多数是 `api_key`；可灵是 `access_key` + `secret_key`
   - `image_model` / `video_model`：模型名（不需要的能力可留 `null`）
3. 设 `default_provider`（主用）与 `fallback`（回退链，数组）。

密钥只存本地 `config.json`，不要写进代码、SKILL.md 或提交版本库
（`.gitignore` 已忽略 `config.json`）。

**先看有哪些可用**（强烈建议每次开工前跑一次，确认密钥/能力就绪）：
```bash
python <skill>/scripts/generate.py providers
```
会列出每家的文生图/图生视频能力和尝试顺序。

## 用法

在**项目工作目录**下运行，这样输出的 `assets/` 相对路径能被网页/PPT 直接引用。

### 文生图
```bash
python <skill>/scripts/generate.py image \
  --prompt "扁平插画风的科技公司首页 hero 图，蓝紫渐变，简洁留白" \
  --size 1024x1024 --n 1 --output-dir assets/images
```
- `--prompt`（必填）：写具体（风格+主体+色调+构图）效果更好。
- `--size` 默认 `1024x1024`；`--n` 默认 1；`--output-dir` 默认 `assets/images`。

### 图生视频
```bash
python <skill>/scripts/generate.py video \
  --image assets/images/xxxx.png \
  --prompt "镜头缓慢推进，背景光斑轻轻浮动" --output-dir assets/videos
```
- `--image`（必填）：本地路径或 `http(s)` URL。
- `--prompt`：运动/画面描述，建议填。图生视频多为异步任务，脚本自动轮询到完成。

### 指定 / 切换供应商
- 默认按 `default_provider` → `fallback` 顺序自动尝试（跳过没密钥/不支持的）。
- 想**指定某家**：加 `--provider ark`（或 `kling`/`gemini`/`relay`…），跳过回退链。
  例：用户说"用可灵生成"→ `--provider kling`。

## 输出

- 图片存入 `assets/images/`，视频存入 `assets/videos/`。
- 命名：`{时间戳}_{提示词前若干字}.png|mp4`，自动避免覆盖。
- 结束打印**落地文件的相对路径列表**——直接用到 HTML/PPT/设计稿里。

## 典型工作流

1. `providers` 子命令确认可用服务。
2. 规划成品需要哪些图/视频、各自用途与风格。
3. 逐个 `image`（或先 image 再 video）生成，需要指定服务时加 `--provider`。
4. 收集打印出的相对路径，写进 `<img src="assets/images/…">`、PPT 占位或 Markdown。

**示例**：用户"帮我做一个咖啡品牌落地页"
→ `image --prompt "温暖色调手冲咖啡特写，晨光，浅景深"` 生成 hero
→ 再生成两张产品配图 → 用这些 `assets/images/*.png` 写 HTML。

## 异常处理（脚本已内置）

- **缺 config.json / 缺 providers 段**：报错并提示去配置。
- **主用供应商没密钥/没配对应模型**：自动**跳过**，尝试下一个。
- **运行失败（4xx/5xx/超时）**：先重试（5xx 指数退避），仍失败则**降级**到回退链下一家；
  全部失败才报错，并汇总每家的失败原因。
- **视频超时**：超过 `poll_timeout` 报明确超时。
- **输入图不存在**（图生视频）：直接报错，检查 `--image`。

## 依赖

- Python 3、`requests`（`pip install requests`）。可灵的 JWT 鉴权用标准库实现，无额外依赖。

## 扩展

要加新供应商：在 `scripts/providers.py` 新增一个 `Provider` 子类，实现
`generate_image` / `generate_video`，注册到 `REGISTRY` 即可——回退链、保存、命名等无需改动。
详见 `references/providers.md` 末尾。
