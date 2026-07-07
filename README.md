# Img-Video · 素材生成 Skill

> 一个 **Claude Agent Skill**：让 Claude / Claude Code 也能“生成图片和视频”。

Claude 本身不会生成像素。装上本 Skill 后，当 Claude 在做**网页设计、PPT、平面设计、海报、Banner、配图、
产品视频**等需要真实视觉素材的任务时，会**自动触发**它——通过外部模型服务生成图片/视频，落地到项目
`assets/` 目录，再直接写进 HTML / PPT / Markdown，而不是留一句“（此处放一张图）”。

默认接入 **[接口AI · jiekou.ai](https://jiekou.ai)** 多模型中转，一个 API Key 即可覆盖
Midjourney、Veo 3、Sora 2、Seedance、Flux 等几十个图像/视频模型。

## 🖼 示例效果

<p align="center">
  <img src="docs/demo-midjourney.png" width="420" alt="Img-Video 示例：Midjourney 生成的雪地柴犬">
</p>

<p align="center"><sub>由本 Skill 调用 <b>Midjourney</b>（<code>mj-txt2img</code>）真实生成 · 提示词：<i>一只戴红色围巾的柴犬坐在雪地里，扁平插画风，薄荷绿背景</i></sub></p>

图生视频（Veo 3.1 / Sora 2）还能把这样一张图变成带镜头运动、可选原生音频的短视频。

## 为什么是 Skill？

[Agent Skill](https://docs.claude.com/en/docs/claude-code/skills) 是一个带 `SKILL.md` 的文件夹，
Claude 读取其中的**描述**来判断“这个任务要不要用它”。装上后你**不用记命令**——正常让 Claude
“帮我做个咖啡品牌落地页”，它自己就会用本 Skill 生成 hero 图、配图甚至展示视频。当然也可手动跑脚本（见下）。

[`SKILL.md`](SKILL.md) 告诉 Claude 三件事：

- **何时触发**：任务里出现“配图/插图/Banner/海报/封面/文生图/图生视频…”，或任何该有图/视频却想留空的场景。
- **怎么用**：调用 `scripts/generate.py` 生成素材、拿回相对路径。
- **别拒绝**：不要因为“我不能生成图片”而回绝——用这个 Skill 就能生成。

## 📦 安装

把本仓库克隆到 Claude 的技能目录，文件夹名用技能名 `img-video`：

```bash
# 个人级（对所有项目生效）
git clone https://github.com/talki-io/img-video-skill.git ~/.claude/skills/img-video

# 或 项目级（只对某个项目生效）
git clone https://github.com/talki-io/img-video-skill.git <你的项目>/.claude/skills/img-video
```

然后装依赖、填 API Key、自检：

```bash
cd ~/.claude/skills/img-video
python3 -m pip install requests
cp config.example.json config.json      # 编辑 config.json 填入你的 jiekou API Key
python scripts/generate.py providers     # 自检可用性与尝试顺序
```

`config.json` 已被 `.gitignore` 忽略，密钥只存本地、不进版本库。装好后新开一个 Claude Code 会话即可自动调用。

## 🎨 支持的模型

| `type` | 服务 | 文生图 | 图生视频 |
|---|---|:---:|:---:|
| `jiekou` | **接口AI 中转**（聚合 Midjourney/Flux/Seedance/可灵/Sora/Veo，**默认**） | ✅ | ✅ |
| `ark` / `jimeng` | 字节**即梦** Seedream/Seedance（直连） | ✅ | ✅ |
| `kling` | 快手**可灵**（直连） | ✅ | ✅ |
| `gemini` | Google Imagen / Veo（直连） | ✅ | ✅ |
| `relay` | 其它 OpenAI 兼容中转 | ✅ | ⚠️ 视网关而定 |

实测跑通的 jiekou 组合：文生图 `mj-txt2img`（Midjourney，一次 4 张）、`flux-2-pro`、`qwen-image-txt2img`；
图生视频 `veo-3.1-generate-img2video`（Veo 3.1，可带原生音频）、`sora-2-img2video`、`seedance-v1-pro-i2v`。
完整清单与各模型字段差异见 [`references/providers.md`](references/providers.md)。

## 🖐 手动使用（不经过 Claude 也能跑）

```bash
# 文生图
python scripts/generate.py image --prompt "扁平插画风的咖啡品牌 hero 图，暖色调，简洁留白"

# 图生视频（喂一张图）
python scripts/generate.py video --image assets/images/xxxx.png --prompt "镜头缓缓推进，光斑浮动"

# 指定某个供应商，跳过自动回退
python scripts/generate.py image --prompt "..." --provider ark

# 查看当前配置下有哪些可用服务
python scripts/generate.py providers
```

脚本结束会打印落地文件的相对路径，直接用到 `<img src="assets/images/…">`、PPT 占位或 Markdown 里。

## 🧩 工作原理

```
Claude 判断任务需要素材 →（触发 Skill）→ scripts/generate.py
   → providers.py 里对应供应商的适配器 → 异步提交 + 轮询到完成
   → 下载素材 → 存 assets/ → 回显相对路径 → Claude 写进成品
```

模型层是**可插拔多供应商**架构：

- **Adapter（适配器）**：每家 API 一个 `Provider` 子类，把差异适配成统一的 `generate_image` / `generate_video`。
- **Factory（工厂）**：`REGISTRY` + `build_provider()` 按 `type` 实例化。
- **Chain of Responsibility（责任链）**：`default_provider → fallback[]` 顺序尝试，
  没密钥/不支持的自动跳过，运行失败的降级到下一家，全失败才报错。

## 📁 项目结构

```
img-video/                   # ← 放进 ~/.claude/skills/ 的技能文件夹
├── SKILL.md                 # ★ 技能核心：触发描述 + 用法（Claude 读这个决定是否调用）
├── config.example.json      # 配置模板（复制为 config.json 填密钥）
├── scripts/
│   ├── generate.py          # 入口：配置 / 供应商选择 / 回退 / 保存 / 命名
│   └── providers.py         # 适配层：Provider 基类 + 各家适配器 + 注册表
├── references/
│   └── providers.md         # 能力矩阵 + 各家配置 + 各模型字段差异 + 扩展指南
└── .gitignore               # 忽略 config.json（密钥）与 assets/（产物）
```

> `SKILL.md` 用渐进式加载（先只读描述，触发后才读正文，用到时才读 `references/`）让 Claude 高效地知道**何时用、怎么用**。

## 🛠 换模型注意

不同模型请求字段不一样（提示词字段名、时长/分辨率枚举、必填项），只改模型名而不改字段会报 400。
config 已留好开关（`prompt_field` / `send_aspect_ratio` / `video_extra` / `duration` / `resolution`），
对照 [`references/providers.md`](references/providers.md) 的「各模型字段差异」速查表调整即可。

## 🤝 扩展新供应商

在 `scripts/providers.py` 新增一个 `Provider` 子类，实现 `generate_image` / `generate_video`，
注册到 `REGISTRY` 即可——回退链、保存、命名等无需改动（开闭原则）。

## 🔒 安全

API Key 只存本地 `config.json`（已 gitignore），不进代码、不进版本库；也支持用环境变量 `IMGVIDEO_CONFIG` 指定配置路径。

## 📄 License

[MIT](LICENSE) · 依赖：Python 3 + `requests`
