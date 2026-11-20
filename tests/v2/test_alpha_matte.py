"""Whether a crop is an isolated object, and whether the cut is worth keeping.

Two questions, and the tests separate them on purpose: the admission gate is
about *geometry* (is the border flat, is the thing the right size, is it a
repair rather than a picture) and the matte is about *pixels* (did the object
survive the cut).  A defect in either one shows up as a different assertion,
which is why they are not tested together through the compiler.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity import alpha_matte


def _page(size=(200, 200), backdrop=(250, 244, 237)) -> np.ndarray:
    page = np.zeros((size[0], size[1], 3), dtype=np.uint8)
    page[:] = backdrop
    return page


def _with_object(page, box=(60, 60, 60, 60), colour=(198, 42, 38)) -> np.ndarray:
    x, y, w, h = box
    page = page.copy()
    page[y : y + h, x : x + w] = colour
    return page


def test_a_box_on_a_flat_backdrop_is_admitted_and_survives_the_cut() -> None:
    page = _with_object(_page())
    ok, evidence = alpha_matte.admit(page, (40, 40, 100, 100), canvas=(200, 200))
    assert ok, evidence
    assert evidence["reason"] == "flat-border"

    crop = page[40:140, 40:140]
    rgba, how = alpha_matte.matte(crop)
    assert rgba is not None, how
    alpha = rgba[..., 3]
    # 四角是底，必须切掉；物体中心必须留住。
    assert alpha[2, 2] == 0 and alpha[-3, -3] == 0
    assert alpha[50, 50] == 255
    # 保留面积要接近物体的真实占比（60×60 / 100×100 = 0.36），而不是接近整块。
    assert 0.25 < float((alpha > 128).mean()) < 0.55


def test_a_photograph_is_refused_before_anything_is_cut() -> None:
    """Structure right up to the border: there is no rectangle to remove."""
    rng = np.random.default_rng(7)
    page = _page()
    page[50:130, 50:130] = rng.integers(0, 255, size=(80, 80, 3), dtype=np.uint8)
    ok, evidence = alpha_matte.admit(page, (50, 50, 80, 80), canvas=(200, 200))
    assert not ok
    assert evidence["reason"] == "busy-border"
    assert evidence["grad"] > alpha_matte.ALPHA_MATTE_RING_GRAD


def test_the_size_band_keeps_icons_and_backgrounds_out() -> None:
    page = _with_object(_page())
    small, _ = alpha_matte.admit(page, (60, 60, 20, 20), canvas=(400, 400))
    large, evidence = alpha_matte.admit(page, (0, 0, 200, 200), canvas=(200, 200))
    assert not small
    assert not large
    assert evidence["reason"] == "size-band"


def test_a_repair_role_is_never_cut_out() -> None:
    """A mark is a strip of re-cut text; cutting it out erases what it carries."""
    page = _with_object(_page())
    ok, evidence = alpha_matte.admit(page, (40, 40, 100, 100), canvas=(200, 200), role="mark")
    assert not ok
    assert evidence["reason"] == "repair-role"


def test_a_flat_crop_with_no_object_returns_nothing() -> None:
    page = _page()
    ok, _evidence = alpha_matte.admit(page, (40, 40, 100, 100), canvas=(200, 200))
    assert ok  # 边框确实平坦——准入通过
    rgba, how = alpha_matte.matte(page[40:140, 40:140])
    assert rgba is None
    assert how["reason"] == "no-object"


def test_the_switch_short_circuits_the_whole_operation(tmp_path, monkeypatch) -> None:
    """Off means off: no decode, no cut, no payload — the caller keeps its rectangle."""
    from PIL import Image

    page = _with_object(_page())
    path = tmp_path / "page.png"
    Image.fromarray(page).save(path)

    monkeypatch.setattr(alpha_matte, "ALPHA_MATTE_ENABLED", False)
    payload, evidence = alpha_matte.matte_png_b64(str(path), 40, 40, 100, 100, 200, 200)
    assert payload is None
    assert evidence["reason"] == "disabled"

    monkeypatch.setattr(alpha_matte, "ALPHA_MATTE_ENABLED", True)
    payload, evidence = alpha_matte.matte_png_b64(str(path), 40, 40, 100, 100, 200, 200)
    assert payload and evidence["reason"] == "matted"
    # 编码出来必须是带 alpha 的 PNG，否则 SVG 会把透明边画成白框。
    import base64
    import io

    with Image.open(io.BytesIO(base64.b64decode(payload))) as encoded:
        assert encoded.mode == "RGBA"


def test_the_gradient_corner_is_flat_locally_but_not_globally() -> None:
    """A soft gradient card is the case this was written for, and it passes.

    The local gradient is near zero everywhere, so the gate admits it — but the
    four corners differ by a lot, which is exactly why an opaque rectangle of it
    becomes visible the moment the surface behind it is rebuilt as a solid.
    """
    page = _page()
    ramp = np.linspace(0, 1, 200)[:, None, None]
    page = (page.astype(np.float32) * (1 - 0.06 * ramp)).astype(np.uint8)
    page = _with_object(page)
    stats = alpha_matte.ring_flatness(page, (40, 40, 100, 100))
    assert stats["grad"] <= alpha_matte.ALPHA_MATTE_RING_GRAD
    assert stats["spread"] > alpha_matte.ALPHA_MATTE_RING_GRAD
