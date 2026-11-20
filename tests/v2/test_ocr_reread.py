"""The recognition repair behind the missing table cells.

RapidOCR's detector finds a 12px line of dense punctuation; its recogniser
sometimes returns ``SSOnSaeessa...`` at 0.33 for that same crop because the
batch's width normalisation is shared.  Read alone, the crop comes back at 0.97.
FluxWeaver's ``执行结果`` column lost three of five rows to exactly that, so these
tests pin the repair: one crop at a time, only when the score clears the bar, and
never on a rotated line.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure import image_contract  # noqa: E402


class _FakeEngine:
    """An engine that answers the whole page at once and crops one by one."""

    def __init__(self, page: list, answers: list[tuple[str, float]]) -> None:
        self.page = page
        self.answers = list(answers)
        self.text_score = 0.5
        self.rec_calls = 0
        self.score_seen: list[float] = []

    def __call__(self, _image):
        self.score_seen.append(self.text_score)
        return list(self.page), [0.0]

    def text_rec(self, crops):
        assert len(crops) == 1
        answer = self.answers[self.rec_calls]
        self.rec_calls += 1
        # 真实接口返回 ``(结果列表, 耗时)``：解包错了会被重读函数的 except 吞掉。
        return [answer], 0.0


def _polygon(x: int, y: int, w: int, h: int) -> list[list[int]]:
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _page_image(tmp_path: Path, width: int = 400, height: int = 120) -> np.ndarray:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    image[20:40, 20:320] = 0
    return image


def test_a_low_score_box_is_reread_on_its_own(tmp_path: Path) -> None:
    page = [
        [_polygon(20, 20, 300, 20), 'SSOnSaeessa.SOnS.oe)', 0.33],
        [_polygon(20, 60, 120, 20), "执行结果", 0.99],
    ]
    engine = _FakeEngine(page, [('{"error":"SUCCESS","message":"SUCCESS"}', 0.97)])
    image = _page_image(tmp_path)

    recovered = image_contract._rapidocr_reread(engine, image, page)

    assert [item["text"] for item in recovered] == ['{"error":"SUCCESS","message":"SUCCESS"}']
    assert recovered[0]["bbox"] == [20, 20, 300, 20]
    assert recovered[0]["confidence"] == pytest.approx(0.97)
    # 一次一个地重读：批量读正是故障来源。
    assert engine.rec_calls == 1


def test_a_reread_that_stays_low_is_dropped(tmp_path: Path) -> None:
    page = [[_polygon(20, 20, 300, 20), "Soe)", 0.31]]
    engine = _FakeEngine(page, [("Soe)", 0.4)])
    image = _page_image(tmp_path)

    assert image_contract._rapidocr_reread(engine, image, page) == []


def test_a_tilted_line_is_not_reread(tmp_path: Path) -> None:
    page = [[[[20, 20], [320, 28], [320, 48], [20, 40]], "tilted", 0.2]]
    engine = _FakeEngine(page, [("tilted", 0.9)])
    image = _page_image(tmp_path)

    assert image_contract._rapidocr_reread(engine, image, page) == []
    assert engine.rec_calls == 0


def test_the_page_pass_keeps_its_confidence_floor(monkeypatch, tmp_path: Path) -> None:
    """Reading with a 0 floor must not leak into the rest of the run."""
    page = [
        [_polygon(20, 20, 300, 20), 'SSOnSaeessa.SOnS.oe)', 0.33],
        [_polygon(20, 60, 120, 20), "执行结果", 0.99],
    ]
    engine = _FakeEngine(page, [('{"error":"SUCCESS"}', 0.96)])
    image = _page_image(tmp_path)
    source = tmp_path / "page.png"
    import cv2

    cv2.imwrite(str(source), image)
    monkeypatch.setattr(image_contract, "_RAPIDOCR_ENGINE", engine)

    observations = image_contract._rapidocr(source)

    assert engine.score_seen == [0.0]
    assert engine.text_score == pytest.approx(0.5)
    texts = [item["text"] for item in observations]
    # 低分那句以重读结果出现，且只出现一次。
    assert texts.count('{"error":"SUCCESS"}') == 1
    assert "SSOnSaeessa.SOnS.oe)" not in texts
    assert "执行结果" in texts
