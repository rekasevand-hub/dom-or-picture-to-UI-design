#!/usr/bin/env python3
"""
调用本地 OmniParser HTTP 服务解析单张图片。

用法：
    python scripts/test_parse.py --image uploads/test01.png --url http://127.0.0.1:8000/parse
"""

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_image(image_path: str, url: str, timeout: int = 120) -> dict:
    payload = json.dumps({"base64_image": encode_image(image_path)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_som_image(result: dict, output_path: str) -> None:
    """把返回的标注图 base64 保存为 PNG 文件。"""
    img_bytes = base64.b64decode(result["som_image_base64"])
    with open(output_path, "wb") as f:
        f.write(img_bytes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test OmniParser /parse endpoint")
    parser.add_argument(
        "--image",
        default="uploads/test01.png",
        help="Path to the image to parse (default: uploads/test01.png)",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/parse",
        help="OmniParser /parse endpoint URL",
    )
    parser.add_argument(
        "--save-som",
        default="output/som_result.png",
        help="Save annotated SOM image to this path",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Sending {image_path} to {args.url} ...")
    result = parse_image(str(image_path), args.url, args.timeout)

    print(f"Latency: {result['latency']:.3f}s")
    print(f"Elements: {len(result['parsed_content_list'])}")
    print(json.dumps(result["parsed_content_list"], indent=2, ensure_ascii=False))

    if args.save_som:
        output_path = Path(args.save_som)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_som_image(result, str(output_path))
        print(f"SOM image saved to: {output_path}")


if __name__ == "__main__":
    main()
