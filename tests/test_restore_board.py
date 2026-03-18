"""Tests for scripts/restore_board.py — board health checking."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.restore_board as restore_board_module
from scripts.restore_board import check_board_health


# ---------------------------------------------------------------------------
# check_board_health — all files present
# ---------------------------------------------------------------------------

def test_check_board_health_all_present(temp_board_dir):
    with patch.object(restore_board_module, "BOARD_DIR", temp_board_dir):
        report = check_board_health()
    assert report["ok"] is True
    assert report["missing"] == [] or all(
        f.startswith("inbox/") for f in report["missing"]
    )
    assert report["empty"] == []
    assert len(report["present"]) >= 6  # sprint, backlog, project, architecture, decisions, standup


# ---------------------------------------------------------------------------
# check_board_health — missing files
# ---------------------------------------------------------------------------

def test_check_board_health_missing_critical_files(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    # Only create some important files, skip critical ones
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    with patch.object(restore_board_module, "BOARD_DIR", board):
        report = check_board_health()

    assert report["ok"] is False
    assert "sprint.md" in report["missing"]
    assert "backlog.md" in report["missing"]


def test_check_board_health_missing_important_files(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    # Create critical files only
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")

    with patch.object(restore_board_module, "BOARD_DIR", board):
        report = check_board_health()

    assert report["ok"] is False
    assert "project.md" in report["missing"]
    assert "architecture.md" in report["missing"]


# ---------------------------------------------------------------------------
# check_board_health — empty files
# ---------------------------------------------------------------------------

def test_check_board_health_empty_critical_file(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    # Create all files, but make sprint.md empty
    (board / "sprint.md").write_text("", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    with patch.object(restore_board_module, "BOARD_DIR", board):
        report = check_board_health()

    assert report["ok"] is False
    assert "sprint.md" in report["empty"]
    assert "backlog.md" in report["present"]


def test_check_board_health_empty_important_file(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("", encoding="utf-8")  # empty
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    with patch.object(restore_board_module, "BOARD_DIR", board):
        report = check_board_health()

    assert report["ok"] is False
    assert "project.md" in report["empty"]


# ---------------------------------------------------------------------------
# check_board_health — inbox handling
# ---------------------------------------------------------------------------

def test_check_board_health_missing_inbox_not_critical(tmp_path):
    board = tmp_path / "board"
    board.mkdir()
    # Create all critical + important files
    (board / "sprint.md").write_text("# Sprint\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")
    # No inbox directory at all

    with patch.object(restore_board_module, "BOARD_DIR", board):
        report = check_board_health()

    # Board is ok even without inbox files (they are not critical)
    assert report["ok"] is True
    # But inbox files are listed as missing
    inbox_missing = [f for f in report["missing"] if f.startswith("inbox/")]
    assert len(inbox_missing) > 0


def test_check_board_health_report_structure(temp_board_dir):
    with patch.object(restore_board_module, "BOARD_DIR", temp_board_dir):
        report = check_board_health()

    assert "ok" in report
    assert "missing" in report
    assert "empty" in report
    assert "present" in report
    assert isinstance(report["ok"], bool)
    assert isinstance(report["missing"], list)
    assert isinstance(report["empty"], list)
    assert isinstance(report["present"], list)
