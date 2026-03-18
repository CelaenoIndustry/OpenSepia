#!/usr/bin/env python3
"""
AI Dev Team — GitLab Provider
BoardProvider implementation for GitLab API v4.
"""

import os
import json
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any, Optional, Union
from dataclasses import dataclass

from ..base import (
    BoardProvider, BOARD_LABELS, PRIORITY_LABELS, ROLE_LABELS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class GitLabConfig:
    url: str = ""
    token: str = ""
    project_id: str = ""

    def __post_init__(self):
        self.url = os.getenv("GITLAB_URL", self.url).rstrip("/")
        self.token = os.getenv("GITLAB_TOKEN", self.token)
        self.project_id = os.getenv("GITLAB_PROJECT_ID", self.project_id)

    @property
    def api_base(self) -> str:
        encoded = urllib.parse.quote(self.project_id, safe="")
        return f"{self.url}/api/v4/projects/{encoded}"

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.token and self.project_id)


# =============================================================================
# HTTP helper
# =============================================================================
def _api_call(config: GitLabConfig, method: str, endpoint: str,
              data: Optional[dict] = None, params: Optional[dict] = None,
              _max_retries: int = 4) -> Union[dict, list]:
    """Perform an API call to GitLab with retry on 429 rate limit."""
    url = f"{config.api_base}{endpoint}"

    if params:
        url += "?" + urllib.parse.urlencode(params)

    body = json.dumps(data).encode("utf-8") if data else None

    for attempt in range(_max_retries + 1):
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "PRIVATE-TOKEN": config.token,
                "Content-Type": "application/json",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_body = resp.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return {"status": "ok"}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _max_retries:
                retry_after = int(e.headers.get("Retry-After", 0))
                wait = max(retry_after, 2 ** attempt)
                logger.warning(f"GitLab API 429 on {method} {endpoint}, retry {attempt + 1}/{_max_retries} in {wait}s")
                time.sleep(wait)
                continue
            error_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"GitLab API {method} {endpoint}: {e.code} — {error_body}")
            return {"error": e.code, "message": error_body}
        except Exception as e:
            logger.error(f"GitLab API {method} {endpoint}: {e}")
            return {"error": str(e)}


# =============================================================================
# Label colors (GitLab-specific)
# =============================================================================
GITLAB_LABEL_COLORS = {
    "status::todo":        "#428BCA",
    "status::in-progress": "#F0AD4E",
    "status::review":      "#8E44AD",
    "status::testing":     "#E67E22",
    "status::done":        "#5CB85C",
    "status::blocked":     "#D9534F",
    "role::product-owner":  "#9B59B6",
    "role::project-manager": "#3498DB",
    "role::developer":      "#2ECC71",
    "role::devops":         "#E67E22",
    "role::tester":         "#E74C3C",
    "priority::critical":   "#D9534F",
    "priority::high":       "#F0AD4E",
    "priority::medium":     "#F7DC6F",
    "priority::low":        "#5CB85C",
}


def ensure_labels(config: GitLabConfig) -> None:
    """Create all required labels if they do not exist."""
    existing = _api_call(config, "GET", "/labels", params={"per_page": 100})
    if isinstance(existing, dict) and "error" in existing:
        logger.error(f"Cannot load labels: {existing}")
        return

    existing_names = {l["name"] for l in existing} if isinstance(existing, list) else set()

    for label_name, color in GITLAB_LABEL_COLORS.items():
        if label_name not in existing_names:
            result = _api_call(config, "POST", "/labels", data={
                "name": label_name,
                "color": color,
            })
            if "error" not in result:
                logger.info(f"Label created: {label_name}")
            else:
                logger.warning(f"Label {label_name}: {result}")


# =============================================================================
# Board setup
# =============================================================================
def setup_board(config: GitLabConfig) -> None:
    """Initialize a GitLab board with the correct columns."""
    ensure_labels(config)

    boards = _api_call(config, "GET", "/boards")
    if isinstance(boards, list) and boards:
        board_id = boards[0]["id"]
    else:
        result = _api_call(config, "POST", "/boards", data={"name": "AI Dev Team"})
        board_id = result.get("id")

    if not board_id:
        logger.error("Cannot create/find board")
        return

    lists = _api_call(config, "GET", f"/boards/{board_id}/lists")
    existing_labels = set()
    if isinstance(lists, list):
        existing_labels = {l.get("label", {}).get("name", "") for l in lists}

    for status_key in ["todo", "in_progress", "review", "testing", "done"]:
        label_name = BOARD_LABELS[status_key]
        if label_name not in existing_labels:
            all_labels = _api_call(config, "GET", "/labels",
                                   params={"search": label_name})
            if isinstance(all_labels, list) and all_labels:
                label_id = all_labels[0]["id"]
                _api_call(config, "POST", f"/boards/{board_id}/lists",
                          data={"label_id": label_id})
                logger.info(f"Board list added: {label_name}")

    logger.info(f"Board #{board_id} configured")


# =============================================================================
# GitLabProvider
# =============================================================================
class GitLabProvider(BoardProvider):
    """GitLab implementation of BoardProvider."""

    def __init__(self, config: Optional[GitLabConfig] = None) -> None:
        self.config = config or GitLabConfig()
        self._issue_cache: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "gitlab"

    @property
    def enabled(self) -> bool:
        return self.config.is_configured

    def init(self) -> None:
        if not self.enabled:
            logger.warning("GitLab is not configured — skipping")
            return
        setup_board(self.config)

    # ----- Cache management -----

    def clear_cache(self) -> None:
        """Clear the in-memory story-id → issue-IID cache.

        Call after bulk operations (board sync, restore) or when a cached
        IID is suspected stale (e.g. issue was deleted).
        """
        self._issue_cache = {}

    # ----- Issues -----

    def create_issue(self, title: str, description: str,
                     labels: list = None, **kwargs) -> dict:
        data = {"title": title, "description": description}
        if labels:
            data["labels"] = ",".join(labels)
        if kwargs.get("milestone_id"):
            data["milestone_id"] = kwargs["milestone_id"]
        if kwargs.get("weight"):
            data["weight"] = kwargs["weight"]

        result = _api_call(self.config, "POST", "/issues", data=data)
        if "error" not in result:
            logger.info(f"Issue #{result.get('iid')} created: {title}")
        return result

    def close_issue(self, issue_id: Any) -> dict:
        return _api_call(self.config, "PUT", f"/issues/{issue_id}",
                         data={"state_event": "close"})

    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict:
        from_label = BOARD_LABELS.get(from_status)
        to_label = BOARD_LABELS.get(to_status)

        data = {}
        if from_label:
            data["remove_labels"] = from_label
        if to_label:
            data["add_labels"] = to_label

        result = _api_call(self.config, "PUT", f"/issues/{issue_id}", data=data)
        if "error" not in result:
            logger.info(f"Issue #{issue_id}: {from_status} → {to_status}")
        return result

    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict:
        body = self._format_agent_comment(agent_id, message)
        return _api_call(self.config, "POST",
                         f"/issues/{issue_id}/notes", data={"body": body})

    def find_issue_by_id(self, story_id: str) -> Optional[int]:
        # 1) In-memory cache
        if story_id in self._issue_cache:
            return self._issue_cache[story_id]

        # 2) File cache
        import json as _json
        cache_path = Path(__file__).parent.parent.parent / "board" / ".gitlab_issue_map.json"
        try:
            with open(cache_path, "r") as f:
                file_cache = _json.load(f)
            if story_id in file_cache:
                iid = file_cache[story_id]
                self._issue_cache[story_id] = iid
                return iid
        except (FileNotFoundError, _json.JSONDecodeError, KeyError):
            pass

        # 3) API search
        issues = self.search_issues(f"[{story_id}]")
        for issue in issues:
            title = issue.get("title", "")
            if f"[{story_id}]" in title:
                iid = issue["iid"]
                self._issue_cache[story_id] = iid
                return iid

        return None

    def list_issues(self, labels: str = None,
                    state: str = "opened") -> list:
        params = {"state": state, "per_page": 50}
        if labels:
            params["labels"] = labels
        result = _api_call(self.config, "GET", "/issues", params=params)
        return result if isinstance(result, list) else []

    def search_issues(self, query: str,
                      state: str = "opened") -> list:
        params = {"search": query, "state": state, "per_page": 20}
        result = _api_call(self.config, "GET", "/issues", params=params)
        return result if isinstance(result, list) else []

    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list:
        params = {"sort": "desc", "per_page": limit}
        result = _api_call(self.config, "GET",
                           f"/issues/{issue_id}/notes", params=params)
        return result if isinstance(result, list) else []

    # ----- Board -----

    def get_board_state(self) -> dict:
        state = {}
        for status_key, label_name in BOARD_LABELS.items():
            issues = self.list_issues(labels=label_name)
            state[status_key] = [
                {
                    "iid": i["iid"],
                    "title": i["title"],
                    "labels": [l for l in i.get("labels", [])],
                    "updated_at": i.get("updated_at", ""),
                }
                for i in issues
            ]
        return state

    def get_board_summary_md(self) -> str:
        if not self.enabled:
            return "(GitLab integration is not active)"

        state = self.get_board_state()
        lines = ["## 📋 Board — current state\n"]

        status_names = {
            "todo": "📥 TODO",
            "in_progress": "🔄 IN PROGRESS",
            "review": "👀 REVIEW",
            "testing": "🧪 TESTING",
            "done": "✅ DONE",
            "blocked": "🚫 BLOCKED",
        }

        for status_key, display_name in status_names.items():
            issues = state.get(status_key, [])
            lines.append(f"### {display_name} ({len(issues)})")
            if issues:
                for i in issues:
                    prio = next((l for l in i["labels"] if l.startswith("priority::")), "")
                    prio_short = prio.replace("priority::", "") if prio else ""
                    lines.append(f"- **#{i['iid']}** {i['title']} [{prio_short}]")
            else:
                lines.append("_(empty)_")
            lines.append("")

        return "\n".join(lines)

    # ----- MR -----

    def create_mr(self, source_branch: str, target_branch: str = "main",
                  title: str = "", description: str = "") -> dict:
        data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title or f"Merge {source_branch} into {target_branch}",
            "description": description,
            "remove_source_branch": True,
        }
        return _api_call(self.config, "POST", "/merge_requests", data=data)

    def list_mrs(self, state: str = "opened") -> list:
        result = _api_call(self.config, "GET", "/merge_requests",
                           params={"state": state})
        return result if isinstance(result, list) else []

    def get_mr(self, mr_id: Any) -> dict:
        return _api_call(self.config, "GET", f"/merge_requests/{mr_id}")

    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict:
        prefix = f"**🤖 {agent_id.upper()}**: " if agent_id else ""
        return _api_call(self.config, "POST",
                         f"/merge_requests/{mr_id}/notes",
                         data={"body": prefix + body})

    def approve_mr(self, mr_id: Any) -> dict:
        return _api_call(self.config, "POST",
                         f"/merge_requests/{mr_id}/approve")

    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict:
        data = {
            "squash": squash,
            "should_remove_source_branch": True,
        }
        return _api_call(self.config, "PUT",
                         f"/merge_requests/{mr_id}/merge", data=data)

    def close_mr(self, mr_id: Any) -> dict:
        return _api_call(self.config, "PUT",
                         f"/merge_requests/{mr_id}",
                         data={"state_event": "close"})

    def get_mr_changes(self, mr_id: Any) -> dict:
        return _api_call(self.config, "GET",
                         f"/merge_requests/{mr_id}/changes")

    def get_open_mrs_md(self) -> str:
        mrs = self.list_mrs("opened")
        if not mrs:
            return "### 🔀 Open Merge Requests\n_(none)_"

        lines = [f"### 🔀 Open Merge Requests ({len(mrs)})\n"]
        for mr in mrs[:10]:
            iid = mr.get("iid", "?")
            title = mr.get("title", "?")
            author = mr.get("author", {}).get("name", "?")
            source = mr.get("source_branch", "?")
            target = mr.get("target_branch", "?")
            lines.append(f"- **!{iid}** {title}")
            lines.append(f"  - `{source}` → `{target}` (by {author})")

        return "\n".join(lines)

    # ----- Backward-compatible methods -----

    def create_story(self, story_id: str, title: str, description: str,
                     priority: str = "medium", assigned_to: Optional[str] = None) -> dict:
        result = super().create_story(story_id, title, description,
                                      priority, assigned_to)
        if "iid" in result:
            self._issue_cache[story_id] = result["iid"]
        return result

    def create_sprint(self, sprint_number: int, due_date: str = None) -> dict:
        """Create a sprint as a milestone (GitLab-specific)."""
        data = {
            "title": f"Sprint {sprint_number}",
            "description": f"Automatically created sprint #{sprint_number}",
        }
        if due_date:
            data["due_date"] = due_date
        return _api_call(self.config, "POST", "/milestones", data=data)

    # ----- Aliases for backward compatibility with GitLabClient -----

    def comment(self, issue_iid: int, agent_id: str, message: str) -> dict:
        return self.comment_on_issue(issue_iid, agent_id, message)

    def update_story_status(self, issue_iid: int,
                            from_status: str, to_status: str) -> dict:
        return self.update_issue_status(issue_iid, from_status, to_status)

    def close_story(self, issue_iid: int) -> dict:
        return self.close_issue(issue_iid)

    def find_issue_by_story_id(self, story_id: str) -> Optional[int]:
        return self.find_issue_by_id(story_id)

    def get_issue_notes(self, issue_iid: int, max_notes: int = 10) -> list:
        return self.get_issue_comments(issue_iid, limit=max_notes)

    def comment_mr(self, mr_iid: int, body: str, agent_id: str = "") -> dict:
        return self.comment_on_mr(mr_iid, body, agent_id)


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    config = GitLabConfig()
    if not config.is_configured:
        print("Set GITLAB_URL, GITLAB_TOKEN, GITLAB_PROJECT_ID")
        sys.exit(1)

    provider = GitLabProvider(config)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        provider.init()
        print("✅ GitLab board initialized")
    elif cmd == "status":
        print(provider.get_board_summary_md())
    elif cmd == "test":
        result = provider.create_story(
            "TEST-001", "Test story", "This is a test", priority="low"
        )
        print(f"Created issue: {result}")
    else:
        print(f"Usage: python gitlab.py [init|status|test]")
