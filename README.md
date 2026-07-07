# VisionBridge · 素材生成桥

> 让 Claude 也能"生成图片和视频"的 Agent Skill。

Claude 自身无法生成像素，但可以调用外部模型服务来生成。**VisionBridge** 把这条链路封装成一个
可直接调用的脚本：给提示词 → 拿到图片/视频文件 → 落地到项目 `assets/` 目录 → 返回相对路径，
让 Claude 在做网页、PPT、平面设计、海报等任务时，能直接把真实素材写进 HTML / PPT / Markdown，
而不是留一句"（此处放一张图）"。

默认接入 **[接口AI · jiekou.ai](https://jiekou.ai)** 多模型中转，一个 API Key 即可覆盖
Midjourney、Veo 3、Sora 2、Seedance、Flux、可灵 等几十个图像/视频模型；也支持直连即梦、可灵、
Gemini 或其它 OpenAI 兼容中转。

---

## ✨ 特性

- **文生图 + 图生视频**：一个脚本两种能力，异步任务自动轮询到完成。
- **可插拔多供应商**：适配器（Adapter）+ 工厂（Factory）+ 责任链（Chain of Responsibility）架构，
  主用服务没密钥或调不通时**自动降级**到回退链下一家。
- **模型随意换**：改一行 config 就能在 Midjourney / Veo / Sora / Seedance / Flux… 之间切换。
- **落地即用**：素材自动存入 `assets/images` `assets/videos`，按文件头识别真实格式（jpg/png/webp/mp4）。
- **健壮**：缺密钥自动跳过、5xx 指数退避重试、失败降级、超时明确报错、密钥只存本地。
- **零重依赖**：Python 3 + `requests` 即可，可灵 JWT 鉴权用标准库手写。

## 🎨 支持的模型服务

| 类型 | 服务 | 文生图 | 图生视频 |
|---|---|:---:|:---:|
| `jiekou` | **接口AI 中转**（聚合 Midjourney/Flux/Seedance/可灵/Sora/Veo 等，**默认**） | ✅ | ✅ |
| `ark` / `jimeng` | 字节**即梦** Seedream/Seedance（直连） | ✅ | ✅ |
| `kling` | 快手**可灵**（直连） | ✅ | ✅ |
| `gemini` | Google Imagen / Veo（直连） | ✅ | ✅ |
| `relay` | 其它 OpenAI 兼容中转 | ✅ | ⚠️ 视网关而定 |

经实测跑通的 jiekou 组合：文生图 `mj-txt2img`（Midjourney，一次 4 张）、`flux-2-pro`、`qwen-image-txt2img`、
`z-image-turbo`；图生视频 `veo-3.1-generate-img2video`（Veo 3.1，可带原生音频）、`sora-2-img2video`、
`seedance-v1-pro-i2v`。完整清单与各模型字段差异见 [`references/providers.md`](references/providers.md)。

## 🚀 快速开始

### 1. 依赖

```bash
python3 -m pip install requests
```

### 2. 配置

```bash
cp config.example.json config.json
# 编辑 config.json，填入你的 API Key（问服务商索取，切勿硬编码到代码里）
```

`config.json` 已被 `.gitignore` 忽略，密钥只存本地、不会进版本库。

先自检可用性：

```bash
python scripts/generate.py providers
```

### 3. 生成

```bash
# 文生图
python scripts/generate.py image --prompt "扁平插画风的咖啡品牌 hero 图，暖色调，简洁留白"

# 图生视频（喂一张图）
python scripts/generate.py video --image assets/images/xxxx.png --prompt "镜头缓缓推进，光斑浮动"

# 指定某个供应商，跳过回退链
python scripts/generate.py image --prompt "..." --provider ark
```

脚本结束会打印落地文件的相对路径，直接用到 `<img src="assets/images/…">`、PPT 占位或 Markdown 里。

## 🧩 架构

```
提示词 → generate.py（编排：选供应商 / 回退链 / 保存 / 命名）
       → providers.py（各家 API 适配器，统一 generate_image / generate_video）
       → 异步提交 + 轮询 → 下载 → 存 assets/ → 回显相对路径
```

- **Adapter**：每家 API 一个 `Provider` 子类，把差异适配成统一接口（都返回素材字节）。
- **Factory**：`REGISTRY` + `build_provider()` 按 `type` 实例化。
- **Chain of Responsibility**：`default_provider → fallback[]` 顺序尝试，没密钥/不支持的自动跳过，
  运行失败的降级到下一家，全失败才报错并汇总原因。

## 🛠 换模型注意

不同模型的请求字段不一样（提示词字段名、时长枚举、必填项等），直接换模型名而不改这些字段会报 400。
config 已留好开关（`prompt_field` / `send_aspect_ratio` / `video_extra` / `duration` / `resolution`），
对照 [`references/providers.md`](references/providers.md) 的「各模型请求字段差异」速查表调整即可。

## 📁 项目结构

```
visionbridge/
├── SKILL.md                 # Agent Skill 定义（触发描述 + 用法）
├── config.example.json      # 配置模板（复制为 config.json 填密钥）
├── scripts/
│   ├── generate.py          # 入口：配置 / 供应商选择 / 回退 / 保存 / 命名
│   └── providers.py         # 适配层：Provider 基类 + 各家适配器 + 注册表
├── references/
│   └── providers.md         # 能力矩阵 + 各家配置 + 各模型字段差异 + 扩展指南
└── .gitignore               # 忽略 config.json（密钥）与 assets/（产物）
```

## 🤝 扩展新供应商

在 `scripts/providers.py` 新增一个 `Provider` 子类，实现 `generate_image` / `generate_video`，
注册到 `REGISTRY` 即可——回退链、保存、命名等无需改动（开闭原则）。详见 `references/providers.md` 末尾。

## 🔒 安全

- API Key 只存本地 `config.json`（已 gitignore），不进代码、不进版本库。
- 也支持用环境变量覆盖：`VISIONBRIDGE_CONFIG` 指定配置路径等。

## 📄 License

[MIT](LICENSE)
