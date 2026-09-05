import json
from pathlib import Path
import pytest
from PIL import Image
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.graph import assign_ids, assign_parent_depth

SAMPLES = [p for p in (Path(__file__).resolve().parents[1] / "samples").glob("*")
           if (p / "00_dom.json").exists()]

@pytest.mark.parametrize("sample", sorted(SAMPLES, key=lambda p: p.name),
                         ids=lambda p: p.name)
def test_sample_dom_pagegraph(sample):
    dom = json.loads((sample / "00_dom.json").read_text(encoding="utf-8"))
    im = Image.open(sample / "00_screenshot.png")
    ctx = ProviderContext(image_path=str(sample / "00_screenshot.png"),
                          image_w=im.width, image_h=im.height, route="dom",
                          output_dir=str(sample), dom_path=str(sample / "00_dom.json"))
    g = DomProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    exp = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    assert len(g["containers"]) >= exp["min_containers"]
    assert exp["min_elements"] <= len(g["elements"]) <= exp["max_elements"]
    for e in g["elements"] + g["containers"]:
        x, y, w, h = e["bbox"]
        assert x >= 0 and y >= 0 and x + w <= im.width + 1 and y + h <= im.height + 1
