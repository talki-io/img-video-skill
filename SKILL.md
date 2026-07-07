---
name: img-video
description: >-
  生成图片和视频素材的桥接工具。Claude 自身无法生成像素，本 Skill 通过外部模型服务产出真实素材并落地到项目
  assets/ 目录——默认走接口AI（jiekou.ai）多模型中转，也支持直连字节即梦 Seedream/Seedance、快手可灵
  Kling、Google Imagen/Veo，以及其它 OpenAI 兼容中转。凡任务需要真实图片/视频而非占位符时——网页/落地页、
  PPT/幻灯片、海报、Banner、封面、社交配图、UI 原型配图、产品展示视频、动态背景等——都应主动调用，不要因为
  “我不能生成图片”而拒绝。触发词：配图、插图、Banner、海报、封面、背景图、文生图、图生视频、text-to-image、
  image-to-video、可灵、即梦、Gemini、换个模型生成。某家没密钥或调不通时会自动切换到备用服务。
---

# Img-Video — 素材生成桥（多供应商）

Claude 不能直接生成像素，但可以调用外部模型服务。本 Skill 把这条链路封装成一个脚本：
**给提示词 → 拿到图片/视频 → 存入 `assets/` → 打印相对路径**，之后可直接写进 HTML、PPT、Markdown 或设计稿。

模型层可插拔：默认走**接口AI（jiekou.ai）**中转，某家没密钥或调不通时自动切到回退链上的
**即梦 / 可灵 / Gemini** 等。完整清单见 [`references/providers.md`](references/providers.md)。

## 何时使用

成品里**该有一张图或一段视频、且占位符或纯文字不合适**时，都用本 Skill 把它生成出来，典型场景：

- 网页 / 落地页 / 邮件模板：Banner、hero 图、配图、图标底图
- PPT / 幻灯片：封面、章节页、内容配图
- 平面设计：海报、封面、社交媒体卡片、缩略图
- UI 原型：示意图、产品截图占位
- 短视频：动态背景、产品展示、由一张图驱动的动画

> 一句话原则：不要留空或写“（此处放一张图）”，直接生成。

## 前置：配置

首次使用前需在 Skill 根目录准备一份 `config.json`（不存在时脚本会报错提示）：

1. 复制模板：`cp config.example.json config.json`
2. 至少配置**一个**供应商——密钥须向用户索取，**切勿编造**。每家填：
   - `type`：供应商类型（见下表）
   - `base_url`：接口地址（有默认值可省）
   - 凭据：多数是 `api_key`；可灵是 `access_key` + `secret_key`
   - `image_model` / `video_model`：模型名（不需要的能力留 `null`）
3. 设 `default_provider`（主用）与 `fallback`（回退链，数组）。

密钥只存本地 `config.json`（已被 `.gitignore` 忽略），不要写进代码、SKILL.md 或提交版本库。

**每次开工前先自检可用性**（确认密钥/能力就绪、查看尝试顺序）：

```bash
python <skill>/scripts/generate.py providers
```

## 用法

在**项目工作目录**下运行，使输出的 `assets/` 相对路径能被网页/PPT 直接引用。

### 文生图

```bash
python <skill>/scripts/generate.py image \
  --prompt "扁平插画风的科技公司首页 hero 图，蓝紫渐变，简洁留白" \
  --size 1024x1024 --n 1 --output-dir assets/images
```

| 参数 | 必填 | 默认 | 说明 |
|---|:---:|---|---|
| `--prompt` | ✅ | — | 写具体（风格+主体+色调+构图）效果更好 |
| `--size` |  | `1024x1024` | 部分中转按比例取图，会自动换算成 `1:1` 等 |
| `--n` |  | `1` | 生成张数 |
| `--output-dir` |  | `assets/images` | 输出目录 |
| `--provider` |  | 按回退链 | 强制指定某家，跳过回退链 |

### 图生视频

```bash
python <skill>/scripts/generate.py video \
  --image assets/images/xxxx.png \
  --prompt "镜头缓慢推进，背景光斑轻轻浮动" --output-dir assets/videos
```

| 参数 | 必填 | 默认 | 说明 |
|---|:---:|---|---|
| `--image` | ✅ | — | 本地路径或 `http(s)` URL |
| `--prompt` |  | 空 | 运动/画面描述，建议填 |
| `--output-dir` |  | `assets/videos` | 输出目录 |
| `--provider` |  | 按回退链 | 强制指定某家 |

图生视频多为异步任务，脚本自动轮询到完成。

### 指定 / 切换供应商

- 不加 `--provider` 时，按 `default_provider → fallback` 顺序自动尝试（跳过没密钥/不支持的）。
- 加 `--provider <name>`（如 `kling`/`ark`/`gemini`/`relay`）**强制指定**某家、跳过回退链。
  例：用户说“用可灵生成”→ `--provider kling`。

## 支持的模型服务

| `type` | 服务 | 文生图 | 图生视频 |
|---|---|:---:|:---:|
| `jiekou` | **接口AI 中转**（聚合 Midjourney/Flux/Seedance/可灵/Sora/Veo，**默认**） | ✅ | ✅ |
| `ark` / `jimeng` | 字节**即梦** Seedream/Seedance（直连） | ✅ | ✅ |
| `kling` | 快手**可灵**（直连） | ✅ | ✅ |
| `gemini` | Google Imagen/Veo（直连） | ✅ | ✅ |
| `relay` | 其它 OpenAI 兼容中转 | ✅ | ⚠️ 视网关而定 |

**实测推荐组合（jiekou）**：文生图 `mj-txt2img`（Midjourney，一次出 4 张）、`flux-2-pro`；
图生视频 `veo-3.1-generate-img2video`（Veo 3.1，可带原生音频）、`sora-2-img2video`、`seedance-v1-pro-i2v`。

> ⚠️ **换模型必看**：不同模型的提示词字段名、时长/分辨率枚举、必填项都不同（如 Midjourney 用 `text`、
> Veo 用 `duration_seconds`+`generate_audio`）。只改模型名而不改这些字段会报 400。
> config 已留好开关（`prompt_field` / `send_aspect_ratio` / `duration` / `resolution` / `video_extra`），
> 对照 [`references/providers.md`](references/providers.md) 的「各模型字段差异」速查表调整。

## 输出

- 图片存入 `assets/images/`，视频存入 `assets/videos/`。
- 命名：`{时间戳}_{提示词前若干字}.{png|jpg|mp4|…}`（按文件头识别真实格式，自动避免覆盖）。
- 结束打印**落地文件的相对路径列表**——直接用到 `<img src="assets/images/…">`、PPT 占位或 Markdown。

## 典型工作流

1. `providers` 子命令确认可用服务与尝试顺序。
2. 规划成品需要哪些图/视频、各自用途与风格。
3. 逐个 `image`（或先 `image` 再 `video`）生成，需要指定服务时加 `--provider`。
4. 收集打印的相对路径，写进成品。

**示例**：用户“帮我做一个咖啡品牌落地页”
→ `image --prompt "温暖色调手冲咖啡特写，晨光，浅景深"` 生成 hero
→ 再生成两张产品配图 → 用这些 `assets/images/*.png` 写 HTML。

## 异常与回退（脚本已内置）

- **缺 config.json / 缺 providers 段**：报错并提示去配置。
- **主用供应商没密钥/没配对应模型**：自动**跳过**，尝试下一个。
- **运行失败（4xx/5xx/超时）**：5xx 与网络异常按指数退避重试；仍失败则**降级**到回退链下一家；
  全部失败才报错，并汇总每家的失败原因。
- **视频超时**：超过 `poll_timeout` 报明确超时。
- **输入图不存在**（图生视频）：直接报错，检查 `--image`。

## 依赖与扩展

- **依赖**：Python 3 + `requests`（`pip install requests`）。可灵 JWT 鉴权用标准库实现，无额外依赖。
- **加新供应商**：在 `scripts/providers.py` 新增一个 `Provider` 子类，实现 `generate_image` /
  `generate_video`，注册到 `REGISTRY` 即可——回退链、保存、命名等无需改动。详见
  [`references/providers.md`](references/providers.md) 末尾。
