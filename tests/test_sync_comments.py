"""Tests for scripts/sync_comments.py — comment extraction and formatting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sync_comments import (
    extract_story_refs,
    extract_mr_refs,
    truncate_for_comment,
    get_active_story_ids,
    _is_review_message,
    _is_approval,
    _find_mrs_for_stories,
    reset_mr_cache,
)


# ---------------------------------------------------------------------------
# extract_story_refs
# ---------------------------------------------------------------------------

def test_extract_story_refs_finds_stories():
    text = "Working on STORY-001 and STORY-042."
    refs = extract_story_refs(text)
    assert "STORY-001" in refs
    assert "STORY-042" in refs


def test_extract_story_refs_finds_bugs():
    text = "Fixed BUG-002 in latest commit."
    refs = extract_story_refs(text)
    assert "BUG-002" in refs


def test_extract_story_refs_mixed():
    text = "STORY-001 depends on BUG-002 and STORY-003."
    refs = extract_story_refs(text)
    assert len(refs) == 3
    assert "STORY-001" in refs
    assert "BUG-002" in refs
    assert "STORY-003" in refs


def test_extract_story_refs_no_matches():
    text = "No references here."
    refs = extract_story_refs(text)
    assert refs == set()


def test_extract_story_refs_deduplicates():
    text = "STORY-001 is referenced twice: STORY-001."
    refs = extract_story_refs(text)
    assert len(refs) == 1


# ---------------------------------------------------------------------------
# extract_mr_refs
# ---------------------------------------------------------------------------

def test_extract_mr_refs_finds_refs():
    text = "Please review !123 and !456."
    refs = extract_mr_refs(text)
    assert 123 in refs
    assert 456 in refs


def test_extract_mr_refs_no_matches():
    text = "No MR references here."
    refs = extract_mr_refs(text)
    assert refs == set()


def test_extract_mr_refs_returns_ints():
    text = "See !99."
    refs = extract_mr_refs(text)
    assert refs == {99}
    for r in refs:
        assert isinstance(r, int)


def test_extract_mr_refs_deduplicates():
    text = "!123 and again !123."
    refs = extract_mr_refs(text)
    assert len(refs) == 1


# ---------------------------------------------------------------------------
# truncate_for_comment
# ---------------------------------------------------------------------------

def test_truncate_short_text():
    text = "Short message"
    assert truncate_for_comment(text) == text


def test_truncate_exact_limit():
    text = "x" * 2000
    assert truncate_for_comment(text) == text


def test_truncate_long_text():
    text = "x" * 3000
    result = truncate_for_comment(text)
    assert len(result) <= 2000
    assert result.endswith("_(truncated)_")


def test_truncate_custom_limit():
    text = "x" * 200
    result = truncate_for_comment(text, max_chars=100)
    assert len(result) <= 100
    assert result.endswith("_(truncated)_")


def test_truncate_preserves_content_when_short():
    text = "Hello world!"
    assert truncate_for_comment(text, max_chars=1000) == "Hello world!"


# ---------------------------------------------------------------------------
# get_active_story_ids
# ---------------------------------------------------------------------------

def test_get_active_story_ids_from_sprint(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text("""\
# Sprint

## TODO
- [ ] STORY-001: First task
- [ ] STORY-002: Second task

## IN PROGRESS
- [ ] BUG-003: A bug fix

## DONE
- [x] STORY-099: This is done
""", encoding="utf-8")

    backlog = tmp_path / "backlog.md"
    backlog.write_text("# Backlog\n", encoding="utf-8")

    result = get_active_story_ids(sprint_path=sprint, backlog_path=backlog)
    assert "STORY-001" in result
    assert "STORY-002" in result
    assert "BUG-003" in result
    # DONE stories should NOT appear
    assert "STORY-099" not in result


def test_get_active_story_ids_excludes_done(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text("""\
# Sprint

## DONE
- [x] STORY-050: Finished
- [x] STORY-051: Also finished
""", encoding="utf-8")

    backlog = tmp_path / "backlog.md"
    backlog.write_text("# Backlog\n", encoding="utf-8")

    result = get_active_story_ids(sprint_path=sprint, backlog_path=backlog)
    assert result == []


def test_get_active_story_ids_deduplicates(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text("""\
# Sprint

## TODO
- [ ] STORY-001: Task one

## REVIEW
- [ ] STORY-001: Task one (duplicate)
""", encoding="utf-8")

    backlog = tmp_path / "backlog.md"
    backlog.write_text("# Backlog\n", encoding="utf-8")

    result = get_active_story_ids(sprint_path=sprint, backlog_path=backlog)
    assert result.count("STORY-001") == 1


def test_get_active_story_ids_missing_files(tmp_path):
    sprint = tmp_path / "nonexistent_sprint.md"
    backlog = tmp_path / "nonexistent_backlog.md"
    result = get_active_story_ids(sprint_path=sprint, backlog_path=backlog)
    assert result == []


def test_get_active_story_ids_from_backlog_active_sections(tmp_path):
    sprint = tmp_path / "sprint.md"
    sprint.write_text("# Sprint\n", encoding="utf-8")

    backlog = tmp_path / "backlog.md"
    backlog.write_text("""\
# Backlog

## TODO
- STORY-010: A todo item

## BLOCKED
- BUG-020: A blocked bug

## DONE
- STORY-099: Finished
""", encoding="utf-8")

    result = get_active_story_ids(sprint_path=sprint, backlog_path=backlog)
    assert "STORY-010" in result
    assert "BUG-020" in result
    assert "STORY-099" not in result


# ---------------------------------------------------------------------------
# _is_review_message
# ---------------------------------------------------------------------------

def test_is_review_message_code_review():
    assert _is_review_message("## Code Review\nSTORY-001 looks good.")

def test_is_review_message_qa_review():
    assert _is_review_message("## QA Functional Review\nAll criteria met.")

def test_is_review_message_approve():
    assert _is_review_message("LGTM, approved!")

def test_is_review_message_not_review():
    assert not _is_review_message("Implemented STORY-001: added /users endpoint")


# ---------------------------------------------------------------------------
# _is_approval
# ---------------------------------------------------------------------------

def test_is_approval_lgtm():
    assert _is_approval("LGTM, code looks good to me.")

def test_is_approval_approved():
    assert _is_approval("Code review: APPROVED. Ship it!")

def test_is_approval_needs_changes():
    assert not _is_approval("Needs changes: missing error handling.")

def test_is_approval_reject():
    assert not _is_approval("I reject this, not approved yet.")

def test_is_approval_mixed_approve_and_reject():
    # If both approve and reject keywords present, reject wins
    assert not _is_approval("Looks good overall but needs changes in auth module.")


# ---------------------------------------------------------------------------
# _find_mrs_for_stories
# ---------------------------------------------------------------------------

class MockClient:
    def __init__(self, mrs):
        self._mrs = mrs
    def list_mrs(self, state):
        return self._mrs

def test_find_mrs_matches_branch_slug():
    reset_mr_cache()
    client = MockClient([
        {"iid": 1, "source_branch": "ai-team/story001-s1c1", "title": "AI Team: story001"},
        {"iid": 2, "source_branch": "ai-team/story002-s1c1", "title": "AI Team: story002"},
    ])
    result = _find_mrs_for_stories(client, {"STORY-001"})
    assert result == {1}

def test_find_mrs_matches_multiple_stories():
    reset_mr_cache()
    client = MockClient([
        {"iid": 5, "source_branch": "ai-team/story010-story011-s3c2", "title": "AI Team"},
    ])
    result = _find_mrs_for_stories(client, {"STORY-010", "STORY-011"})
    assert result == {5}

def test_find_mrs_no_match():
    reset_mr_cache()
    client = MockClient([
        {"iid": 1, "source_branch": "ai-team/story099-s1c1", "title": "AI Team: story099"},
    ])
    result = _find_mrs_for_stories(client, {"STORY-001"})
    assert result == set()

def test_find_mrs_matches_title():
    reset_mr_cache()
    client = MockClient([
        {"iid": 3, "source_branch": "feature/something", "title": "Fix for STORY-005"},
    ])
    result = _find_mrs_for_stories(client, {"STORY-005"})
    assert result == {3}
