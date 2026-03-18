#!/usr/bin/env python3
"""
AI Dev Team — Board Provider ABC
Abstract interface for GitLab, GitHub, Gitea, and other providers.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Label conventions (shared across providers)
# =============================================================================
BOARD_LABELS = {
    "todo":        "status::todo",
    "in_progress": "status::in-progress",
    "review":      "status::review",
    "testing":     "status::testing",
    "done":        "status::done",
    "blocked":     "status::blocked",
}

PRIORITY_LABELS = {
    "critical": "priority::critical",
    "high":     "priority::high",
    "medium":   "priority::medium",
    "low":      "priority::low",
}

ROLE_LABELS = {
    "po":     "role::product-owner",
    "pm":     "role::project-manager",
    "dev":    "role::developer",
    "devops": "role::devops",
    "tester": "role::tester",
}

AGENT_DISPLAY = {
    "po":            ("🟣", "Product Owner"),
    "pm":            ("🔵", "Project Manager"),
    "dev1":          ("🟢", "Developer 1"),
    "dev2":          ("🟩", "Developer 2"),
    "devops":        ("🟠", "DevOps Engineer"),
    "tester":        ("🔴", "QA Engineer"),
    "sec_analyst":   ("🛡️", "Security Analyst"),
    "sec_engineer":  ("🔐", "Security Engineer"),
    "sec_pentester": ("💀", "Penetration Tester"),
    "standup":       ("📋", "Daily Standup"),
}


# =============================================================================
# BoardProvider ABC
# =============================================================================
class BoardProvider(ABC):
    """
    Common interface for managing issues, boards, and merge/pull requests.
    Implementations: GitLabProvider, GitHubProvider, ...
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier — "gitlab", "github", etc."""
        ...

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Is the provider configured and ready to use?"""
        ...

    @abstractmethod
    def init(self) -> None:
        """Initialize project (labels, board, ...)."""
        ...

    # ----- Issues -----

    @abstractmethod
    def create_issue(self, title: str, description: str,
                     labels: list = None, **kwargs) -> dict:
        ...

    @abstractmethod
    def close_issue(self, issue_id: Any) -> dict:
        ...

    @abstractmethod
    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict:
        ...

    @abstractmethod
    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict:
        ...

    @abstractmethod
    def find_issue_by_id(self, story_id: str) -> Optional[int]:
        ...

    @abstractmethod
    def list_issues(self, labels: str = None,
                    state: str = "opened") -> list:
        ...

    @abstractmethod
    def search_issues(self, query: str,
                      state: str = "opened") -> list:
        ...

    @abstractmethod
    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list:
        ...

    # ----- Board -----

    @abstractmethod
    def get_board_state(self) -> dict:
        ...

    @abstractmethod
    def get_board_summary_md(self) -> str:
        ...

    # ----- MR / PR -----

    @abstractmethod
    def create_mr(self, source_branch: str, target_branch: str,
                  title: str, description: str = "") -> dict:
        ...

    @abstractmethod
    def list_mrs(self, state: str = "opened") -> list:
        ...

    @abstractmethod
    def get_mr(self, mr_id: Any) -> dict:
        ...

    @abstractmethod
    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict:
        ...

    @abstractmethod
    def approve_mr(self, mr_id: Any) -> dict:
        ...

    @abstractmethod
    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict:
        ...

    @abstractmethod
    def close_mr(self, mr_id: Any) -> dict:
        ...

    @abstractmethod
    def get_open_mrs_md(self) -> str:
        ...

    @abstractmethod
    def get_mr_changes(self, mr_id: Any) -> dict:
        ...

    # ----- Cache management -----

    def clear_cache(self) -> None:
        """Clear any in-memory issue caches.

        Call this when issues may have been deleted or renumbered externally,
        e.g. after a board sync or restore operation.  The default
        implementation is a no-op; providers with caches should override.
        """

    # ----- High-level (default implementations) -----

    def create_story(self, story_id: str, title: str, description: str,
                     priority: str = "medium", assigned_to: Optional[str] = None) -> dict:
        """Create a user story as an issue."""
        labels = [
            BOARD_LABELS["todo"],
            PRIORITY_LABELS.get(priority, PRIORITY_LABELS["medium"]),
        ]
        if assigned_to and assigned_to in ROLE_LABELS:
            labels.append(ROLE_LABELS[assigned_to])

        desc = f"**Story ID**: {story_id}\n\n{description}"
        return self.create_issue(f"[{story_id}] {title}", desc, labels=labels)

    def create_bug(self, bug_id: str, title: str, description: str,
                   severity: str = "medium", related_issue: Optional[Any] = None) -> dict:
        """Create a bug report as an issue."""
        labels = [
            BOARD_LABELS["todo"],
            PRIORITY_LABELS.get(severity, PRIORITY_LABELS["medium"]),
            "type::bug",
        ]
        desc = f"**Bug ID**: {bug_id}\n\n{description}"
        if related_issue:
            desc += f"\n\nRelated to #{related_issue}"

        return self.create_issue(
            f"\U0001f41b [{bug_id}] {title}", desc, labels=labels
        )

    def get_recent_comments_md(self, story_ids: list[str],
                               max_chars: int = 6000) -> str:
        """Return recent comments as Markdown for agent context.

        Fetches the latest comments from each active story's issue,
        including human comments posted directly on GitLab/GitHub.
        """
        if not self.enabled:
            return ""

        lines = []
        total_chars = 0

        for sid in story_ids:
            iid = self.find_issue_by_id(sid)
            if not iid:
                continue

            notes = self.get_issue_comments(iid, limit=10)
            # Filter out system notes
            notes = [n for n in notes if not n.get("system", False)]
            if not notes:
                continue

            header = f"### {sid} (#{iid})\n"
            if total_chars + len(header) > max_chars:
                break
            lines.append(header)
            total_chars += len(header)

            for note in notes[-8:]:
                author = note.get("author", {}).get("name", "?")
                body = note.get("body", "")
                if len(body) > 800:
                    body = body[:797] + "..."
                entry = f"- **{author}**: {body}\n"
                if total_chars + len(entry) > max_chars:
                    break
                lines.append(entry)
                total_chars += len(entry)

        return "".join(lines)

    def _format_agent_comment(self, agent_id: str, message: str) -> str:
        """Format a comment from an agent with emoji and name."""
        emoji, name = AGENT_DISPLAY.get(agent_id, ("💬", agent_id.upper()))
        return f"{emoji} **{name}** (`{agent_id}`)\n\n{message}"
