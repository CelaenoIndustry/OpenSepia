"""Tests for integrations/base.py — constants and formatting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.base import (
    BOARD_LABELS, PRIORITY_LABELS, ROLE_LABELS, AGENT_DISPLAY,
    BoardProvider,
)


# ---------------------------------------------------------------------------
# BOARD_LABELS
# ---------------------------------------------------------------------------

def test_board_labels_has_expected_keys():
    expected = {"todo", "in_progress", "review", "testing", "done", "blocked"}
    assert set(BOARD_LABELS.keys()) == expected


def test_board_labels_values_start_with_status():
    for value in BOARD_LABELS.values():
        assert value.startswith("status::"), f"Expected status:: prefix, got {value}"


# ---------------------------------------------------------------------------
# PRIORITY_LABELS
# ---------------------------------------------------------------------------

def test_priority_labels_has_expected_keys():
    expected = {"critical", "high", "medium", "low"}
    assert set(PRIORITY_LABELS.keys()) == expected


def test_priority_labels_values_start_with_priority():
    for value in PRIORITY_LABELS.values():
        assert value.startswith("priority::"), f"Expected priority:: prefix, got {value}"


# ---------------------------------------------------------------------------
# ROLE_LABELS
# ---------------------------------------------------------------------------

def test_role_labels_has_expected_keys():
    expected = {"po", "pm", "dev", "devops", "tester"}
    assert set(ROLE_LABELS.keys()) == expected


def test_role_labels_values_start_with_role():
    for value in ROLE_LABELS.values():
        assert value.startswith("role::"), f"Expected role:: prefix, got {value}"


# ---------------------------------------------------------------------------
# AGENT_DISPLAY
# ---------------------------------------------------------------------------

def test_agent_display_has_all_agents():
    expected = {
        "po", "pm", "dev1", "dev2", "devops", "tester",
        "sec_analyst", "sec_engineer", "sec_pentester", "standup",
    }
    assert set(AGENT_DISPLAY.keys()) == expected


def test_agent_display_values_are_tuples():
    for agent_id, value in AGENT_DISPLAY.items():
        assert isinstance(value, tuple), f"{agent_id} value is not a tuple"
        assert len(value) == 2, f"{agent_id} tuple length is {len(value)}, expected 2"


def test_agent_display_names_are_strings():
    for agent_id, (emoji, name) in AGENT_DISPLAY.items():
        assert isinstance(name, str), f"{agent_id} name is not a string"
        assert len(name) > 0, f"{agent_id} name is empty"


# ---------------------------------------------------------------------------
# _format_agent_comment
# ---------------------------------------------------------------------------

class _DummyProvider(BoardProvider):
    """Minimal concrete subclass to test _format_agent_comment."""

    @property
    def name(self):
        return "dummy"

    @property
    def enabled(self):
        return False

    def init(self): ...
    def create_issue(self, *a, **kw): ...
    def close_issue(self, *a, **kw): ...
    def update_issue_status(self, *a, **kw): ...
    def comment_on_issue(self, *a, **kw): ...
    def find_issue_by_id(self, *a, **kw): ...
    def list_issues(self, *a, **kw): ...
    def search_issues(self, *a, **kw): ...
    def get_issue_comments(self, *a, **kw): ...
    def get_board_state(self, *a, **kw): ...
    def get_board_summary_md(self, *a, **kw): ...
    def create_mr(self, *a, **kw): ...
    def list_mrs(self, *a, **kw): ...
    def get_mr(self, *a, **kw): ...
    def comment_on_mr(self, *a, **kw): ...
    def approve_mr(self, *a, **kw): ...
    def merge_mr(self, *a, **kw): ...
    def close_mr(self, *a, **kw): ...
    def get_open_mrs_md(self, *a, **kw): ...
    def get_mr_changes(self, *a, **kw): ...


def test_format_agent_comment_known_agent():
    provider = _DummyProvider()
    result = provider._format_agent_comment("pm", "Hello world")
    assert "**Project Manager**" in result
    assert "(`pm`)" in result
    assert "Hello world" in result


def test_format_agent_comment_unknown_agent():
    provider = _DummyProvider()
    result = provider._format_agent_comment("unknown_agent", "Test msg")
    assert "UNKNOWN_AGENT" in result
    assert "Test msg" in result


def test_format_agent_comment_contains_emoji_for_known_agent():
    provider = _DummyProvider()
    emoji, _ = AGENT_DISPLAY["dev1"]
    result = provider._format_agent_comment("dev1", "Fix bug")
    assert emoji in result
