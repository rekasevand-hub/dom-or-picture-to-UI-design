# -*- coding: utf-8 -*-
"""acctoken 网关健康检查（轻量，不引 openai 重试）。

用法（在项目根目录运行）:
    python scripts/check_gateway.py [--attempts 2] [--chat-timeout 40]

行为:
    1. GET  {VISION_BASE_URL}/models          -- 网关可达性 + 是否广播 VISION_MODEL
    2. POST {VISION_BASE_URL}/chat/completions -- 最小请求实测 qwen3-vl-plus 延迟/可用性

退出码: 0=健康, 1=配置缺失, 2=网关/鉴权/模型错误, 3=超时/不可达, 4=请求失败但不确定类别
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config.settings import load_config  # noqa: E402


def _redact(key: str | None) -> str:
    if not key:
        return "<missing>"
    return key[:6] + "..." + key[-4:] if len(key) > 12 else "***"


def _short(body: str | None, limit: int = 400) -> str:
    if not body:
        return ""
    body = " ".join(body.split())
    return body[:limit] + ("…" if len(body) > limit else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", type=int, default=1, help="chat 请求次数（默认 1）")
    ap.add_argument("--chat-timeout", type=float, default=40.0, help="每次 chat 请求超时秒数（默认 40）")
    args = ap.parse_args()

    cfg = load_config()
    base = (cfg.vision_base_url or "").rstrip("/")
    key = cfg.vision_api_key
    model = cfg.vision_model
    if not base or not key:
        print("[FAIL] VISION_BASE_URL / VISION_API_KEY missing (check .env)")
        return 1
    print(f"[cfg ] base={base}  model={model}  key={_redact(key)}")
    headers = {"Authorization": f"Bearer {key}"}

    # 1) models 列表
    try:
        t0 = time.monotonic()
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{base}/models", headers=headers)
        dt = time.monotonic() - t0
        print(f"[GET ] /models -> HTTP {r.status_code}  {dt*1000:.0f} ms")
        if r.status_code != 200:
            print("       body:", _short(r.text))
            return 2
        ids = {m.get("id") for m in r.json().get("data", []) if isinstance(m, dict)}
        print(f"       advertised models={len(ids)}  target model advertised={model in ids}")
    except httpx.TimeoutException:
        print("[FAIL] /models 15s timeout -> gateway unreachable")
        return 3
    except httpx.HTTPError as e:
        print(f"[FAIL] /models 请求异常: {type(e).__name__}: {e}")
        return 3

    # 2) 最小 chat 实测
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping - connectivity check, reply OK only"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    ok, worst = 0, 0.0
    for i in range(1, args.attempts + 1):
        try:
            t0 = time.monotonic()
            with httpx.Client(timeout=args.chat_timeout) as client:
                r = client.post(f"{base}/chat/completions", headers=headers, json=payload)
            dt = time.monotonic() - t0
            worst = max(worst, dt)
            if r.status_code == 200:
                data = r.json()
                finish = (data.get("choices") or [{}])[0].get("finish_reason")
                usage = (data.get("usage") or {}).get("total_tokens")
                ok += 1
                print(f"[POST] attempt {i} -> HTTP 200  {dt:.1f} s  finish={finish}  tokens={usage}")
            else:
                print(f"[POST] attempt {i} -> HTTP {r.status_code}  {dt:.1f} s  body: {_short(r.text)}")
                return 2
        except httpx.TimeoutException:
            print(f"[POST] attempt {i} -> {args.chat_timeout:g}s timeout (no response)")
            return 3
        except httpx.HTTPError as e:
            print(f"[POST] attempt {i} -> 异常 {type(e).__name__}: {e}")
            return 3

    print(f"\n[VERDICT] healthy ({ok}/{args.attempts} success, slowest {worst:.1f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


