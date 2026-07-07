"""
Img-Video 供应商适配层
==========================

把不同图像/视频生成服务的差异，收敛到一个统一接口后面。采用的模式：

- **Adapter（适配器）**：每个 Provider 子类把某家 API 的请求/响应，适配成统一的
  `generate_image` / `generate_video`（都返回 `list[bytes]`，即原始素材字节）。
- **Factory（工厂）**：`build_providers()` 按 config 里的 provider 类型实例化对应适配器。
- **Chain of Responsibility（责任链）**：orchestrator 按「主用 + 回退链」顺序尝试，
  没密钥或不支持该能力的供应商自动跳过，运行失败则降级到下一个。

新增一家服务 = 新增一个 Provider 子类并注册到 REGISTRY，其余代码不用动（开闭原则）。

统一契约：
    generate_image(prompt, size, n) -> list[bytes]   # 每个元素是一张图的字节
    generate_video(image_ref, prompt) -> list[bytes] # 每个元素是一段视频的字节
    能力不具备时抛 Unsupported；调用失败时抛 ProviderError。
"""

import base64
import hashlib
import hmac
import json
import mimetypes
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


# ---------- 异常 ----------

class ProviderError(Exception):
    """某供应商在运行期失败（网络/接口/超时），可触发降级到下一个。"""


class Unsupported(ProviderError):
    """该供应商不具备此能力（缺模型或缺该能力），应静默跳过。"""


# ---------- 共享工具 ----------

def log(msg: str):
    print(msg, file=sys.stderr)


def coerce_url(m):
    """把「可能是 str / list / dict」的输出，归一成一个 URL 字符串。"""
    if isinstance(m, str):
        return m
    if isinstance(m, list) and m:
        return coerce_url(m[0])
    if isinstance(m, dict):
        return deep_find(m, ("url", "video_url", "image_url", "output_url", "download_url"))
    return None


def deep_find(obj, keys):
    """在任意嵌套结构里深度优先查找首个命中 keys 的非空值。"""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k]:
                return obj[k]
        for v in obj.values():
            r = deep_find(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = deep_find(it, keys)
            if r is not None:
                return r
    return None


def load_image_ref(image: str):
    """返回 (kind, value, mime)：kind 为 'url' 或 'bytes'。"""
    parsed = urlparse(image)
    if parsed.scheme in ("http", "https"):
        return "url", image, None
    p = Path(image)
    if not p.is_file():
        raise ProviderError(f"输入图片不存在：{image}")
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return "bytes", p.read_bytes(), mime


def image_as_data_uri(image: str) -> str:
    kind, value, mime = load_image_ref(image)
    if kind == "url":
        return value
    return f"data:{mime};base64,{base64.b64encode(value).decode()}"


def image_as_base64(image: str) -> str:
    """裸 base64（无 data: 前缀）。若是 URL 则先下载。"""
    kind, value, _ = load_image_ref(image)
    if kind == "url":
        r = requests.get(value, timeout=60)
        r.raise_for_status()
        return base64.b64encode(r.content).decode()
    return base64.b64encode(value).decode()


class Http:
    """带重试的 HTTP 客户端；5xx 与网络异常按指数退避重试。"""

    def __init__(self, timeout=120, max_retries=3):
        self.timeout = timeout
        self.max_retries = max_retries

    def request(self, method, url, **kwargs):
        last = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(method, url, timeout=self.timeout, **kwargs)
                if resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}: {resp.text[:400]}"
                    log(f"[重试 {attempt}/{self.max_retries}] 服务端 {resp.status_code}")
                    time.sleep(min(2 ** attempt, 10))
                    continue
                return resp
            except requests.RequestException as e:
                last = str(e)
                log(f"[重试 {attempt}/{self.max_retries}] 网络异常：{e}")
                time.sleep(min(2 ** attempt, 10))
        raise ProviderError(f"请求失败（重试 {self.max_retries} 次）：{last}")

    def get_bytes(self, url) -> bytes:
        r = self.request("GET", url)
        if r.status_code != 200:
            raise ProviderError(f"下载失败 HTTP {r.status_code}：{url}")
        return r.content


# ---------- 基类 ----------

class Provider:
    name = "base"
    # 该供应商的凭据在 config 里叫什么（用于「有没有配密钥」判断）
    credential_keys = ("api_key",)

    def __init__(self, cfg: dict, http: Http):
        self.cfg = cfg
        self.http = http

    # -- 能力与凭据 --
    def has_credentials(self) -> bool:
        return all(self.cfg.get(k) for k in self.credential_keys)

    def can(self, kind: str) -> bool:
        """kind ∈ {'image','video'}：既有凭据又配了对应模型才算具备该能力。"""
        model = self.cfg.get("image_model" if kind == "image" else "video_model")
        return bool(self.has_credentials() and model)

    def base(self) -> str:
        return (self.cfg.get("base_url") or "").rstrip("/")

    def poll_cfg(self):
        return self.cfg.get("poll_interval", 5), self.cfg.get("poll_timeout", 600)

    # -- 能力实现（子类重写）--
    def generate_image(self, prompt, size, n) -> list:
        raise Unsupported(f"{self.name} 未实现文生图")

    def generate_video(self, image_ref, prompt) -> list:
        raise Unsupported(f"{self.name} 未实现图生视频")

    # -- 通用轮询（异步任务）--
    def poll_media(self, status_url, headers=None):
        interval, timeout = self.poll_cfg()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.http.request("GET", status_url, headers=headers)
            if r.status_code != 200:
                raise ProviderError(f"查询任务失败 HTTP {r.status_code}：{r.text[:400]}")
            payload = r.json()
            status = (deep_find(payload, ("status", "state", "task_status")) or "").lower()
            media = coerce_url(deep_find(payload, ("video_url", "mp4_url", "image_url",
                                                   "output_url", "download_url", "output",
                                                   "images", "videos", "url")))
            if status in ("failed", "error", "cancelled", "fail"):
                raise ProviderError(f"任务失败 status={status}：{json.dumps(payload, ensure_ascii=False)[:400]}")
            done = status in ("", "succeed", "succeeded", "success", "completed", "done", "finished")
            if media and (done or status not in ("submitted", "pending", "running", "processing", "queued", "in_progress")):
                return media
            log(f"[{self.name}] 任务进行中 status={status or '未知'}，{interval}s 后重试…")
            time.sleep(interval)
        raise ProviderError(f"{self.name} 视频生成超时（>{timeout}s）")


# ---------- OpenAI 兼容网关 / 其它第三方中转 ----------

class OpenAICompatProvider(Provider):
    """通用 OpenAI 兼容协议：文生图 /images/generations（兼容 url 与 b64_json）；
    图生视频走通用 /videos/generations（提交+轮询），字段名容错，兼容同步直返。
    用于 jiekou 之外、遵循 OpenAI 协议的其它中转站。"""
    name = "relay"

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['api_key']}", "Content-Type": "application/json"}

    def generate_image(self, prompt, size, n):
        url = f"{self.base()}/images/generations"
        body = {"model": self.cfg["image_model"], "prompt": prompt, "n": n, "size": size}
        r = self.http.request("POST", url, headers=self._headers(), json=body)
        if r.status_code != 200:
            raise ProviderError(f"[{self.name}] 文生图 HTTP {r.status_code}：{r.text[:400]}")
        data = r.json().get("data") or []
        if not data:
            raise ProviderError(f"[{self.name}] 未返回图片：{r.text[:400]}")
        out = []
        for it in data:
            if it.get("b64_json"):
                out.append(base64.b64decode(it["b64_json"]))
            elif it.get("url"):
                out.append(self.http.get_bytes(it["url"]))
        return out

    def generate_video(self, image_ref, prompt):
        submit = f"{self.base()}{self.cfg.get('video_submit_path', '/videos/generations')}"
        body = {"model": self.cfg["video_model"], "prompt": prompt or "", "image": image_as_data_uri(image_ref)}
        r = self.http.request("POST", submit, headers=self._headers(), json=body)
        if r.status_code not in (200, 201, 202):
            raise ProviderError(f"[{self.name}] 视频提交 HTTP {r.status_code}：{r.text[:400]}")
        payload = r.json()
        media = deep_find(payload, ("video_url", "mp4_url", "url"))
        status = (deep_find(payload, ("status", "state")) or "").lower()
        if media and status not in ("pending", "running", "processing", "queued", "in_progress"):
            return [self.http.get_bytes(media)]
        task = deep_find(payload, ("task_id", "id", "request_id"))
        if not task:
            raise ProviderError(f"[{self.name}] 无法解析视频 URL/任务 id：{r.text[:400]}")
        path = self.cfg.get("video_status_path", "/videos/generations/{id}").format(id=task)
        media = self.poll_media(f"{self.base()}{path}", headers=self._headers())
        return [self.http.get_bytes(media)]


# ---------- 可灵 Kling（快手）----------

def _kling_jwt(ak: str, sk: str) -> str:
    """可灵用 access_key/secret_key 签发短时 JWT（HS256），此处用标准库手写。"""
    def b64(d):
        return base64.urlsafe_b64encode(d).rstrip(b"=")
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}).encode())
    signing = header + b"." + payload
    sig = b64(hmac.new(sk.encode(), signing, hashlib.sha256).digest())
    return (signing + b"." + sig).decode()


class KlingProvider(Provider):
    """可灵：文生图与图生视频均为异步任务。默认 base_url https://api.klingai.com"""
    name = "kling"
    credential_keys = ("access_key", "secret_key")

    def _headers(self):
        token = _kling_jwt(self.cfg["access_key"], self.cfg["secret_key"])
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def generate_image(self, prompt, size, n):
        base = self.base() or "https://api.klingai.com"
        r = self.http.request("POST", f"{base}/v1/images/generations", headers=self._headers(),
                              json={"model_name": self.cfg["image_model"], "prompt": prompt, "n": n})
        if r.status_code != 200:
            raise ProviderError(f"[kling] 文生图提交 HTTP {r.status_code}：{r.text[:400]}")
        task = deep_find(r.json(), ("task_id",))
        if not task:
            raise ProviderError(f"[kling] 未返回 task_id：{r.text[:400]}")
        # 可灵图片任务查询也在同一路径下
        interval, timeout = self.poll_cfg()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            q = self.http.request("GET", f"{base}/v1/images/generations/{task}", headers=self._headers())
            payload = q.json()
            status = (deep_find(payload, ("task_status",)) or "").lower()
            if status in ("failed", "fail"):
                raise ProviderError(f"[kling] 任务失败：{q.text[:400]}")
            urls = deep_find(payload, ("images",))
            if status == "succeed" and urls:
                return [self.http.get_bytes(u["url"]) for u in urls]
            log(f"[kling] 图片任务 status={status or '未知'}，{interval}s 后重试…")
            time.sleep(interval)
        raise ProviderError("[kling] 文生图超时")

    def generate_video(self, image_ref, prompt):
        base = self.base() or "https://api.klingai.com"
        body = {"model_name": self.cfg["video_model"], "image": image_as_base64(image_ref), "prompt": prompt or ""}
        r = self.http.request("POST", f"{base}/v1/videos/image2video", headers=self._headers(), json=body)
        if r.status_code != 200:
            raise ProviderError(f"[kling] 视频提交 HTTP {r.status_code}：{r.text[:400]}")
        task = deep_find(r.json(), ("task_id",))
        if not task:
            raise ProviderError(f"[kling] 未返回 task_id：{r.text[:400]}")
        media = self.poll_media(f"{base}/v1/videos/image2video/{task}", headers=self._headers())
        return [self.http.get_bytes(media)]


# ---------- 即梦 Jimeng（火山方舟 Seedream / Seedance）----------

class ArkProvider(Provider):
    """字节即梦，走火山方舟 Ark。文生图 Seedream 兼容 OpenAI images 协议；
    图生视频 Seedance 走 Ark 内容生成任务接口（提交+轮询）。
    默认 base_url https://ark.cn-beijing.volces.com/api/v3"""
    name = "ark"

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['api_key']}", "Content-Type": "application/json"}

    def _base(self):
        return self.base() or "https://ark.cn-beijing.volces.com/api/v3"

    def generate_image(self, prompt, size, n):
        body = {"model": self.cfg["image_model"], "prompt": prompt, "size": size,
                "n": n, "response_format": "url"}
        r = self.http.request("POST", f"{self._base()}/images/generations", headers=self._headers(), json=body)
        if r.status_code != 200:
            raise ProviderError(f"[ark] 文生图 HTTP {r.status_code}：{r.text[:400]}")
        data = r.json().get("data") or []
        if not data:
            raise ProviderError(f"[ark] 未返回图片：{r.text[:400]}")
        out = []
        for it in data:
            if it.get("url"):
                out.append(self.http.get_bytes(it["url"]))
            elif it.get("b64_json"):
                out.append(base64.b64decode(it["b64_json"]))
        return out

    def generate_video(self, image_ref, prompt):
        content = [{"type": "text", "text": prompt or ""},
                   {"type": "image_url", "image_url": {"url": image_as_data_uri(image_ref)}}]
        body = {"model": self.cfg["video_model"], "content": content}
        r = self.http.request("POST", f"{self._base()}/contents/generations/tasks",
                              headers=self._headers(), json=body)
        if r.status_code not in (200, 201, 202):
            raise ProviderError(f"[ark] 视频提交 HTTP {r.status_code}：{r.text[:400]}")
        task = deep_find(r.json(), ("id", "task_id"))
        if not task:
            raise ProviderError(f"[ark] 未返回任务 id：{r.text[:400]}")
        media = self.poll_media(f"{self._base()}/contents/generations/tasks/{task}", headers=self._headers())
        return [self.http.get_bytes(media)]


# ---------- Gemini（Google Imagen / Veo）----------

class GeminiProvider(Provider):
    """Google 生成式 AI：文生图用 Imagen predict，图生视频用 Veo 长任务。
    默认 base_url https://generativelanguage.googleapis.com。密钥以 ?key= 传。"""
    name = "gemini"

    def _base(self):
        return self.base() or "https://generativelanguage.googleapis.com"

    def _key(self):
        return {"key": self.cfg["api_key"]}

    def generate_image(self, prompt, size, n):
        model = self.cfg["image_model"]
        url = f"{self._base()}/v1beta/models/{model}:predict"
        body = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": n}}
        r = self.http.request("POST", url, params=self._key(),
                              headers={"Content-Type": "application/json"}, json=body)
        if r.status_code != 200:
            raise ProviderError(f"[gemini] 文生图 HTTP {r.status_code}：{r.text[:400]}")
        preds = r.json().get("predictions") or []
        out = []
        for p in preds:
            b64 = p.get("bytesBase64Encoded") or deep_find(p, ("bytesBase64Encoded", "b64_json"))
            if b64:
                out.append(base64.b64decode(b64))
        if not out:
            raise ProviderError(f"[gemini] 未返回图片：{r.text[:400]}")
        return out

    def generate_video(self, image_ref, prompt):
        model = self.cfg["video_model"]
        url = f"{self._base()}/v1beta/models/{model}:predictLongRunning"
        instance = {"prompt": prompt or ""}
        instance["image"] = {"bytesBase64Encoded": image_as_base64(image_ref), "mimeType": "image/png"}
        r = self.http.request("POST", url, params=self._key(),
                              headers={"Content-Type": "application/json"},
                              json={"instances": [instance]})
        if r.status_code != 200:
            raise ProviderError(f"[gemini] 视频提交 HTTP {r.status_code}：{r.text[:400]}")
        op = deep_find(r.json(), ("name",))
        if not op:
            raise ProviderError(f"[gemini] 未返回 operation：{r.text[:400]}")
        interval, timeout = self.poll_cfg()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            q = self.http.request("GET", f"{self._base()}/v1beta/{op}", params=self._key())
            payload = q.json()
            if payload.get("done"):
                b64 = deep_find(payload, ("bytesBase64Encoded",))
                media = deep_find(payload, ("video_url", "url", "uri"))
                if b64:
                    return [base64.b64decode(b64)]
                if media:
                    return [self.http.get_bytes(media)]
                raise ProviderError(f"[gemini] 任务完成但无视频：{q.text[:400]}")
            log(f"[gemini] Veo 任务进行中，{interval}s 后重试…")
            time.sleep(interval)
        raise ProviderError("[gemini] 视频生成超时")


# ---------- 接口AI jiekou.ai（第三方多模型中转）----------

def _aspect_ratio(size: str) -> str:
    """把 '1024x1024' 之类尺寸换算成 '1:1' / '16:9' 这种比例（jiekou 多按比例取图）。"""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
        from math import gcd
        g = gcd(w, h) or 1
        return f"{w // g}:{h // g}"
    except Exception:
        return "1:1"


class JiekouProvider(Provider):
    """接口AI（jiekou.ai）多模型中转。真实契约（经实测确认）：
      - 提交：POST {base}/v3/async/<模型slug>，Bearer 鉴权，返回 {"task_id": "..."}
      - 查询：GET  {base}/v3/async/task-result?task_id=<id>
              返回 {"task":{"status":"TASK_STATUS_SUCCEED"...}, "images":[{"image_url"}], "videos":[{"video_url"}]}
      - 状态：TASK_STATUS_SUCCEED / TASK_STATUS_PROCESSING / TASK_STATUS_QUEUED / TASK_STATUS_FAILED
    默认 base_url https://api.highwayapi.ai。模型 slug 见 references/providers.md 或官方文档
    （文生图如 flux-2-pro / z-image-turbo / qwen-image-txt2img；图生视频如 seedance-v1-pro-i2v）。"""
    name = "jiekou"

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['api_key']}", "Content-Type": "application/json"}

    def _base(self):
        return self.base() or "https://api.highwayapi.ai"

    def _submit(self, model, body):
        r = self.http.request("POST", f"{self._base()}/v3/async/{model}",
                              headers=self._headers(), json=body)
        if r.status_code not in (200, 201, 202):
            raise ProviderError(f"[jiekou] 提交任务 {model} HTTP {r.status_code}：{r.text[:400]}")
        task = deep_find(r.json(), ("task_id", "id"))
        if not task:
            raise ProviderError(f"[jiekou] 未返回 task_id：{r.text[:300]}")
        return task

    def _poll(self, task, want_keys):
        """轮询任务结果；want_keys 是候选输出字段（不同模型字段不同，如 images / image_urls /
        videos / video_urls），返回该类输出的 URL 列表。"""
        interval, timeout = self.poll_cfg()
        qp = self.cfg.get("query_path", "/v3/async/task-result")
        url = f"{self._base()}{qp}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.http.request("GET", url, headers=self._headers(), params={"task_id": task})
            if r.status_code != 200:
                raise ProviderError(f"[jiekou] 查询任务 HTTP {r.status_code}：{r.text[:300]}")
            payload = r.json()
            status = (deep_find(payload, ("status", "task_status")) or "").upper()
            if any(k in status for k in ("FAIL", "ERROR", "CANCEL")):
                reason = deep_find(payload, ("reason", "message")) or ""
                raise ProviderError(f"[jiekou] 任务失败 {status} {reason}：{r.text[:300]}")
            items = next((payload[k] for k in want_keys if payload.get(k)), [])
            urls = [u for u in (coerce_url(it) for it in items) if u]
            if urls:
                return urls
            if "SUCCEED" in status or "SUCCESS" in status:
                raise ProviderError(f"[jiekou] 任务完成但无输出（字段 {want_keys}）：{r.text[:300]}")
            prog = deep_find(payload, ("progress_percent",))
            log(f"[jiekou] 任务 {status or '进行中'}"
                + (f" {prog}%" if prog else "") + f"，{interval}s 后重试…")
            time.sleep(interval)
        raise ProviderError(f"[jiekou] 任务超时（>{timeout}s），task_id={task}")

    def generate_image(self, prompt, size, n):
        # 各模型提示词字段名不一（多数 prompt，Midjourney 用 text），用 prompt_field 兼容
        body = {self.cfg.get("prompt_field", "prompt"): prompt}
        if self.cfg.get("send_aspect_ratio", True):
            body["aspect_ratio"] = _aspect_ratio(size)
        body.update(self.cfg.get("image_extra", {}))
        out = []
        for _ in range(max(1, n)):  # 异步接口一次一任务，多图循环提交
            task = self._submit(self.cfg["image_model"], body)
            out += [self.http.get_bytes(u) for u in self._poll(task, ("images", "image_urls"))]
        return out

    def generate_video(self, image_ref, prompt):
        # image 字段上游映射为 image_url，需 data URI 或公网 URL（裸 base64 会被判非法）
        body = {"prompt": prompt or "", "image": image_as_data_uri(image_ref)}
        if self.cfg.get("resolution"):
            body["resolution"] = self.cfg["resolution"]
        if self.cfg.get("duration"):
            body["duration"] = self.cfg["duration"]
        body.update(self.cfg.get("video_extra", {}))
        task = self._submit(self.cfg["video_model"], body)
        return [self.http.get_bytes(u) for u in self._poll(task, ("videos", "video_urls"))]


# ---------- 注册表 / 工厂 ----------

REGISTRY = {
    "jiekou": JiekouProvider,  # 接口AI 第三方多模型中转（默认）
    "relay": OpenAICompatProvider,  # 其它 OpenAI 兼容中转，改 base_url 即可
    "kling": KlingProvider,    # 可灵（直连）
    "ark": ArkProvider,        # 即梦（火山方舟，直连）
    "jimeng": ArkProvider,     # 即梦别名
    "gemini": GeminiProvider,  # Google（直连）
}


def build_provider(ptype: str, cfg: dict, http: Http) -> Provider:
    cls = REGISTRY.get(ptype)
    if cls is None:
        raise ProviderError(f"未知供应商类型：{ptype}（支持：{', '.join(sorted(set(REGISTRY)))}）")
    return cls(cfg, http)
