from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from src.app.services.structure.backends.grounding_reliability import (
    GroundingRequestError,
)
from src.app.services.structure.backends.grounding_vlm import (
    GroundingVLM,
    parse_vlm_json,
)
from src.app.services.structure.image_enrichment.tiling import plan_image_tiles
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.providers.grounding import GroundingProvider


class _Report:
    def __init__(self, tile_id: str) -> None:
        self.tile_id = tile_id

    def to_dict(self) -> dict:
        return {"tile_id": self.tile_id, "attempt_count": 1}


class _TiledBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_report = None

    def ground(self, _image_path, _width, _height):
        self.calls.append("single")
        self.last_report = _Report("tile-0000")
        return {
            "containers": [{"bbox": [0, 0, 80, 20], "role": "banner"}],
            "elements": [{"bbox": [8, 4, 30, 10], "type": "text", "text": "Home"}],
        }

    def ground_with_prompt(
        self,
        _image_path,
        _width,
        _height,
        prompt,
        *,
        strategy_id="grounding-tile",
        metadata=None,
    ):
        tile_id = (metadata or {}).get("tile", {}).get("id", "unknown")
        self.calls.append(tile_id)
        self.last_report = _Report(tile_id)
        return {
            "containers": [],
            "elements": [
                {
                    "bbox": [10, 10, 30, 10],
                    "type": "text",
                    "text": tile_id,
                }
            ],
        }


def _config(max_height: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        vision_tile_max_height=max_height,
        vision_tile_overlap=20,
    )


def _context(path: Path, width: int, height: int) -> ProviderContext:
    return ProviderContext(
        image_path=str(path),
        image_w=width,
        image_h=height,
        route="grounding",
        output_dir=str(path.parent),
    )


def test_ordinary_image_under_limit_sends_one_request_and_keeps_graph_shape():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        Image.new("RGB", (120, 100), "white").save(path)
        backend = _TiledBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config()).run(_context(path, 120, 100))

    assert backend.calls == ["single"]
    assert graph["route"] == "grounding"
    assert graph["containers"][0]["role"] == "banner"
    assert graph["elements"][0]["text"] == "Home"
    assert graph["provenance"]["tiling"]["tiles"] == [
        {
            "id": "tile-0000",
            "source_rect": [0, 0, 120, 100],
            "page_origin": [0, 0],
            "reason": "single-tile",
        }
    ]


def test_long_image_uses_each_planned_tile_and_translates_to_page_coordinates():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        Image.new("RGB", (200, 500), "white").save(path)
        backend = _TiledBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config()).run(_context(path, 200, 500))

    planned = plan_image_tiles(200, 500, max_tile_height=200, overlap=20)
    assert backend.calls == [tile["id"] for tile in planned]
    assert [item["bbox"][1] for item in graph["elements"]] == [10, 190, 370]
    assert graph["provenance"]["tiling"]["tiles"] == [
        {
            "id": tile["id"],
            "source_rect": tile["source_rect"],
            "page_origin": tile["page_origin"],
            "reason": tile["reason"],
        }
        for tile in planned
    ]


class _RepairBackend(_TiledBackend):
    def __init__(self) -> None:
        super().__init__()
        self.subject_calls = 0

    def ground_with_prompt(
        self,
        image_path,
        width,
        height,
        prompt,
        *,
        strategy_id="grounding-tile",
        metadata=None,
    ):
        tile_id = (metadata or {}).get("tile", {}).get("id", "unknown")
        if tile_id == "tile-0000":
            self.subject_calls += 1
            if self.subject_calls == 1:
                self.calls.append("tile-0000:invalid")
                raise GroundingRequestError("response-invalid", "bad json")
            assert "Repair" in prompt
            self.calls.append("tile-0000:repair")
            self.last_report = _Report(tile_id)
            return {
                "containers": [],
                "elements": [
                    {"bbox": [5, 5, 20, 8], "type": "text", "text": "repaired"}
                ],
            }
        return super().ground_with_prompt(
            image_path,
            width,
            height,
            prompt,
            strategy_id=strategy_id,
            metadata=metadata,
        )


def test_invalid_json_gets_one_repair_attempt():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        Image.new("RGB", (200, 300), "white").save(path)
        backend = _RepairBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config()).run(_context(path, 200, 300))

    assert backend.calls[:2] == ["tile-0000:invalid", "tile-0000:repair"]
    assert any(item["text"] == "repaired" for item in graph["elements"])


class _SmallerRetryBackend(_TiledBackend):
    def ground_with_prompt(
        self,
        image_path,
        width,
        height,
        prompt,
        *,
        strategy_id="grounding-tile",
        metadata=None,
    ):
        tile = (metadata or {}).get("tile", {})
        tile_id = tile.get("id", "unknown")
        if tile_id == "tile-0000":
            self.calls.append(f"{tile_id}:failure")
            raise GroundingRequestError("response-invalid", "bad json")
        return super().ground_with_prompt(
            image_path,
            width,
            height,
            prompt,
            strategy_id=strategy_id,
            metadata=metadata,
        )


def test_failed_repair_uses_one_smaller_tile_retry():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        image = Image.new("RGB", (200, 300), "white")
        for y in range(0, 300, 10):
            image.paste((10, 20, 30), (0, y, 100, min(300, y + 5)))
        image.save(path)
        backend = _SmallerRetryBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config()).run(_context(path, 200, 300))

    assert [call for call in backend.calls if call.startswith("tile-0000")] == [
        "tile-0000:failure",
        "tile-0000:failure",
    ]
    assert any(
        item["status"] == "recovered-by-smaller-tiles"
        for item in graph["provenance"]["tiling"]["tiles"]
    )


class _EmptyBackend(_TiledBackend):
    def ground(self, image_path, width, height):
        self.calls.append("single")
        self.last_report = _Report("tile-0000")
        return {"containers": [], "elements": []}


def test_empty_nonbackground_output_fails_closed():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        image = Image.new("RGB", (120, 100), "white")
        image.paste((20, 40, 80), (10, 10, 90, 80))
        image.save(path)
        backend = _EmptyBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            with pytest.raises(GroundingRequestError) as caught:
                GroundingProvider(_config()).run(_context(path, 120, 100))

    assert caught.value.category == "empty-structure"


def test_empty_majority_background_tile_is_accepted():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "image.png"
        Image.new("RGB", (120, 100), "white").save(path)
        backend = _EmptyBackend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(_config()).run(_context(path, 120, 100))

    assert backend.calls == ["single"]
    assert graph["containers"] == []
    assert graph["elements"] == []


def test_grounding_vlm_tile_prompt_uses_supplied_prompt_and_parses_json():
    captured: dict[str, str] = {}

    class _Runtime:
        def run(self, *, image_bytes, prompt, invoke):
            assert image_bytes == b"tile-bytes"
            captured["prompt"] = prompt
            value, _usage = invoke("https://vision.test/v1")
            return SimpleNamespace(
                value=value,
                report=_Report("tile-0000"),
            )

    class _Completions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"containers":[],"elements":'
                                '[{"bbox":[0.1,0.2,0.5,0.3],'
                                '"type":"text","text":"Tile"}]}'
                            )
                        )
                    )
                ],
                usage=None,
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions())
    )
    cfg = SimpleNamespace(
        vision_model="vision-test",
        vision_timeout=5,
        vision_max_image_bytes=1024,
        vision_max_response_bytes=1024,
    )
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "tile.png"
        path.write_bytes(b"tile-bytes")
        backend = GroundingVLM(
            cfg,
            runtime=_Runtime(),
            client_factory=lambda _endpoint, _timeout: client,
        )
        parsed = backend.ground_with_prompt(
            str(path),
            200,
            100,
            "Custom tile prompt",
            strategy_id="grounding-tile",
            metadata={"tile": {"id": "tile-0000"}},
        )

    assert captured["prompt"] == "Custom tile prompt"
    assert parsed["elements"][0]["bbox"] == [20, 20, 80, 10]
    assert parsed["elements"][0]["text"] == "Tile"
    assert backend.last_request_metadata["tile"]["id"] == "tile-0000"


def test_grounding_vlm_tile_contract_parses_source_pixel_xywh():
    class _Runtime:
        def run(self, *, image_bytes, prompt, invoke):
            assert image_bytes == b"tile-bytes"
            value, _usage = invoke("https://vision.test/v1")
            return SimpleNamespace(
                value=value,
                report=_Report("tile-0000"),
            )

    class _Completions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"containers":[{"bbox":{"x":0,"y":0,'
                                '"width":200,"height":30},"role":"banner"}],'
                                '"elements":[{"bbox":{"x":20,"y":40,'
                                '"width":80,"height":24},"type":"text",'
                                '"text":"Heading"}],"assets":[],"backgrounds":[]}'
                            )
                        )
                    )
                ],
                usage=None,
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions())
    )
    cfg = SimpleNamespace(
        vision_model="vision-test",
        vision_timeout=5,
        vision_max_image_bytes=1024,
        vision_max_response_bytes=4096,
    )
    with tempfile.TemporaryDirectory() as raw_dir:
        path = Path(raw_dir) / "tile.png"
        path.write_bytes(b"tile-bytes")
        backend = GroundingVLM(
            cfg,
            runtime=_Runtime(),
            client_factory=lambda _endpoint, _timeout: client,
        )
        parsed = backend.ground_with_prompt(
            str(path),
            200,
            100,
            "Source-pixel tile prompt",
            strategy_id="grounding-enrichment",
            metadata={
                "tile": {"id": "tile-0000"},
                "bbox_format": "source-px-xywh",
            },
        )

    assert parsed["containers"][0]["bbox"] == [0, 0, 200, 30]
    assert parsed["elements"][0]["bbox"] == [20, 40, 80, 24]


def test_grounding_vlm_calibrates_provider_thousand_pixel_x_axis():
    raw = (
        '{"containers":[{"bbox":{"x":0,"y":0,"width":144,"height":826},'
        '"role":"sidebar"}],"elements":[{"bbox":{"x":220,"y":172,'
        '"width":340,"height":32},"type":"input","text":"auto_backup",'
        '"controlValue":"auto_backup","controlState":"enabled"}],'
        '"assets":[],"backgrounds":[]}'
    )

    parsed = parse_vlm_json(
        raw,
        1920,
        826,
        bbox_format="source-px-xywh",
    )

    assert parsed["containers"][0]["bbox"] == [0, 0, 276, 826]
    assert parsed["elements"][0]["bbox"] == [422, 172, 653, 32]
    assert parsed["elements"][0]["controlValue"] == "auto_backup"
    assert parsed["elements"][0]["controlState"] == "enabled"
