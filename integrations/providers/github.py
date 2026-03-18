#!/usr/bin/env python3
"""
AI Dev Team — GitHub Provider
BoardProvider implementation for GitHub REST API v3.
Issues = stories/bugs, Pull Requests = merge requests.
Labels for board state (same conventions as GitLab).
"""

import os
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any, Optional, Union

from ..base import (
    BoardProvider, BOARD_LABELS, PRIORITY_LABELS, ROLE_LABELS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================
class GitHubConfig:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.owner = os.getenv("GITHUB_OWNER", "")
        self.repo = os.getenv("GITHUB_REPO", "")
        self.api_url = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    @property
    def api_base(self) -> str:
        return f"{self.api_url}/repos/{self.owner}/{self.repo}"

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.owner and self.repo)


# =============================================================================
# HTTP helper
# =============================================================================
def _api_call(config: GitHubConfig, method: str, endpoint: str,
              data: Optional[dict] = None, params: Optional[dict] = None) -> Union[dict, list]:
    """Perform an API call to GitHub."""
    url = f"{config.api_base}{endpoint}"

    if params:
        url += "?" + urllib.parse.urlencode(params)

    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {config.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
            if response_body:
                return json.loads(response_body)
            return {"status": "ok"}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error(f"GitHub API {method} {endpoint}: {e.code} — {error_body}")
        return {"error": e.code, "message": error_body}
    except Exception as e:
        logger.error(f"GitHub API {method} {endpoint}: {e}")
        return {"error": str(e)}


# =============================================================================
# Label colors (GitHub-specific — hex without #)
# =============================================================================
GITHUB_LABEL_COLORS = {
    "status::todo":        "428BCA",
    "status::in-progress": "F0AD4E",
    "status::review":      "8E44AD",
    "status::testing":     "E67E22",
    "status::done":        "5CB85C",
    "status::blocked":     "D9534F",
    "role::product-owner":  "9B59B6",
    "role::project-manager": "3498DB",
    "role::developer":      "2ECC71",
    "role::devops":         "E67E22",
    "role::tester":         "E74C3C",
    "priority::critical":   "D9534F",
    "priority::high":       "F0AD4E",
    "priority::medium":     "F7DC6F",
    "priority::low":        "5CB85C",
    "type::bug":            "D93F0B",
}


def ensure_labels(config: GitHubConfig) -> None:
    """Create all required labels if they do not exist."""
    # Load existing labels (paginated)
    existing_names = set()
    page = 1
    while True:
        result = _api_call(config, "GET", "/labels",
                           params={"per_page": 100, "page": page})
        if not isinstance(result, list) or not result:
            break
        existing_names.update(l["name"] for l in result)
        if len(result) < 100:
            break
        page += 1

    for label_name, color in GITHUB_LABEL_COLORS.items():
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
# GitHubProvider
# =============================================================================
class GitHubProvider(BoardProvider):
    """GitHub implementation of BoardProvider."""

    def __init__(self, config: Optional[GitHubConfig] = None) -> None:
        self.config = config or GitHubConfig()
        self._issue_cache: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "github"

    @property
    def enabled(self) -> bool:
        return self.config.is_configured

    def init(self) -> None:
        if not self.enabled:
            logger.warning("GitHub is not configured — skipping")
            return
        ensure_labels(self.config)
        logger.info("GitHub labels initialized")

    # ----- Cache management -----

    def clear_cache(self) -> None:
        """Clear the in-memory story-id → issue-number cache.

        Call after bulk operations (board sync, restore) or when a cached
        number is suspected stale (e.g. issue was deleted).
        """
        self._issue_cache = {}

    # ----- Issues -----

    def create_issue(self, title: str, description: str,
                     labels: list = None, **kwargs) -> dict:
        data = {"title": title, "body": description}
        if labels:
            data["labels"] = labels  # GitHub accepts a list directly

        result = _api_call(self.config, "POST", "/issues", data=data)
        if "error" not in result:
            # Map GitHub "number" to "iid" for compatibility
            result["iid"] = result.get("number")
            logger.info(f"Issue #{result.get('number')} created: {title}")
        return result

    def close_issue(self, issue_id: Any) -> dict:
        return _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                         data={"state": "closed"})

    def update_issue_status(self, issue_id: Any, from_status: str,
                            to_status: str) -> dict:
        # Load current labels
        issue = _api_call(self.config, "GET", f"/issues/{issue_id}")
        if "error" in issue:
            return issue

        current_labels = [l["name"] for l in issue.get("labels", [])]

        # Remove old status label
        from_label = BOARD_LABELS.get(from_status)
        if from_label and from_label in current_labels:
            current_labels.remove(from_label)

        # Add new status label
        to_label = BOARD_LABELS.get(to_status)
        if to_label and to_label not in current_labels:
            current_labels.append(to_label)

        result = _api_call(self.config, "PATCH", f"/issues/{issue_id}",
                           data={"labels": current_labels})
        if "error" not in result:
            logger.info(f"Issue #{issue_id}: {from_status} → {to_status}")
        return result

    def comment_on_issue(self, issue_id: Any, agent_id: str,
                         message: str) -> dict:
        body = self._format_agent_comment(agent_id, message)
        return _api_call(self.config, "POST",
                         f"/issues/{issue_id}/comments",
                         data={"body": body})

    def find_issue_by_id(self, story_id: str) -> Optional[int]:
        # 1) In-memory cache
        if story_id in self._issue_cache:
            return self._issue_cache[story_id]

        # 2) File cache
        import json as _json
        cache_path = Path(__file__).parent.parent.parent / "board" / ".github_issue_map.json"
        try:
            with open(cache_path, "r") as f:
                file_cache = _json.load(f)
            if story_id in file_cache:
                num = file_cache[story_id]
                self._issue_cache[story_id] = num
                return num
        except (FileNotFoundError, _json.JSONDecodeError, KeyError):
            pass

        # 3) API search
        issues = self.search_issues(f"[{story_id}]")
        for issue in issues:
            title = issue.get("title", "")
            if f"[{story_id}]" in title:
                num = issue["number"]
                self._issue_cache[story_id] = num
                return num

        return None

    def list_issues(self, labels: str = None,
                    state: str = "opened") -> list:
        # GitHub uses "open"/"closed" instead of "opened"/"closed"
        gh_state = "open" if state == "opened" else state
        params = {"state": gh_state, "per_page": 50}
        if labels:
            params["labels"] = labels

        result = _api_call(self.config, "GET", "/issues", params=params)
        if not isinstance(result, list):
            return []

        # Filter out pull requests (GitHub returns issues and PRs together)
        issues = [i for i in result if "pull_request" not in i]
        # Add "iid" alias
        for i in issues:
            i["iid"] = i.get("number")
        return issues

    def search_issues(self, query: str,
                      state: str = "opened") -> list:
        # GitHub Search API
        gh_state = "open" if state == "opened" else "closed"
        safe_query = urllib.parse.quote(query, safe="")
        q = f"{safe_query} repo:{self.config.owner}/{self.config.repo} is:issue state:{gh_state}"
        url = f"{self.config.api_url}/search/issues"
        params = {"q": q, "per_page": 20}

        full_url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            full_url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                for i in items:
                    i["iid"] = i.get("number")
                return items
        except Exception as e:
            logger.error(f"GitHub Search API: {e}")
            return []

    def get_issue_comments(self, issue_id: Any,
                           limit: int = 10) -> list:
        params = {"per_page": limit}
        result = _api_call(self.config, "GET",
                           f"/issues/{issue_id}/comments", params=params)
        if not isinstance(result, list):
            return []

        # Map to GitLab-compatible format
        comments = []
        for c in result:
            comments.append({
                "id": c.get("id"),
                "body": c.get("body", ""),
                "author": {
                    "name": c.get("user", {}).get("login", "?"),
                },
                "created_at": c.get("created_at", ""),
                "system": False,
            })
        return comments

    # ----- Board -----

    def get_board_state(self) -> dict:
        state = {}
        for status_key, label_name in BOARD_LABELS.items():
            issues = self.list_issues(labels=label_name)
            state[status_key] = [
                {
                    "iid": i.get("number"),
                    "title": i.get("title", ""),
                    "labels": [l["name"] for l in i.get("labels", [])
                               if isinstance(l, dict)],
                    "updated_at": i.get("updated_at", ""),
                }
                for i in issues
            ]
        return state

    def get_board_summary_md(self) -> str:
        if not self.enabled:
            return "(GitHub integration is not active)"

        state = self.get_board_state()
        lines = ["## 📋 GitHub Board — current state\n"]

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

    # ----- PR (as MR) -----

    def create_mr(self, source_branch: str, target_branch: str = "main",
                  title: str = "", description: str = "") -> dict:
        data = {
            "head": source_branch,
            "base": target_branch,
            "title": title or f"Merge {source_branch} into {target_branch}",
            "body": description,
        }
        result = _api_call(self.config, "POST", "/pulls", data=data)
        if "error" not in result:
            result["iid"] = result.get("number")
        return result

    def list_mrs(self, state: str = "opened") -> list:
        gh_state = "open" if state == "opened" else state
        params = {"state": gh_state, "per_page": 50}
        result = _api_call(self.config, "GET", "/pulls", params=params)
        if not isinstance(result, list):
            return []
        for pr in result:
            pr["iid"] = pr.get("number")
            pr["source_branch"] = pr.get("head", {}).get("ref", "?")
            pr["target_branch"] = pr.get("base", {}).get("ref", "?")
            if "user" in pr:
                pr["author"] = {"name": pr["user"].get("login", "?")}
        return result

    def get_mr(self, mr_id: Any) -> dict:
        result = _api_call(self.config, "GET", f"/pulls/{mr_id}")
        if "error" not in result:
            result["iid"] = result.get("number")
        return result

    def comment_on_mr(self, mr_id: Any, body: str,
                      agent_id: str = "") -> dict:
        prefix = f"**🤖 {agent_id.upper()}**: " if agent_id else ""
        # GitHub PR comments go through the issues endpoint
        return _api_call(self.config, "POST",
                         f"/issues/{mr_id}/comments",
                         data={"body": prefix + body})

    def approve_mr(self, mr_id: Any) -> dict:
        return _api_call(self.config, "POST",
                         f"/pulls/{mr_id}/reviews",
                         data={"event": "APPROVE"})

    def merge_mr(self, mr_id: Any, squash: bool = False) -> dict:
        data = {"merge_method": "squash" if squash else "merge"}
        return _api_call(self.config, "PUT",
                         f"/pulls/{mr_id}/merge", data=data)

    def close_mr(self, mr_id: Any) -> dict:
        return _api_call(self.config, "PATCH",
                         f"/pulls/{mr_id}",
                         data={"state": "closed"})

    def get_mr_changes(self, mr_id: Any) -> dict:
        return _api_call(self.config, "GET", f"/pulls/{mr_id}/files")

    def get_open_mrs_md(self) -> str:
        mrs = self.list_mrs("opened")
        if not mrs:
            return "### 🔀 Open Pull Requests\n_(none)_"

        lines = [f"### 🔀 Open Pull Requests ({len(mrs)})\n"]
        for pr in mrs[:10]:
            iid = pr.get("number", "?")
            title = pr.get("title", "?")
            author = pr.get("author", {}).get("name", "?")
            source = pr.get("source_branch", "?")
            target = pr.get("target_branch", "?")
            lines.append(f"- **#{iid}** {title}")
            lines.append(f"  - `{source}` → `{target}` (by {author})")

        return "\n".join(lines)

    # ----- Backward-compatible aliases -----

    def create_story(self, story_id: str, title: str, description: str,
                     priority: str = "medium", assigned_to: Optional[str] = None) -> dict:
        result = super().create_story(story_id, title, description,
                                      priority, assigned_to)
        if result.get("number"):
            self._issue_cache[story_id] = result["number"]
        return result


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    config = GitHubConfig()
    if not config.is_configured:
        print("Set GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO")
        sys.exit(1)

    provider = GitHubProvider(config)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        provider.init()
        print("✅ GitHub labels initialized")
    elif cmd == "status":
        print(provider.get_board_summary_md())
    elif cmd == "test":
        result = provider.create_story(
            "TEST-001", "Test story", "This is a test", priority="low"
        )
        print(f"Created issue: {result}")
    else:
        print(f"Usage: python github.py [init|status|test]")
