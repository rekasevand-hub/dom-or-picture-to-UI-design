# -*- coding: utf-8 -*-
"""`--rerun` 的两道闸：脏工作区拒绝，bridge 刚被写过则警告。

为什么要有这道闸：2026-11-13 15:38 有一次复跑，产物里 `gitDirty = true`——另一个会话
在同一棵树上未提交的「墨迹归属」改动把参考口径换掉了，content-review 的 owner 从 14
掉到 12，而导出 sha 逐字节相同。数字看起来像回归，其实是换了尺子。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_benchmark_families as cbf


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cbf, "JOURNAL", tmp_path / "no-journal.jsonl")


def test_dirty_worktree_refuses_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbf, "_dirty_entries", lambda: [" M src/x.py"])
    assert cbf._preflight(True, False) == 2


def test_dirty_worktree_allowed_with_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbf, "_dirty_entries", lambda: [" M src/x.py"])
    assert cbf._preflight(True, True) is None


def test_clean_worktree_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbf, "_dirty_entries", lambda: [])
    assert cbf._preflight(True, False) is None


def test_non_rerun_ignores_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbf, "_dirty_entries", lambda: [" M src/x.py"])
    assert cbf._preflight(False, False) is None


def test_fresh_journal_warns_but_does_not_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal = tmp_path / "bridge-journal.jsonl"
    journal.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cbf, "JOURNAL", journal)
    monkeypatch.setattr(cbf, "_dirty_entries", lambda: [])
    assert cbf._preflight(True, False) is None
    assert "bridge journal" in capsys.readouterr().out
