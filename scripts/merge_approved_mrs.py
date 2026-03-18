#!/usr/bin/env python3
"""
AI Dev Team — Auto-merge approved MRs + cleanup of stale branches.

After completing an agent cycle:
1. Merges approved MRs (ai-team/* branches)
2. Closes stale MRs (older than 2 days without approvals)
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.providers.gitlab import GitLabProvider, GitLabConfig, _api_call
from integrations.logging_config import setup_logging

logger = setup_logging("merge_approved_mrs")

# MRs older than this many days without approvals will be closed
STALE_DAYS = 2


def _parse_gitlab_date(date_str: str) -> datetime:
    """Parse a GitLab ISO 8601 date."""
    # GitLab returns format: 2025-01-15T10:30:00.000Z or 2025-01-15T10:30:00.000+00:00
    date_str = date_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _is_our_branch(mr: dict) -> bool:
    """Filter only ai-team/ branches (our MRs, not manual ones)."""
    source = mr.get("source_branch", "")
    return source.startswith("ai-team/")


def _parse_cycle_number(branch_name: str) -> int:
    """Extract cycle number from branch name (ai-team/sprint-X-cycle-Y -> Y)."""
    # Format: ai-team/sprint-3-cycle-10
    try:
        return int(branch_name.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def merge_approved_mrs(client: GitLabProvider) -> tuple[int, int]:
    """
    Merge approved MRs and close stale ones.

    Strategy: the newest cycle gets merged, older ones are closed as superseded
    (each cycle contains the complete workspace state, so the newest = the most complete).

    Returns:
        (merged_count, closed_count)
    """
    if not client.enabled:
        logger.warning("GitLab is not configured — skipping auto-merge")
        return 0, 0

    mrs = client.list_mrs("opened")
    if not mrs:
        logger.info("No open MRs")
        return 0, 0

    # Filter only our ai-team/ branches
    our_mrs = [mr for mr in mrs if _is_our_branch(mr)]
    if not our_mrs:
        logger.info("No ai-team/ MRs to process")
        return 0, 0

    # Sort by cycle number — newest first
    our_mrs.sort(key=lambda m: _parse_cycle_number(m.get("source_branch", "")), reverse=True)

    merged = 0
    closed = 0
    newest_merged = False
    now = datetime.now(timezone.utc)

    for mr in our_mrs:
        iid = mr.get("iid")
        title = mr.get("title", "?")
        branch = mr.get("source_branch", "?")

        # Get MR details
        detail = client.get_mr(iid)
        if "error" in detail:
            logger.warning(f"MR !{iid}: cannot get details — {detail}")
            continue

        merge_status = detail.get("detailed_merge_status", detail.get("merge_status", ""))
        created_at = _parse_gitlab_date(detail.get("created_at", ""))
        age = now - created_at

        # Approvals: basic detail does not return approval data on free tier,
        # we need to call /approvals endpoint separately
        approvals = _api_call(client.config, "GET", f"/merge_requests/{iid}/approvals")
        is_approved = approvals.get("approved", False)

        can_merge = merge_status in ("can_be_merged", "mergeable")

        # --- Newest MR: merge if approved ---
        if not newest_merged and can_merge and is_approved:
            logger.info(f"MR !{iid} '{title}' ({branch}) — merging (newest, approved)")
            result = client.merge_mr(iid, squash=False)
            if "error" not in result:
                merged += 1
                newest_merged = True
                logger.info(f"MR !{iid} successfully merged")
            else:
                logger.warning(f"MR !{iid} merge failed: {result}")
            continue

        # --- Older MR after successful merge of newest: close as superseded ---
        if newest_merged:
            logger.info(f"MR !{iid} '{title}' ({branch}) — closing (superseded by newer cycle)")
            client.comment_mr(
                iid,
                "Automatically closed — a newer cycle was merged, this MR is superseded.",
                agent_id="orchestrator",
            )
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
                logger.info(f"MR !{iid} closed")
            else:
                logger.warning(f"MR !{iid} close failed: {result}")
            continue

        # --- Conflict cleanup: approved MR with conflicts — close ---
        # Next cycle will create a new MR from clean main
        if not can_merge and is_approved:
            logger.info(f"MR !{iid} '{title}' ({branch}) — closing (approved but {merge_status}, next cycle will create a new one)")
            client.comment_mr(
                iid,
                f"Automatically closed — MR has conflicts ({merge_status}). Next cycle will create a new MR from current main.",
                agent_id="orchestrator",
            )
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
                logger.info(f"MR !{iid} closed")
            else:
                logger.warning(f"MR !{iid} close failed: {result}")
            continue

        # --- Stale MR cleanup ---
        if age > timedelta(days=STALE_DAYS) and not is_approved:
            logger.info(f"MR !{iid} '{title}' — closing (stale: {age.days}d, no approvals)")
            client.comment_mr(
                iid,
                f"Automatically closed — MR is older than {STALE_DAYS} days without approvals.",
                agent_id="orchestrator",
            )
            result = client.close_mr(iid)
            if "error" not in result:
                closed += 1
                logger.info(f"MR !{iid} closed")
            else:
                logger.warning(f"MR !{iid} close failed: {result}")
            continue

        logger.info(
            f"MR !{iid} '{title}' — skipped "
            f"(merge_status={merge_status}, approved={is_approved}, age={age.days}d)"
        )

    return merged, closed


if __name__ == "__main__":
    config = GitLabConfig()
    if not config.is_configured:
        print("GitLab is not configured (GITLAB_URL, GITLAB_TOKEN, GITLAB_PROJECT_ID)")
        sys.exit(1)

    client = GitLabProvider(config)
    merged, closed = merge_approved_mrs(client)
    print(f"Done: {merged} MRs merged, {closed} MRs closed")
