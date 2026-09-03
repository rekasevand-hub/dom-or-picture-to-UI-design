"""
测试 OmniParser 本地服务是否可用。

用法：
    python scripts/test_omniparser_service.py
    python scripts/test_omniparser_service.py --image uploads/test01.png
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

try:
    import requests
except ImportError as exc:
    print("错误：缺少 requests 依赖，请先安装：pip install requests")
    raise SystemExit(1) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Test OmniParser local service")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--image", default=None, help="要测试的图片路径")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    # 1. 健康检查
    print(f"测试健康检查: {base_url}/health")
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        print(f"  状态: {data.get('status')}")
        print(f"  模型已加载: {data.get('model_loaded')}")
    except requests.ConnectionError:
        print(f"  ❌ 无法连接到 {base_url}，请确认服务已启动")
        return 1
    except Exception as exc:
        print(f"  ❌ 健康检查失败: {exc}")
        return 1

    # 2. 可选：发送真实图片测试
    if args.image:
        img_path = Path(args.image)
        if not img_path.exists():
            print(f"  ❌ 图片不存在: {img_path}")
            return 1

        print(f"测试图片解析: {img_path}")
        image_b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        try:
            resp = requests.post(
                f"{base_url}/parse",
                json={"base64_image": image_b64},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            parsed = data.get("parsed_content_list", [])
            latency = data.get("latency", 0)
            print(f"  ✅ 解析成功，检出 {len(parsed)} 个元素，耗时 {latency:.3f}s")
            for i, item in enumerate(parsed[:5]):
                print(f"    [{i}] {item.get('type')}: {item.get('content', '')[:40]}")
            if len(parsed) > 5:
                print(f"    ... 还有 {len(parsed) - 5} 个元素")
        except Exception as exc:
            print(f"  ❌ 图片解析失败: {exc}")
            return 1

    print("\n全部测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
