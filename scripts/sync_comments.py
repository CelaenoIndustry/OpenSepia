#!/usr/bin/env python3
"""
AI Dev Team — Board Comment Sync
Synchronizes agent comments to provider issues/MRs and reads comments back.

WRITE: Agent writes to inbox -> extract STORY-XXX -> post comment to provider issue
READ:  Provider issues -> fetch comments -> inject into agent context
"""

import os
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
BOARD_DIR = BASE_DIR / "board"


# =============================================================================
# WRITE functions — agent output -> provider comments
# =============================================================================

def extract_story_refs(text: str) -> set[str]:
    """Extract STORY-XXX and BUG-XXX references from text."""
    return set(re.findall(r'((?:STORY|BUG)-\d+)', text))


def extract_mr_refs(text: str) -> set[int]:
    """Extract MR IID references (!123) from text. Returns a set of ints."""
    return {int(m) for m in re.findall(r'!(\d+)', text)}


def truncate_for_comment(text: str, max_chars: int = 2000) -> str:
    """Truncate a message for a provider comment."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 20] + "\n\n_(truncated)_"


def post_agent_messages_to_provider(agent_id: str, written_files: list[dict[str, str]], client: Any) -> int:
    """
    Main WRITE: iterates over written inbox files, extracts story references,
    posts a comment to the corresponding provider issue.

    Args:
        agent_id: Agent ID (po, pm, dev1, ...)
        written_files: list of dicts with 'path' and 'content' keys
        client: BoardProvider instance

    Returns:
        number of posted comments
    """
    if not client or not client.enabled:
        return 0

    posted = 0

    for file_info in written_files:
        path = file_info.get("path", "")
        content = file_info.get("content", "")

        # Only inbox files
        if "board/inbox/" not in path:
            continue

        if not content.strip():
            continue

        # Extract story references
        story_refs = extract_story_refs(content)
        if not story_refs:
            continue

        # Prepare comment
        comment_body = truncate_for_comment(content)

        for story_id in story_refs:
            try:
                iid = client.find_issue_by_id(story_id)
                if not iid:
                    logger.debug(f"Provider: issue for {story_id} not found")
                    continue

                result = client.comment_on_issue(iid, agent_id, comment_body)
                if "error" not in result:
                    posted += 1
                    logger.info(f"Provider: comment from {agent_id} on {story_id} (#{iid})")
                else:
                    logger.warning(f"Provider: error commenting on {story_id}: {result}")

            except Exception as e:
                logger.warning(f"Provider: error sending comment on {story_id}: {e}")

        # MR comments and approvals — explicit !123 references
        mr_refs = extract_mr_refs(content)
        for mr_iid in mr_refs:
            try:
                result = client.comment_on_mr(mr_iid, comment_body, agent_id=agent_id)
                if "error" not in result:
                    posted += 1
                    logger.info(f"Provider: comment from {agent_id} on MR !{mr_iid}")

                # Auto-approve if agent approves
                if _is_approval(content):
                    _try_approve_mr(client, mr_iid, agent_id)

            except Exception as e:
                logger.warning(f"Provider: error commenting on MR !{mr_iid}: {e}")

        # MR comments — auto-detect from story references + review keywords
        if _is_review_message(content) and story_refs:
            mr_iids_from_stories = _find_mrs_for_stories(client, story_refs)
            # Skip MRs already handled via explicit !refs
            for mr_iid in mr_iids_from_stories - mr_refs:
                try:
                    result = client.comment_on_mr(mr_iid, comment_body, agent_id=agent_id)
                    if "error" not in result:
                        posted += 1
                        logger.info(f"Provider: review from {agent_id} on MR !{mr_iid}")

                    if _is_approval(content):
                        _try_approve_mr(client, mr_iid, agent_id)

                except Exception as e:
                    logger.warning(f"Provider: error posting review on MR !{mr_iid}: {e}")

    return posted


# Cache open MRs per sync cycle to avoid repeated API calls
_open_mrs_cache: list | None = None


def _get_open_mrs(client: Any) -> list:
    """Get open MRs, cached for the duration of the sync cycle."""
    global _open_mrs_cache
    if _open_mrs_cache is None:
        _open_mrs_cache = client.list_mrs("opened")
    return _open_mrs_cache


def reset_mr_cache() -> None:
    """Reset the open MRs cache. Call at the start of each sync cycle."""
    global _open_mrs_cache
    _open_mrs_cache = None


def _find_mrs_for_stories(client: Any, story_ids: set[str]) -> set[int]:
    """Find open MRs whose branch name or title contains any of the story IDs."""
    mrs = _get_open_mrs(client)
    matched = set()
    for mr in mrs:
        branch = mr.get("source_branch", "")
        title = mr.get("title", "")
        search_text = f"{branch} {title}".lower()
        for story_id in story_ids:
            # Match story123 (branch slug) or STORY-123 (title)
            slug = story_id.lower().replace("-", "")
            if slug in search_text or story_id.lower() in search_text:
                matched.add(mr["iid"])
                break
    return matched


_REVIEW_KEYWORDS = [
    "code review", "review", "qa review", "functional review",
    "pentest", "security review", "lgtm", "approve", "approved",
    "looks good", "needs changes", "request changes",
]

_APPROVE_KEYWORDS = ["approve", "lgtm", "approved", "looks good", "✅"]


def _is_review_message(content: str) -> bool:
    """Detect if a message is a code review or QA review."""
    content_lower = content.lower()
    return any(kw in content_lower for kw in _REVIEW_KEYWORDS)


def _is_approval(content: str) -> bool:
    """Detect if a message contains approval keywords."""
    content_lower = content.lower()
    # Must contain approval keyword but NOT rejection
    has_approval = any(kw in content_lower for kw in _APPROVE_KEYWORDS)
    has_rejection = any(kw in content_lower for kw in ["needs changes", "reject", "request changes", "not approved"])
    return has_approval and not has_rejection


def _try_approve_mr(client: Any, mr_iid: int, agent_id: str) -> None:
    """Try to approve an MR, log the result."""
    try:
        result = client.approve_mr(mr_iid)
        if "error" not in result:
            logger.info(f"Provider: {agent_id} approved MR !{mr_iid}")
        else:
            logger.debug(f"Provider: approve MR !{mr_iid} failed: {result}")
    except Exception as e:
        logger.debug(f"Provider: approve MR !{mr_iid} error: {e}")


# =============================================================================
# STANDUP functions — board/standup.md -> provider issues
# =============================================================================

def post_standup_to_provider(standup_path: Path, client: Any) -> int:
    """
    Read board/standup.md, extract STORY/BUG references,
    post 1 consolidated standup comment per issue.

    Returns:
        number of posted comments
    """
    if not client or not client.enabled:
        return 0

    if not standup_path.exists():
        return 0

    content = standup_path.read_text(encoding="utf-8")
    if not content.strip():
        return 0

    # Extract all STORY/BUG references from standups
    story_refs = extract_story_refs(content)
    if not story_refs:
        return 0

    # Prepare consolidated comment
    comment_body = f"📋 **Standup Summary**\n\n{truncate_for_comment(content, 3000)}"

    posted = 0
    for story_id in story_refs:
        try:
            iid = client.find_issue_by_id(story_id)
            if not iid:
                logger.debug(f"Standup: issue for {story_id} not found")
                continue

            result = client.comment_on_issue(iid, "standup", comment_body)
            if "error" not in result:
                posted += 1
                logger.info(f"Standup: comment on {story_id} (#{iid})")
            else:
                logger.warning(f"Standup: error commenting on {story_id}: {result}")

        except Exception as e:
            logger.warning(f"Standup: error sending to {story_id}: {e}")

    return posted


# =============================================================================
# READ functions — provider comments -> agent context
# =============================================================================

def get_active_story_ids(sprint_path: Path | None = None, backlog_path: Path | None = None) -> list[str]:
    """
    Extract active story IDs (not DONE) from sprint.md and backlog.md.
    """
    story_ids = []

    if sprint_path is None:
        sprint_path = BOARD_DIR / "sprint.md"
    if backlog_path is None:
        backlog_path = BOARD_DIR / "backlog.md"

    # Active sections — only these contain relevant story references
    ACTIVE_KEYWORDS = {"todo", "in progress", "in_progress", "review", "testing", "blocked"}

    for fpath in [sprint_path, backlog_path]:
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8")

        # Parse only active sections (TODO, IN PROGRESS, REVIEW, TESTING, BLOCKED)
        # Ignore DONE, Retrospective, Backlog, Notes, Velocity, etc.
        in_active_section = False
        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("##"):
                in_active_section = any(kw in stripped for kw in ACTIVE_KEYWORDS)
                continue
            if not in_active_section:
                continue

            refs = re.findall(r'((?:STORY|BUG)-\d+)', line)
            story_ids.extend(refs)

    # Deduplicate, preserve order
    seen = set()
    unique = []
    for sid in story_ids:
        if sid not in seen:
            seen.add(sid)
            unique.append(sid)

    return unique


def fetch_comments_for_context(story_ids: list[str], client: Any,
                                       max_chars: int = 2000) -> str:
    """
    Wrapper for client.get_recent_comments_md().
    Returns a Markdown section with provider comments for agent context.
    """
    if not client or not client.enabled:
        return ""

    if not story_ids:
        return ""

    try:
        return client.get_recent_comments_md(story_ids, max_chars=max_chars)
    except Exception as e:
        logger.warning(f"Provider: error fetching comments: {e}")
        return ""
