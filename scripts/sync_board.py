#!/usr/bin/env python3
"""
AI Dev Team — Board Sync
Synchronizes backlog.md and sprint.md with provider issues and labels.
Called after each cycle by the orchestrator.
"""

import os
import re
import sys
import json
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.logging_config import load_env
load_env()

from integrations.providers.gitlab import (
    GitLabProvider, GitLabConfig, _api_call,
)
from integrations.base import BOARD_LABELS, PRIORITY_LABELS

from integrations.logging_config import setup_logging
logger = setup_logging("sync_board")

BASE_DIR = Path(__file__).parent.parent
BOARD_DIR = BASE_DIR / "board"


def parse_backlog(backlog_path: Path) -> list[dict[str, Any]]:
    """Parse backlog.md and return a list of stories/bugs."""
    content = backlog_path.read_text(encoding="utf-8")
    items = []

    current_priority = "medium"
    # Map section headers to priorities
    priority_map = {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
    }

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect priority section
        for key, prio in priority_map.items():
            if key in line and line.startswith("##"):
                current_priority = prio
                break

        # Detect story/bug header: ### STORY-001: Title or ### BUG-001: Title
        match = re.match(r'^###\s+((?:STORY|BUG)-\d+):\s*(.+)', line)
        if match:
            item_id = match.group(1)
            title = match.group(2).strip()

            # Collect description lines until next ### or ## or ---
            desc_lines = []
            i += 1
            while i < len(lines):
                if lines[i].startswith("### ") or lines[i].startswith("## ") or lines[i].strip() == "---":
                    break
                desc_lines.append(lines[i])
                i += 1

            description = "\n".join(desc_lines).strip()

            # Extract status from description
            status = "todo"
            status_match = re.search(r'\*\*Status\*\*:\s*(.+)', description)
            if status_match:
                status = normalize_status(status_match.group(1))

            # Extract assigned to
            assigned = None
            assign_match = re.search(r'\*\*Assigned\*\*:\s*(.+)', description)
            if assign_match:
                assigned = assign_match.group(1).strip()

            items.append({
                "id": item_id,
                "title": title,
                "description": description,
                "priority": current_priority,
                "status": status,
                "assigned": assigned,
                "is_bug": item_id.startswith("BUG-"),
            })
            continue

        i += 1

    return items


def normalize_status(raw: str) -> str:
    """Normalize free-form English status to a standard value.

    Standard values: todo, in_progress, review, testing, done, blocked
    """
    s = raw.strip().lower()

    # Direct matches
    direct = {
        "todo": "todo",
        "in_progress": "in_progress",
        "in progress": "in_progress",
        "done": "done",
        "blocked": "blocked",
        "review": "review",
        "testing": "testing",
    }
    if s in direct:
        return direct[s]

    # Pattern matching for free-form statuses
    patterns = [
        ("in.progress", "in_progress"),
        ("review", "review"),
    ]
    for pattern, status in patterns:
        if pattern in s:
            return status

    # Handle "DONE (conditionally accepted)" etc — starts with known status word
    for key in direct:
        if s.startswith(key):
            return direct[key]

    return "todo"


def parse_sprint_statuses(sprint_path: Path) -> dict[str, str]:
    """Parse sprint.md and return a mapping of item_id -> status.

    Supports two formats:
    1) Sections ## TODO / ## IN PROGRESS with - [ ] STORY-XXX items
    2) Blocks ### STORY-XXX: with **Status**: value
    Strategy 1 has priority, strategy 2 fills in the missing ones.
    """
    content = sprint_path.read_text(encoding="utf-8")
    statuses = {}

    # --- Strategy 1: ## STATUS sections with checkbox items ---
    status_map = {
        "todo": "todo",
        "in progress": "in_progress",
        "in_progress": "in_progress",
        "done": "done",
        "blocked": "blocked",
        "review": "review",
        "testing": "testing",
    }

    current_status = None
    for line in content.split("\n"):
        stripped = line.strip().lower()
        # Detect status section (## TODO, ## IN PROGRESS, etc.)
        if stripped.startswith("## ") and not stripped.startswith("### "):
            matched = False
            for keyword, status in status_map.items():
                if keyword in stripped:
                    current_status = status
                    matched = True
                    break
            if not matched:
                current_status = None

        if current_status:
            if line.strip().startswith("- ["):
                refs = re.findall(r'((?:STORY|BUG)-\d+)', line)
                for ref in refs:
                    statuses[ref] = current_status

    # --- Strategy 2: ### STORY-XXX: blocks with **Status**: value ---
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        header_match = re.match(r'^###\s+((?:STORY|BUG)-\d+):', lines[i])
        if header_match:
            item_id = header_match.group(1)
            if item_id not in statuses:
                # Search following lines (max 15) for **Status**:
                for j in range(i + 1, min(i + 16, len(lines))):
                    if lines[j].startswith("### ") or lines[j].startswith("## "):
                        break
                    status_match = re.search(r'\*\*Status\*\*:\s*(.+)', lines[j])
                    if status_match:
                        statuses[item_id] = normalize_status(status_match.group(1))
                        break
        i += 1

    return statuses


def sync_to_gitlab(items: list[dict[str, Any]], sprint_statuses: dict[str, str], provider: GitLabProvider) -> tuple[int, int]:
    """Synchronize items to GitLab Issues."""
    config = provider.config

    # Load existing issues
    all_issues = provider.list_issues(state="opened")
    closed_issues = provider.list_issues(state="closed")
    all_issues.extend(closed_issues)

    # Build map: story_id -> issue
    issue_map = {}
    for issue in all_issues:
        # Extract story/bug ID from title: [STORY-001] or [BUG-001]
        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', issue.get("title", ""))
        if match:
            issue_map[match.group(1)] = issue

    created = 0
    updated = 0

    # Set of all status label names
    all_status_labels = set(BOARD_LABELS.values())

    for item in items:
        item_id = item["id"]
        # Override status from sprint.md if available
        status = sprint_statuses.get(item_id, item["status"])

        # Map to board label
        status_label = BOARD_LABELS.get(status, BOARD_LABELS["todo"])
        priority_label = PRIORITY_LABELS.get(item["priority"], PRIORITY_LABELS["medium"])

        labels = [status_label, priority_label]
        if item["is_bug"]:
            labels.append("type::bug")

        title_prefix = "🐛 " if item["is_bug"] else ""
        full_title = f"{title_prefix}[{item_id}] {item['title']}"

        if item_id in issue_map:
            # Update existing issue
            existing = issue_map[item_id]
            existing_labels = set(existing.get("labels", []))
            new_labels = set(labels)

            # Check if labels changed
            old_status = existing_labels & all_status_labels
            new_status = new_labels & all_status_labels

            if old_status != new_status or not new_labels.issubset(existing_labels):
                result = _api_call(
                    config, "PUT", f"/issues/{existing['iid']}",
                    data={"labels": ",".join(new_labels | (existing_labels - all_status_labels))},
                )
                if "error" not in result:
                    updated += 1
                    logger.info(f"  Updated #{existing['iid']} {item_id}: {old_status} -> {new_status}")

            # Reopen if moved back from done
            if status != "done" and existing.get("state") == "closed":
                _api_call(config, "PUT", f"/issues/{existing['iid']}",
                          data={"state_event": "reopen"})
                logger.info(f"  Reopened #{existing['iid']} {item_id}")

            # Close if done
            if status == "done" and existing.get("state") != "closed":
                _api_call(config, "PUT", f"/issues/{existing['iid']}",
                          data={"state_event": "close"})
                logger.info(f"  Closed #{existing['iid']} {item_id}")

        else:
            # Create new issue
            desc = f"**{item_id}**\n\n{item['description']}"
            if item.get("assigned"):
                desc += f"\n\n**Assigned**: {item['assigned']}"

            result = provider.create_issue(full_title, desc, labels=labels)
            if "error" not in result:
                created += 1
                logger.info(f"  Created #{result.get('iid')} {item_id}: {item['title']}")
            else:
                logger.error(f"  Failed to create {item_id}: {result}")

    # --- Sprint-only items (in sprint.md but not in backlog as ### block) ---
    backlog_ids = {item["id"] for item in items}
    for item_id, status in sprint_statuses.items():
        if item_id in backlog_ids:
            continue  # already processed in main loop

        if item_id not in issue_map:
            logger.warning(f"  Sprint-only {item_id} ({status}): no GitLab issue, skipping")
            continue

        existing = issue_map[item_id]
        status_label = BOARD_LABELS.get(status, BOARD_LABELS["todo"])
        existing_labels = set(existing.get("labels", []))
        old_status = existing_labels & all_status_labels
        new_status = {status_label}

        if old_status != new_status:
            new_labels = list((existing_labels - all_status_labels) | new_status)
            result = _api_call(config, "PUT", f"/issues/{existing['iid']}",
                               data={"labels": ",".join(new_labels)})
            if "error" not in result:
                updated += 1
                logger.info(f"  Updated sprint-only #{existing['iid']} {item_id}: {old_status} -> {new_status}")

        # Close if done
        if status == "done" and existing.get("state") != "closed":
            _api_call(config, "PUT", f"/issues/{existing['iid']}",
                      data={"state_event": "close"})
            logger.info(f"  Closed #{existing['iid']} {item_id}")

        # Reopen if moved back from done
        if status != "done" and existing.get("state") == "closed":
            _api_call(config, "PUT", f"/issues/{existing['iid']}",
                      data={"state_event": "reopen"})
            logger.info(f"  Reopened #{existing['iid']} {item_id}")

    # Export story_id -> issue_iid map to cache file
    cache_map = {}
    # Re-fetch issues so the map includes newly created ones
    all_fresh = provider.list_issues(state="opened")
    closed_fresh = provider.list_issues(state="closed")
    all_fresh.extend(closed_fresh)
    for issue in all_fresh:
        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', issue.get("title", ""))
        if match:
            cache_map[match.group(1)] = issue["iid"]

    if cache_map:
        cache_path = BOARD_DIR / ".gitlab_issue_map.json"
        try:
            cache_path.write_text(json.dumps(cache_map, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            logger.info(f"  Issue map cache: {len(cache_map)} entries -> {cache_path}")
        except Exception as e:
            logger.warning(f"  Issue map cache: write error: {e}")

    return created, updated


def main() -> None:
    config = GitLabConfig()
    if not config.is_configured:
        logger.warning("GitLab is not configured (GITLAB_URL/TOKEN/PROJECT_ID), skipping sync")
        return

    provider = GitLabProvider(config)
    logger.info("GitLab Board Sync...")

    backlog_path = BOARD_DIR / "backlog.md"
    sprint_path = BOARD_DIR / "sprint.md"

    if not backlog_path.exists():
        logger.warning("backlog.md does not exist")
        return

    # Parse
    items = parse_backlog(backlog_path)
    logger.info(f"  Backlog: {len(items)} items")

    sprint_statuses = {}
    if sprint_path.exists():
        sprint_statuses = parse_sprint_statuses(sprint_path)
        logger.info(f"  Sprint statuses: {sprint_statuses}")

    # Sync
    created, updated = sync_to_gitlab(items, sprint_statuses, provider)
    logger.info(f"  Done: {created} created, {updated} updated")


if __name__ == "__main__":
    main()
