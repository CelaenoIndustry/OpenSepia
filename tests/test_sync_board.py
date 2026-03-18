"""Tests for scripts/sync_board.py — backlog parsing and status normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sync_board import parse_backlog, normalize_status, parse_sprint_statuses


# ---------------------------------------------------------------------------
# parse_backlog
# ---------------------------------------------------------------------------

SAMPLE_BACKLOG = """\
# Backlog

## CRITICAL

### STORY-001: Implement login
**Status**: todo
**Assigned**: dev1

Login must support OAuth.

### BUG-001: Fix crash on startup
**Status**: in_progress

App crashes when config is missing.

---

## HIGH

### STORY-002: Add dashboard
**Status**: review

Dashboard with charts.

## LOW

### STORY-003: Update docs
**Status**: done
"""


def test_parse_backlog_returns_all_items(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    assert len(items) == 4


def test_parse_backlog_extracts_ids(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    ids = [item["id"] for item in items]
    assert "STORY-001" in ids
    assert "BUG-001" in ids
    assert "STORY-002" in ids
    assert "STORY-003" in ids


def test_parse_backlog_extracts_priority(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    by_id = {item["id"]: item for item in items}
    assert by_id["STORY-001"]["priority"] == "critical"
    assert by_id["STORY-002"]["priority"] == "high"
    assert by_id["STORY-003"]["priority"] == "low"


def test_parse_backlog_extracts_status(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    by_id = {item["id"]: item for item in items}
    assert by_id["STORY-001"]["status"] == "todo"
    assert by_id["BUG-001"]["status"] == "in_progress"
    assert by_id["STORY-002"]["status"] == "review"
    assert by_id["STORY-003"]["status"] == "done"


def test_parse_backlog_detects_bugs(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    by_id = {item["id"]: item for item in items}
    assert by_id["BUG-001"]["is_bug"] is True
    assert by_id["STORY-001"]["is_bug"] is False


def test_parse_backlog_extracts_assigned(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text(SAMPLE_BACKLOG, encoding="utf-8")
    items = parse_backlog(backlog)
    by_id = {item["id"]: item for item in items}
    assert by_id["STORY-001"]["assigned"] == "dev1"
    assert by_id["STORY-002"]["assigned"] is None


def test_parse_backlog_empty_file(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text("# Backlog\n", encoding="utf-8")
    items = parse_backlog(backlog)
    assert items == []


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------

def test_normalize_status_todo():
    assert normalize_status("todo") == "todo"


def test_normalize_status_in_progress():
    assert normalize_status("in_progress") == "in_progress"
    assert normalize_status("in progress") == "in_progress"


def test_normalize_status_done():
    assert normalize_status("done") == "done"


def test_normalize_status_done_conditional():
    assert normalize_status("DONE (conditionally accepted)") == "done"


def test_normalize_status_blocked():
    assert normalize_status("blocked") == "blocked"


def test_normalize_status_review():
    assert normalize_status("review") == "review"


def test_normalize_status_testing():
    assert normalize_status("testing") == "testing"


def test_normalize_status_unknown_defaults_to_todo():
    assert normalize_status("something_random") == "todo"


def test_normalize_status_case_insensitive():
    assert normalize_status("TODO") == "todo"
    assert normalize_status("DONE") == "done"
    assert normalize_status("In_Progress") == "in_progress"


# ---------------------------------------------------------------------------
# parse_sprint_statuses
# ---------------------------------------------------------------------------

SAMPLE_SPRINT_SECTION_BASED = """\
# Sprint 5

## TODO
- [ ] **STORY-010**: New feature
- [ ] **BUG-005**: Fix button

## IN PROGRESS
- [ ] **STORY-011**: Refactor module

## DONE
- [x] **STORY-009**: Completed task
"""

SAMPLE_SPRINT_BLOCK_BASED = """\
# Sprint 5

### STORY-020: Block feature
**Status**: review

### STORY-021: Another item
**Status**: testing

### BUG-010: Block bug
**Status**: blocked
"""


def test_parse_sprint_statuses_section_based(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text(SAMPLE_SPRINT_SECTION_BASED, encoding="utf-8")
    statuses = parse_sprint_statuses(sprint)
    assert statuses["STORY-010"] == "todo"
    assert statuses["BUG-005"] == "todo"
    assert statuses["STORY-011"] == "in_progress"
    assert statuses["STORY-009"] == "done"


def test_parse_sprint_statuses_block_based(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text(SAMPLE_SPRINT_BLOCK_BASED, encoding="utf-8")
    statuses = parse_sprint_statuses(sprint)
    assert statuses["STORY-020"] == "review"
    assert statuses["STORY-021"] == "testing"
    assert statuses["BUG-010"] == "blocked"


def test_parse_sprint_statuses_section_takes_priority(tmp_path):
    content = """\
# Sprint

## IN PROGRESS
- [ ] **STORY-100**: Overlap item

### STORY-100: Overlap item
**Status**: done
"""
    sprint = tmp_path / "sprint.md"
    sprint.write_text(content, encoding="utf-8")
    statuses = parse_sprint_statuses(sprint)
    # Section-based (strategy 1) has priority
    assert statuses["STORY-100"] == "in_progress"


def test_parse_sprint_statuses_empty_file(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text("# Sprint\n", encoding="utf-8")
    statuses = parse_sprint_statuses(sprint)
    assert statuses == {}
