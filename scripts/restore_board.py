#!/usr/bin/env python3
"""
AI Dev Team — Board Restore

Restores board state from local snapshots or from GitLab/GitHub issues.

Usage:
    python scripts/restore_board.py --from-snapshot     # restore from board/.snapshot/
    python scripts/restore_board.py --from-provider     # reconstruct from GitLab/GitHub issues
    python scripts/restore_board.py --check             # check board health (no changes)
"""

import sys
import re
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
BOARD_DIR = BASE_DIR / "board"
SNAPSHOT_DIR = BOARD_DIR / ".snapshot"

sys.path.insert(0, str(BASE_DIR))

from integrations.logging_config import load_env
load_env()

from integrations.logging_config import setup_logging
logger = setup_logging("restore_board")

CRITICAL_FILES = ["sprint.md", "backlog.md"]
IMPORTANT_FILES = ["project.md", "architecture.md", "decisions.md", "standup.md"]
INBOX_FILES = [
    "inbox/po.md", "inbox/pm.md", "inbox/dev1.md", "inbox/dev2.md",
    "inbox/devops.md", "inbox/tester.md", "inbox/sec_analyst.md",
    "inbox/sec_engineer.md", "inbox/sec_pentester.md",
]


def check_board_health() -> dict[str, bool | list[str]]:
    """Check the health of board files. Returns a report dict."""
    report = {"ok": True, "missing": [], "empty": [], "present": []}

    for f in CRITICAL_FILES + IMPORTANT_FILES:
        path = BOARD_DIR / f
        if not path.exists():
            report["missing"].append(f)
            report["ok"] = False
        elif path.stat().st_size == 0:
            report["empty"].append(f)
            report["ok"] = False
        else:
            report["present"].append(f)

    for f in INBOX_FILES:
        path = BOARD_DIR / f
        if not path.exists():
            report["missing"].append(f)
            # Inbox files can be missing (not critical)

    return report


def restore_from_snapshot() -> bool:
    """Restore board files from local .snapshot/ directory."""
    if not SNAPSHOT_DIR.exists():
        logger.error("No snapshot directory found at board/.snapshot/")
        logger.info("Snapshots are created automatically by the orchestrator before each cycle.")
        return False

    backups = list(SNAPSHOT_DIR.glob("*.bak"))
    if not backups:
        logger.error("No snapshot files found in board/.snapshot/")
        return False

    restored = 0
    for bak_file in backups:
        # sprint.md.bak -> sprint.md
        original_name = bak_file.name.replace(".bak", "")
        target = BOARD_DIR / original_name

        if not target.exists() or target.stat().st_size == 0:
            content = bak_file.read_text(encoding="utf-8")
            target.write_text(content, encoding="utf-8")
            restored += 1
            logger.info(f"  Restored: {original_name} ({len(content)} chars)")
        else:
            logger.info(f"  Skipped: {original_name} (already exists and non-empty)")

    logger.info(f"Restore complete: {restored} files restored from snapshot")
    return restored > 0


def restore_from_provider() -> bool:
    """Reconstruct board files from GitLab/GitHub issues."""
    try:
        from integrations.providers import detect_provider
        from integrations.base import BOARD_LABELS, PRIORITY_LABELS
    except ImportError as e:
        logger.error(f"Cannot import integrations: {e}")
        return False

    provider = detect_provider()
    if not provider or not provider.enabled:
        logger.error("No board provider configured (GitLab/GitHub)")
        logger.info("Set GITLAB_URL+GITLAB_TOKEN or GITHUB_TOKEN+GITHUB_REPO in config/.env")
        return False

    logger.info(f"Fetching issues from {provider.name}...")

    # Fetch all issues
    open_issues = provider.list_issues(state="opened")
    closed_issues = provider.list_issues(state="closed")
    all_issues = open_issues + closed_issues

    if not all_issues:
        logger.warning("No issues found on the provider. Cannot reconstruct board.")
        return False

    logger.info(f"  Found {len(all_issues)} issues ({len(open_issues)} open, {len(closed_issues)} closed)")

    # Reverse label maps for lookup
    status_from_label = {v: k for k, v in BOARD_LABELS.items()}
    priority_from_label = {v: k for k, v in PRIORITY_LABELS.items()}

    # Parse issues into stories
    stories = []
    for issue in all_issues:
        title = issue.get("title", "")
        labels = set(issue.get("labels", []))

        # Extract story/bug ID from title: [STORY-001] or [BUG-001]
        match = re.search(r'\[((?:STORY|BUG)-\d+)\]', title)
        if not match:
            continue

        story_id = match.group(1)
        story_title = re.sub(r'^\S*\s*\[(?:STORY|BUG)-\d+\]\s*', '', title).strip()

        # Determine status from labels
        status = "todo"
        for label in labels:
            if label in status_from_label:
                status = status_from_label[label]
                break
        # Override: closed issues are done
        if issue.get("state") == "closed":
            status = "done"

        # Determine priority from labels
        priority = "medium"
        for label in labels:
            if label in priority_from_label:
                priority = priority_from_label[label]
                break

        is_bug = story_id.startswith("BUG-")
        description = issue.get("description", "")

        stories.append({
            "id": story_id,
            "title": story_title,
            "description": description,
            "status": status,
            "priority": priority,
            "is_bug": is_bug,
        })

    if not stories:
        logger.warning("No STORY/BUG issues found. Cannot reconstruct board.")
        return False

    logger.info(f"  Parsed {len(stories)} stories/bugs")

    # --- Reconstruct backlog.md ---
    backlog_path = BOARD_DIR / "backlog.md"
    if not backlog_path.exists() or backlog_path.stat().st_size == 0:
        sections = {"critical": [], "high": [], "medium": [], "low": []}
        for s in stories:
            sections[s["priority"]].append(s)

        lines = ["# Backlog\n"]
        for prio in ["critical", "high", "medium", "low"]:
            if sections[prio]:
                lines.append(f"\n## {prio.upper()}\n")
                for s in sections[prio]:
                    prefix = "BUG" if s["is_bug"] else "STORY"
                    lines.append(f"### {s['id']}: {s['title']}")
                    lines.append(f"**Priority**: {s['priority'].upper()}")
                    lines.append(f"**Status**: {s['status'].upper()}")
                    if s["description"]:
                        # Take first 500 chars of description
                        desc = s["description"][:500].strip()
                        lines.append(f"\n{desc}")
                    lines.append("")

        backlog_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"  Reconstructed backlog.md ({len(stories)} stories)")
    else:
        logger.info(f"  Skipped backlog.md (already exists)")

    # --- Reconstruct sprint.md ---
    sprint_path = BOARD_DIR / "sprint.md"
    if not sprint_path.exists() or sprint_path.stat().st_size == 0:
        # Group active stories by status
        active = [s for s in stories if s["status"] != "done"]
        done = [s for s in stories if s["status"] == "done"]

        status_order = ["todo", "in_progress", "review", "testing", "blocked"]
        status_display = {
            "todo": "TODO",
            "in_progress": "IN PROGRESS",
            "review": "REVIEW",
            "testing": "TESTING",
            "blocked": "BLOCKED",
        }

        lines = ["# Sprint (reconstructed from provider)\n"]

        for status in status_order:
            items = [s for s in active if s["status"] == status]
            if items:
                lines.append(f"\n## {status_display[status]}\n")
                for s in items:
                    lines.append(f"- [ ] **{s['id']}**: {s['title']}")
                lines.append("")

        if done:
            lines.append("\n## DONE\n")
            for s in done[-10:]:  # Last 10 done items
                lines.append(f"- [x] **{s['id']}**: {s['title']}")
            lines.append("")

        sprint_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"  Reconstructed sprint.md ({len(active)} active, {len(done)} done)")
    else:
        logger.info(f"  Skipped sprint.md (already exists)")

    # --- Ensure inbox files exist ---
    inbox_dir = BOARD_DIR / "inbox"
    inbox_dir.mkdir(exist_ok=True)
    for inbox_file in INBOX_FILES:
        path = BOARD_DIR / inbox_file
        if not path.exists():
            path.write_text("", encoding="utf-8")

    logger.info("Restore from provider complete.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Dev Team — Board Restore")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="Check board health (no changes)")
    group.add_argument("--from-snapshot", action="store_true",
                       help="Restore from local board/.snapshot/ backups")
    group.add_argument("--from-provider", action="store_true",
                       help="Reconstruct from GitLab/GitHub issues")
    args = parser.parse_args()

    if args.check:
        report = check_board_health()
        print(f"\n{'=' * 50}")
        print(f"  Board Health Check")
        print(f"{'=' * 50}")
        if report["present"]:
            for f in report["present"]:
                print(f"  OK  {f}")
        if report["empty"]:
            for f in report["empty"]:
                print(f"  EMPTY  {f}")
        if report["missing"]:
            for f in report["missing"]:
                print(f"  MISSING  {f}")
        print(f"{'=' * 50}")
        if report["ok"]:
            print("  Status: HEALTHY")
        else:
            print("  Status: NEEDS REPAIR")
            print(f"\n  Fix options:")
            if SNAPSHOT_DIR.exists() and list(SNAPSHOT_DIR.glob("*.bak")):
                print(f"    python scripts/restore_board.py --from-snapshot")
            print(f"    python scripts/restore_board.py --from-provider")
        print()

    elif args.from_snapshot:
        print("Restoring board from local snapshot...")
        restore_from_snapshot()

    elif args.from_provider:
        print("Reconstructing board from GitLab/GitHub issues...")
        restore_from_provider()


if __name__ == "__main__":
    main()
