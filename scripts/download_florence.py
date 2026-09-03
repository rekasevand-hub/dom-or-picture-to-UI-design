"""从 hf-mirror.com 下载 Florence-2-base-ft 缺失的远程代码文件。"""
from pathlib import Path
import urllib.request
import urllib.error

BASE_URL = "https://hf-mirror.com/microsoft/Florence-2-base-ft/resolve/main"
TARGET_DIR = Path("OmniParser/OmniParser-master/weights/icon_caption_florence")
TARGET_DIR.mkdir(parents=True, exist_ok=True)

FILES = [
    "preprocessor_config.json",
    "processing_florence2.py",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
    "modeling_florence2.py",
    "configuration_florence2.py",
]

opener = urllib.request.build_opener()
opener.addheaders = [("User-Agent", "Mozilla/5.0")]
urllib.request.install_opener(opener)

for fname in FILES:
    url = f"{BASE_URL}/{fname}"
    out = TARGET_DIR / fname
    if out.exists():
        print(f"已存在: {out}")
        continue
    try:
        print(f"下载: {url} -> {out}")
        urllib.request.urlretrieve(url, out)
        print(f"  完成 ({out.stat().st_size} bytes)")
    except urllib.error.HTTPError as e:
        print(f"  失败: {e.code} {e.reason}")
    except Exception as e:
        print(f"  失败: {e}")

print("\n最终文件列表:")
for f in sorted(TARGET_DIR.iterdir()):
    print(f"  {f.name} ({f.stat().st_size} bytes)")
