#!/usr/bin/env python3
"""
VisionBridge — 素材生成入口（orchestrator）

通过多家「接口AI jiekou / 即梦 / 可灵 / Gemini / 其它中转」适配器生成图片与视频，
按「主用供应商 + 回退链」依次尝试：没配密钥或不支持该能力的自动跳过，
运行失败则降级到下一个；素材落地 assets/ 并打印相对路径。

用法：
    python generate.py image --prompt "..." [--size 1024x1024] [--n 1]
                             [--output-dir assets/images] [--provider ark]
    python generate.py video --image assets/images/x.png --prompt "镜头推进"
                             [--output-dir assets/videos] [--provider kling]
    python generate.py providers      # 列出当前配置下可用的供应商与能力

配置：默认读 Skill 根目录的 config.json，可用 --config 或环境变量 VISIONBRIDGE_CONFIG 覆盖。
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import Http, ProviderError, Unsupported, build_provider, REGISTRY  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent


def die(msg, code=1):
    print(f"[错误] {msg}", file=sys.stderr)
    sys.exit(code)


# ---------- 配置 ----------

def load_config(explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("VISIONBRIDGE_CONFIG"):
        candidates.append(Path(os.environ["VISIONBRIDGE_CONFIG"]))
    candidates.append(SKILL_ROOT / "config.json")
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        die(f"找不到 config.json。请复制 {SKILL_ROOT/'config.example.json'} 为 "
            f"{SKILL_ROOT/'config.json'} 并配置至少一个供应商。")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"config.json 不是合法 JSON：{e}")
    if "providers" not in cfg or not isinstance(cfg["providers"], dict):
        die("config.json 缺少 providers 段（供应商→配置 的映射）。")
    return cfg


def provider_order(cfg, forced):
    """决定尝试顺序：--provider 指定则只用它；否则 default_provider + fallback。"""
    if forced:
        return [forced]
    order = []
    if cfg.get("default_provider"):
        order.append(cfg["default_provider"])
    order += [p for p in cfg.get("fallback", []) if p not in order]
    # 若都没配，退化为「配置里出现的所有供应商」
    if not order:
        order = list(cfg["providers"].keys())
    return order


def make_provider(name, cfg):
    pcfg = dict(cfg["providers"].get(name) or {})
    # 供应商未在 providers 段声明，但类型已知时，允许空配置（便于报"没配密钥"）
    ptype = pcfg.get("type", name)
    http = Http(timeout=pcfg.get("timeout", cfg.get("timeout", 120)),
                max_retries=pcfg.get("max_retries", cfg.get("max_retries", 3)))
    pcfg.setdefault("poll_interval", cfg.get("poll_interval", 5))
    pcfg.setdefault("poll_timeout", cfg.get("poll_timeout", 600))
    provider = build_provider(ptype, pcfg, http)
    provider.name = name  # 日志用配置里的名字（如 relay），而非底层适配器类型
    return provider


# ---------- 命名与保存 ----------

def slugify(text, limit=30):
    text = re.sub(r"\s+", "-", (text or "asset").strip())
    text = re.sub(r"[^\w一-鿿\-]", "", text)
    text = re.sub(r"-{2,}", "-", text)[:limit].strip("-")
    return text or "asset"


def sniff_ext(data, default):
    """按文件头识别真实格式，避免"其实是 JPEG 却存成 .png"这类扩展名不符。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"GIF8":
        return "gif"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    return default


def save_all(chunks, output_dir, prompt, default_ext):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{slugify(prompt)}"
    paths = []
    for i, data in enumerate(chunks):
        ext = sniff_ext(data, default_ext)
        name = f"{base}.{ext}" if i == 0 else f"{base}-{i}.{ext}"
        p = out / name
        j = 1
        while p.exists():
            p = out / f"{base}-{i}-{j}.{ext}"
            j += 1
        p.write_bytes(data)
        paths.append(p)
    return paths


def emit(paths):
    print("\n生成完成，文件如下：")
    for p in paths:
        try:
            rel = p.resolve().relative_to(Path.cwd())
        except ValueError:
            rel = p.resolve()
        print(f"  {rel}")


# ---------- 责任链：按顺序尝试供应商 ----------

def run_chain(cfg, kind, forced, action):
    order = provider_order(cfg, forced)
    errors = []
    attempted = False
    for name in order:
        try:
            provider = make_provider(name, cfg)
        except ProviderError as e:
            errors.append(f"{name}: {e}")
            continue
        if not provider.can(kind):
            reason = "缺密钥" if not provider.has_credentials() else f"未配 {kind} 模型"
            print(f"[跳过] {name}：{reason}", file=sys.stderr)
            errors.append(f"{name}: 跳过（{reason}）")
            continue
        attempted = True
        print(f"[使用] {name} 生成{('图片' if kind=='image' else '视频')}…", file=sys.stderr)
        try:
            return action(provider)
        except Unsupported as e:
            errors.append(f"{name}: {e}")
        except ProviderError as e:
            print(f"[失败] {name}：{e}，尝试降级…", file=sys.stderr)
            errors.append(f"{name}: {e}")
    if not attempted:
        die("没有可用的供应商。请检查 config.json 是否为目标能力配置了密钥与模型。\n  详情：\n  "
            + "\n  ".join(errors))
    die("所有供应商均失败：\n  " + "\n  ".join(errors))


# ---------- 子命令 ----------

def cmd_image(args, cfg):
    paths = run_chain(cfg, "image", args.provider,
                      lambda p: save_all(p.generate_image(args.prompt, args.size, args.n),
                                         args.output_dir, args.prompt, "png"))
    emit(paths)


def cmd_video(args, cfg):
    paths = run_chain(cfg, "video", args.provider,
                      lambda p: save_all(p.generate_video(args.image, args.prompt),
                                         args.output_dir, args.prompt or "video", "mp4"))
    emit(paths)


def cmd_providers(args, cfg):
    print("当前配置下的供应商能力：\n")
    order = provider_order(cfg, None)
    for name in cfg["providers"]:
        try:
            p = make_provider(name, cfg)
            img = "✅" if p.can("image") else "—"
            vid = "✅" if p.can("video") else "—"
            role = "主用" if cfg.get("default_provider") == name else (
                   "回退" if name in cfg.get("fallback", []) else "备用")
            print(f"  {name:10s} 文生图 {img}  图生视频 {vid}  [{role}]")
        except ProviderError as e:
            print(f"  {name:10s} 配置错误：{e}")
    print(f"\n支持的供应商类型：{', '.join(sorted(set(REGISTRY)))}")
    print(f"尝试顺序：{' → '.join(order)}")


# ---------- 入口 ----------

def main():
    ap = argparse.ArgumentParser(description="VisionBridge 素材生成")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("image", help="文生图")
    pi.add_argument("--prompt", required=True)
    pi.add_argument("--size", default="1024x1024")
    pi.add_argument("--n", type=int, default=1)
    pi.add_argument("--output-dir", default="assets/images")
    pi.add_argument("--provider", help="强制指定供应商，跳过回退链")

    pv = sub.add_parser("video", help="图生视频")
    pv.add_argument("--image", required=True)
    pv.add_argument("--prompt", default="")
    pv.add_argument("--output-dir", default="assets/videos")
    pv.add_argument("--provider")

    sub.add_parser("providers", help="列出可用供应商与能力")

    args = ap.parse_args()
    cfg = load_config(args.config)

    {"image": cmd_image, "video": cmd_video, "providers": cmd_providers}[args.command](args, cfg)


if __name__ == "__main__":
    main()
