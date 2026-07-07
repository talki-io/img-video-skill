# 供应商与模型参考

模型层是**可插拔适配架构**（Adapter + Factory + 责任链）：主用供应商没配密钥或调不通时，
沿回退链自动降级到下一个。默认走**接口AI（jiekou.ai）**多模型中转，也可直连各家或换其它中转。

## 1. 能力矩阵

| `type` | 服务 | 文生图 | 图生视频 | 凭据字段 |
|---|---|:---:|:---:|---|
| `jiekou` | **接口AI 中转**（聚合 Midjourney/Flux/Seedance/可灵/Sora/Veo，**默认**） | ✅ | ✅ | `api_key` |
| `ark` / `jimeng` | 字节**即梦**（火山方舟 Seedream/Seedance，直连） | ✅ | ✅ | `api_key` |
| `kling` | 快手**可灵**（直连） | ✅ | ✅ | `access_key` + `secret_key` |
| `gemini` | Google（Imagen / Veo，直连） | ✅ | ✅ | `api_key` |
| `relay` | 其它 OpenAI 兼容中转 | ✅ | ⚠️ 取决于网关 | `api_key` |

> 「具备某能力」= **既配了凭据、又配了对应的 `image_model` / `video_model`**。缺任一即视为不支持、自动跳过。

## 2. 选择与回退逻辑

- `default_provider`：主用供应商（默认 `jiekou`）。
- `fallback`：回退链（数组，按序尝试）。
- 运行时：先试主用 → 没密钥/没配对应模型的**自动跳过** → 运行失败的**降级到下一个** → 全失败才报错。
- `--provider <name>`：单次调用**强制指定**某家，跳过回退链。
- `python scripts/generate.py providers`：查看当前配置下每家的能力与尝试顺序。

## 3. 全局配置项

置于 `config.json` 顶层，作为各供应商的默认值（供应商内可同名覆盖）：

| 键 | 默认 | 说明 |
|---|---|---|
| `default_provider` | — | 主用供应商名 |
| `fallback` | `[]` | 回退链（供应商名数组） |
| `timeout` | `120` | 单次 HTTP 超时（秒） |
| `max_retries` | `3` | 5xx / 网络异常的重试次数（指数退避） |
| `poll_interval` | `5` | 异步任务轮询间隔（秒） |
| `poll_timeout` | `600` | 异步任务总超时（秒） |
| `providers` | — | 供应商名 → 该供应商配置 的映射（必填） |

## 4. 接口AI jiekou.ai（默认中转，已实测打通 ✅）

官方文档：<https://docs.jiekou.ai/docs/support/quickstart>

**真实契约（实测确认）：**

- **Base URL**：`https://api.highwayapi.ai`
- **认证**：请求头 `Authorization: Bearer <api_key>`
- **提交**：`POST /v3/async/<模型slug>` → 返回 `{"task_id": "..."}`
- **查询**：`GET /v3/async/task-result?task_id=<id>`（路径可用 `query_path` 覆盖），返回：
  ```json
  { "task": {"status": "TASK_STATUS_SUCCEED", "progress_percent": 0},
    "images": [{"image_url": "..."}], "videos": [{"video_url": "...", "video_type": "mp4"}] }
  ```
- **状态词**：`TASK_STATUS_QUEUED` / `TASK_STATUS_PROCESSING` / `TASK_STATUS_SUCCEED` / `TASK_STATUS_FAILED`。
- **文生图请求体**：`{ "<prompt_field>": ..., "aspect_ratio": "1:1" }`；`image_extra` 可追加字段。
- **图生视频请求体**：`{ "prompt": ..., "image": "<data URI 或公网 URL>", "resolution": ..., "duration": ... }`
  —— ⚠️ `image` 上游映射为 `image_url`，**必须是 data URI（`data:image/png;base64,...`）或公网 URL，不能是裸 base64**；
  脚本已自动把本地图片编码成 data URI。`video_extra` 可追加 `aspect_ratio`/`seed`/`camera_fixed`/`last_image` 等。

### 4.1 已实测可用的模型 slug

| 用途 | slug 示例 |
|---|---|
| 文生图 | `flux-2-pro`、`z-image-turbo`（快）、`qwen-image-txt2img`、`mj-txt2img`（Midjourney） |
| 图生视频 | `sora-2-img2video` ✅、`seedance-v1-pro-i2v` ✅、`veo-3.1-generate-img2video`、`minimax-hailuo-2.3-i2v` |
| 文生视频 | `seedance-2.0`、`veo-3.1-generate-text2video`、`veo-3.0-generate-001-text2video` |

> 多数 slug = 官方模型文档页名去掉 `reference-` 前缀（如 `reference-flux-2-pro` → `flux-2-pro`）。
> 完整清单见 <https://docs.jiekou.ai/llms.txt>。换模型直接改 config 里的 `image_model` / `video_model`。

### 4.2 jiekou 专属配置项

| 键 | 默认 | 作用 |
|---|---|---|
| `prompt_field` | `prompt` | 提示词字段名。**Midjourney 用 `text`** |
| `send_aspect_ratio` | `true` | 是否发送 `aspect_ratio`。MJ 不吃该字段，置 `false`（改用 `--ar` 写进提示词） |
| `image_extra` | `{}` | 并入文生图请求体的自定义字段 |
| `resolution` | 不发 | 图生视频分辨率（如 `720p`/`1080p`），各模型枚举不同 |
| `duration` | 不发 | 图生视频时长；Seedance 用 `5`/`10`，Sora 2 用 `4`/`8`/`12`（错值 400） |
| `video_extra` | `{}` | 并入图生视频请求体的自定义字段 |
| `query_path` | `/v3/async/task-result` | 任务结果查询路径 |

### 4.3 各模型字段差异速查

| 差异点 | 说明 | 相关 config 字段 |
|---|---|---|
| 提示词字段名 | 多数用 `prompt`；**Midjourney 用 `text`** | `prompt_field` |
| 宽高比字段 | 多数支持 `aspect_ratio`；MJ 不吃（用 `--ar 1:1` 写进提示词） | `send_aspect_ratio` |
| 视频时长枚举 | Seedance `5`/`10`；**Sora 2 `4`/`8`/`12`**；**Veo `duration_seconds` 4/6/8** | `duration` / `video_extra` |
| 分辨率枚举 | 各模型不同，见其文档 | `resolution` |
| 输出多图 | **Midjourney 一次返回 4 张** | —（脚本自动全保存） |

> **Veo 尤其注意**：它用 `duration_seconds`（不是 `duration`，枚举 4/6/8）且 `generate_audio` 必填。
> 用 `video_extra` 传这两个字段，并从 config **删掉 `duration` 键**，避免发出未知字段。

### 4.4 已实测配置速查

- **Midjourney 文生图**：`image_model="mj-txt2img"`, `prompt_field="text"`, `send_aspect_ratio=false`（一次 4 张）
- **Sora 2 图生视频**：`video_model="sora-2-img2video"`, `duration=8`（或 4/12）
- **Seedance 图生视频**：`video_model="seedance-v1-pro-i2v"`, `duration=5`（或 10）
- **Veo 3.1 图生视频（带原生音频）**：`video_model="veo-3.1-generate-img2video"`, `resolution="720p"`（或 1080p），
  删除 `duration` 键，`video_extra={"generate_audio":true,"duration_seconds":8}`（时长 4/6/8）

### 4.5 旗舰图像模型的 slug 取法

Gemini 3 Pro Image / Seedream 4.x / GPT-Image-2 等旗舰模型的真实接口 slug 与文档页名不一致，
且**只显示在 Playground**（API 探测取不到，但账号可用——同级的 Veo 3 / Sora 2 均可用）。取法：
登录 <https://jiekou.vip> → 打开该模型卡「试用模型」→ 代码示例里形如 `POST /v3/async/<真实slug>`
→ 把 `<真实slug>` 填到 config 的 `image_model`。脚本已兼容这些模型的 `image_urls` 字段。

> **模型列表接口**：`GET https://api.highwayapi.ai/openai/v1/models`（Bearer 认证，OpenAI 兼容）
> 可列出账号可用的 chat / 图像模型 id；但 `/v3/async` 的媒体模型（flux/seedance/sora 等）不在此列表，
> 其 slug 见各模型文档页或 Playground。

### 4.6 配置示例

```json
{ "type": "jiekou", "base_url": "https://api.highwayapi.ai", "api_key": "sk-...",
  "image_model": "flux-2-pro", "video_model": "seedance-v1-pro-i2v",
  "query_path": "/v3/async/task-result", "resolution": "720p", "duration": 5 }
```

## 5. 直连各家（可选）

### 5.1 ark / jimeng（即梦，火山方舟）

```json
{ "type": "ark", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key": "ark-...",
  "image_model": "doubao-seedream-3-0-t2i-...", "video_model": "doubao-seedance-1-0-lite-i2v-..." }
```

文生图（Seedream）兼容 OpenAI images 协议；图生视频（Seedance）走 Ark 内容生成任务（`/contents/generations/tasks`，提交+轮询）。

### 5.2 kling（可灵）

```json
{ "type": "kling", "base_url": "https://api.klingai.com",
  "access_key": "...", "secret_key": "...", "image_model": "kling-v1", "video_model": "kling-v1" }
```

用 `access_key`/`secret_key` 自动签发短时 JWT（HS256，脚本内置标准库实现，无额外依赖）；文生图与图生视频均为异步任务，自动轮询。

### 5.3 gemini（Google）

```json
{ "type": "gemini", "base_url": "https://generativelanguage.googleapis.com", "api_key": "AIza...",
  "image_model": "imagen-3.0-generate-002", "video_model": "veo-2.0-generate-001" }
```

文生图走 Imagen `:predict`；图生视频走 Veo `:predictLongRunning` 长任务；密钥以 `?key=` 传。

### 5.4 relay（其它 OpenAI 兼容中转）

```json
{ "type": "relay", "base_url": ".../v1", "api_key": "sk-...",
  "image_model": "gpt-image-1", "video_model": null }
```

文生图走 `/images/generations`（兼容 `url` 与 `b64_json`）。若中转支持视频，填 `video_model`；
必要时用 `video_submit_path`（默认 `/videos/generations`）、`video_status_path`（默认 `/videos/generations/{id}`）调整路径。

## 6. 适配新供应商

各家接口字段可能随版本变化。脚本已对响应做了容错（深度查找 `url`/`b64`/`task_id`/`status`，
并把 list/嵌套输出归一成 URL）。若某家字段特殊：

1. **小改**：调整该供应商 config 里的路径/额外字段（如 jiekou 的 `query_path`、`image_extra`/`video_extra`）。
2. **大改**：在 `scripts/providers.py` 新增一个 `Provider` 子类，实现 `generate_image` /
   `generate_video`（返回 `list[bytes]`），注册到 `REGISTRY` 即可——回退链、保存、命名等无需改动（开闭原则）。
