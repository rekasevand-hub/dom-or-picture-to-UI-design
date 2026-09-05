# -*- coding: utf-8 -*-
"""main CLI 参数契约测试：登录态相关参数与校验。"""
from __future__ import annotations

import pytest

from src.main import _build_parser, main


def test_parser_accepts_storage_state_flags():
    args = _build_parser().parse_args(
        ["--url", "https://example.com", "--route", "dom",
         "--tool", "svg", "--storage-state", "state.json"])
    assert args.storage_state == "state.json"
    assert args.login_state is None


def test_login_state_without_url_is_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--login-state", "out.json", "--route", "dom"])
    assert exc.value.code == 2
    assert "--login-state" in capsys.readouterr().err


def test_login_state_conflicts_with_storage_state(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--url", "https://example.com", "--login-state", "out.json",
              "--storage-state", "in.json"])
    assert exc.value.code == 2
    assert "分两步" in capsys.readouterr().err
