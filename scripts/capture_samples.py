"""抓本地 HTML 页面成回归语料：00_screenshot.png + 00_dom.json。"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.structure.capture import DOM_JS

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(Path(args.html).resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "00_screenshot.png"), full_page=True)
        nodes = page.evaluate(DOM_JS)
        (out / "00_dom.json").write_text(
            json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        browser.close()
    from PIL import Image
    from src.app.services.structure.providers.dom import DomProvider
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.graph import assign_ids, assign_parent_depth
    im = Image.open(out / "00_screenshot.png")
    ctx = ProviderContext(image_path=str(out / "00_screenshot.png"),
                          image_w=im.width, image_h=im.height, route="dom",
                          output_dir=str(out), dom_path=str(out / "00_dom.json"))
    g = DomProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    nc, ne = len(g["containers"]), len(g["elements"])
    (out / "expected.json").write_text(json.dumps(
        {"min_containers": max(1, int(nc * 0.7)),
         "min_elements": max(1, int(ne * 0.7)),
         "max_elements": int(ne * 1.3) + 1}, indent=1), encoding="utf-8")
    print("captured", out, "counts", nc, ne)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
