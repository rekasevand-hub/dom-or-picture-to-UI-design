"""失败分层：分类只记账，层映射在 policy，门禁不变。

用例直接照抄 2026-11-13 的四条 owner 归因——那四条是人工查过的，分类器必须复现它们，
否则就是又造了一套和实测不一致的判据。
"""

from __future__ import annotations

import pytest

from src.app.services.evidence.image_figma_acceptance import (
    IMAGE_MVP_POLICY_V21,
    _with_failure_layers,
)
from src.app.services.evidence.native_text_quality import _failure_class

PASS = {"position": True, "size": True, "coverage": True, "edgeF1": True}


def _class(checks, sides, dx=0, dy=0, wd=0, hd=0, wt=4, ht=3, pos=2) -> str:
    return _failure_class(checks, sides, dx, dy, wd, hd, wt, ht, pos)


def test_all_checks_pass() -> None:
    assert _class(PASS, []) == "pass"


def test_glyph_only_failure_is_typeface() -> None:
    """`检查状态`：墨迹框逐像素重合，只有 coverage 差 → 字形。"""
    checks = {**PASS, "coverage": False}
    assert _class(checks, [], wd=0, hd=0) == "typeface-glyph"


def test_edge_f1_only_failure_is_typeface() -> None:
    """`内容正在审核中`：面积对、边缘对不上 → 字形。"""
    checks = {**PASS, "edgeF1": False}
    assert _class(checks, []) == "typeface-glyph"


def test_width_only_failure_is_advance_axis() -> None:
    """`REQ-OIBFZVUES`：宽超 6/容差 5、高在容差内、位移干净、未贴边 → 宽度轴。"""
    checks = {**PASS, "size": False}
    assert _class(checks, [], wd=6, hd=2) == "typeface-advance"


def test_real_offset_dominates_the_advance_axis() -> None:
    """`系统运行正常`：宽也超、高也在容差内，但 dy 位移是真的 → 机械。

    这条是分类顺序的关键反例：只看「高宽不自洽」会把它误判成字族，
    等于把 13px 的间距缺陷放进「不挡发布」那一层。
    """
    checks = {**PASS, "position": False, "size": False}
    assert _class(checks, [], dx=0, dy=-6, wd=-5, hd=2) == "mechanical"


def test_offset_on_a_clipped_axis_is_instrument_capped() -> None:
    """参考墨迹贴着窗口左边时，dx 读数被封顶 → 量具层，不是机械缺陷。"""
    checks = {**PASS, "position": False}
    assert _class(checks, ["left"], dx=9, dy=0) == "instrument-capped"


def test_width_failure_on_a_clipped_axis_is_instrument_capped() -> None:
    checks = {**PASS, "size": False}
    assert _class(checks, ["right"], wd=-12, hd=0) == "instrument-capped"


def test_both_axes_out_is_mechanical() -> None:
    checks = {**PASS, "size": False}
    assert _class(checks, [], wd=9, hd=8) == "mechanical"


def test_policy_declares_three_layers_in_report_mode() -> None:
    declaration = IMAGE_MVP_POLICY_V21["native_text_failure_layers"]
    assert declaration["enforcement"] == "report"
    layers = declaration["layers"]
    assert set(layers) == {"mechanical", "typeface", "instrument"}
    assert layers["mechanical"]["blocks"] is True
    assert layers["typeface"]["blocks"] is False
    assert layers["instrument"]["blocks"] is False
    assert layers["mechanical"]["classes"] == ["mechanical"]


def _owner(class_name: str, status: str = "fail", scope: str = "critical-gate") -> dict:
    return {"failureClass": class_name, "status": status, "ownerScope": scope}


def test_layer_counts_only_scale_to_critical_gate() -> None:
    quality = {
        "owners": [
            _owner("mechanical"),
            _owner("typeface-glyph"),
            _owner("typeface-glyph"),
            _owner("instrument-capped"),
            _owner("mechanical", scope="diagnostic-only"),
            _owner("pass", status="pass"),
        ]
    }
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    layers = report["failureLayers"]
    assert layers["scope"] == "critical-gate"
    assert layers["ownerCount"] == 5
    assert layers["failureCounts"] == {
        "mechanical": 1,
        "typeface": 2,
        "instrument": 1,
    }
    assert layers["unclassifiedFailures"] == 0


def test_hypothetical_green_needs_zero_blocking_failures() -> None:
    quality = {
        "owners": [
            _owner("typeface-glyph"),
            _owner("instrument-capped"),
            _owner("pass", status="pass"),
        ]
    }
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    assert report["failureLayers"]["hypothetical"]["blockingFailures"] == 0
    assert report["failureLayers"]["hypothetical"]["wouldPass"] is True


def test_hypothetical_red_keeps_one_mechanical_failure_loud() -> None:
    quality = {"owners": [_owner("mechanical"), _owner("typeface-glyph")]}
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    assert report["failureLayers"]["hypothetical"]["blockingFailures"] == 1
    assert report["failureLayers"]["hypothetical"]["wouldPass"] is False


def test_native_text_failure_without_geometry_failure_stays_mechanical() -> None:
    """四维全过但 nativeText 不成立 = 我们没发原生文字，属机械层。"""
    quality = {"owners": [_owner("pass")]}
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    assert report["failureLayers"]["failureCounts"]["mechanical"] == 1


def test_unknown_class_is_reported_not_swallowed() -> None:
    quality = {"owners": [_owner("something-new")]}
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    assert report["failureLayers"]["unclassifiedFailures"] == 1
    assert report["failureLayers"]["hypothetical"]["wouldPass"] is False


def test_layer_report_does_not_touch_status_or_checks() -> None:
    quality = {
        "status": "measured-gate",
        "owners": [
            {"failureClass": "mechanical", "status": "fail", "checks": {"size": False}}
        ],
    }
    report = _with_failure_layers(quality, IMAGE_MVP_POLICY_V21)
    assert report["status"] == quality["status"]
    assert report["owners"] == quality["owners"]
    assert "failureLayers" in report


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
