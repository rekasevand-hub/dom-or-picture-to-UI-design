"""One public name for the screenshot route: ``omni-cv``.

`physical` was the stage-three spelling and stays as a hidden alias so frozen
regression commands keep running — but it must announce itself and never show up
in ``--help``.  ``--omni-cv`` is the shortcut, and conflicting spellings are an
error rather than a silent precedence rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _path in (_ROOT, _ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import image_figma_mvp  # noqa: E402
from src.app.services.structure import router  # noqa: E402
from src import main as cli  # noqa: E402


def test_the_canonical_name_is_the_only_public_route() -> None:
    assert router.ROUTE_OMNI_CV == "omni-cv"
    assert router.PUBLIC_ROUTES == ("auto", "dom", "omni-cv")


def test_the_alias_maps_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert router.normalize_route("physical") == "omni-cv"
    message = capsys.readouterr().err
    assert "deprecated" in message
    assert "--route omni-cv" in message


def test_a_canonical_name_is_passed_through_silently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert router.normalize_route("omni-cv") == "omni-cv"
    assert capsys.readouterr().err == ""


def test_the_alias_stays_out_of_help() -> None:
    text = cli._build_parser().format_help()
    assert "omni-cv" in text
    # 历史名仍可解析，但不该出现在任何公开的帮助文本里（连弃用说明都不占位）。
    assert "{auto,dom,omni-cv}" in text
    assert "physical" not in text
    assert "grounding" not in text


def test_the_main_cli_accepts_both_spellings() -> None:
    assert cli.parse_args(["--image", "a.png", "--route", "omni-cv"]).route == "omni-cv"
    assert cli.parse_args(["--image", "a.png", "--omni-cv"]).omni_cv is True
    # 别名在解析阶段就被归一，下游看不到 `physical`。
    assert cli.parse_args(["--image", "a.png", "--route", "physical"]).route == "omni-cv"


def test_the_shortcut_conflicts_loudly_with_another_route() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--image", "a.png", "--omni-cv", "--route", "dom"])
    assert excinfo.value.code == 2


def test_the_image_pipeline_accepts_the_same_two_spellings() -> None:
    parser = image_figma_mvp._build_parser()
    base = ["--image", "a.png", "--truth", "a.json", "--out", "o"]
    assert parser.parse_args(base + ["--route", "omni-cv"]).route == "omni-cv"
    assert parser.parse_args(base + ["--route", "physical"]).route == "omni-cv"
    assert parser.parse_args(base + ["--omni-cv"]).omni_cv is True
    # 不显式给路线时保持历史默认：auto（截图走 cv，带兜底）。
    assert parser.parse_args(base).route is None
