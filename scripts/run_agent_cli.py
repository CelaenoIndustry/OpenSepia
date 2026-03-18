#!/usr/bin/env python3
"""
AI Dev Team — Agent Runner (Claude Code CLI version)
Uses 'claude' CLI instead of API. Works with Pro/Max subscription.

Usage:
  python run_agent_cli.py --agent dev --verbose
  python run_agent_cli.py --all
"""

import os
import re
import sys
import json
import yaml
import time
import argparse
import subprocess
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

# Uses module-level logger, configured by caller
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.logging_config import load_env
load_env()

# =============================================================================
# Constants
# =============================================================================
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
BOARD_DIR = BASE_DIR / "board"
WORKSPACE_DIR = BASE_DIR / "workspace"
LOGS_DIR = BASE_DIR / "logs" / "runs"
STANDUP_FILE = BOARD_DIR / "standup.md"

MAX_STANDUP_CHARS = 2000
MAX_INBOX_CHARS = 1500
MAX_WORKSPACE_FILES_PER_DIR = 10
MAX_WORKSPACE_SUBDIRS = 5
AGENT_TIMEOUT_SECONDS = 900
MAX_COMMENT_CONTEXT_CHARS = 6000


# =============================================================================
# Helper functions
# =============================================================================
def load_config() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load agent and project configuration."""
    with open(CONFIG_DIR / "agents.yaml", "r") as f:
        agents_config = yaml.safe_load(f)
    with open(CONFIG_DIR / "project.yaml", "r") as f:
        project_config = yaml.safe_load(f)
    return agents_config, project_config


def read_file_safe(path: Path) -> str:
    """Safely read a file, return empty string if it does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"[READ ERROR: {e}]"


def write_file(path: Path, content: str) -> None:
    """Write to a file, create directories if they do not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def archive_inbox(agent_id: str, content: str) -> None:
    """Archive processed inbox."""
    if not content.strip():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = BOARD_DIR / "archive" / agent_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{timestamp}.md"
    write_file(archive_path, content)


def get_workspace_tree(max_depth: int = 2) -> str:
    """Return workspace file tree (truncated to save tokens)."""
    result = []
    workspace = WORKSPACE_DIR
    if not workspace.exists():
        return "(workspace is empty)"

    def walk(path: Path, depth: int, prefix: str = ""):
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file() and not e.name.startswith(".")]

        for f in files[:MAX_WORKSPACE_FILES_PER_DIR]:
            result.append(f"{prefix}{f.name}")
        if len(files) > MAX_WORKSPACE_FILES_PER_DIR:
            result.append(f"{prefix}... and {len(files)-MAX_WORKSPACE_FILES_PER_DIR} more")
        for d in dirs[:MAX_WORKSPACE_SUBDIRS]:
            if d.name in ("node_modules", "__pycache__", ".git", "venv"):
                continue
            result.append(f"{prefix}{d.name}/")
            walk(d, depth + 1, prefix + "  ")

    walk(workspace, 0)
    return "\n".join(result) if result else "(workspace is empty)"


def initialize_standup_file(sprint_num: int, cycle: int) -> None:
    """
    Initialize standup file for a new cycle.
    Archive old standup, keep last cycle as context.
    FIX: Removes nested <details> blocks to prevent accumulation.
    """
    old_content = read_file_safe(STANDUP_FILE)

    if old_content.strip():
        # Archive COMPLETE old standup
        archive_dir = BOARD_DIR / "archive" / "standup"
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        write_file(archive_dir / f"s{sprint_num}_c{cycle - 1}_{timestamp}.md", old_content)

        # Keep last cycle as context — WITHOUT nested <details>!
        # Cut off old <details> blocks
        details_pos = old_content.find("<details>")
        if details_pos > 0:
            clean_content = old_content[:details_pos].strip()
        else:
            clean_content = old_content.strip()

        if len(clean_content) > MAX_INBOX_CHARS:
            clean_content = clean_content[:MAX_INBOX_CHARS] + "\n_(truncated)_"

        prev_section = f"\n\n<details><summary>Previous cycle</summary>\n\n{clean_content}\n</details>\n"
    else:
        prev_section = ""

    header = f"# Standup — Sprint {sprint_num}, Cycle {cycle}\n"
    write_file(STANDUP_FILE, header + prev_section + "\n")


# =============================================================================
# Building agent context (token-efficient version)
# =============================================================================
def build_agent_context(agent_id: str, agents_config: dict, project_config: dict) -> str:
    """
    Build complete context for an agent.
    TOKEN-EFFICIENT VERSION - fewer tokens for Pro plan.
    """
    agent = agents_config["agents"][agent_id]
    sprint_cfg = project_config.get("sprint", {})

    # Load board files
    project_md = read_file_safe(BOARD_DIR / "project.md")
    sprint_md = read_file_safe(BOARD_DIR / "sprint.md")
    backlog_md = read_file_safe(BOARD_DIR / "backlog.md")

    # Load standup (current cycle) — only current, not nested <details>
    standup_content = read_file_safe(STANDUP_FILE)
    # Cut off nested <details> blocks (old cycles)
    details_pos = standup_content.find("<details>")
    if details_pos > 0:
        standup_content = standup_content[:details_pos].strip()
    if len(standup_content) > MAX_STANDUP_CHARS:
        standup_content = standup_content[:MAX_STANDUP_CHARS] + "\n_(truncated)_"

    # Load this agent's inbox
    inbox_path = BOARD_DIR / "inbox" / f"{agent_id}.md"
    inbox_content = read_file_safe(inbox_path)

    # Workspace tree (truncated)
    workspace_tree = get_workspace_tree()

    # Metadata
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cycle = sprint_cfg.get("current_cycle", 0)
    sprint_num = sprint_cfg.get("current_sprint", 1)

    # SYSTEM PROMPT
    system_prompt = agent["system_prompt"]

    # Provider comments (READ path)
    provider_section = ""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from integrations.providers import detect_provider
        from scripts.sync_comments import get_active_story_ids, fetch_comments_for_context
        gl_client = detect_provider()
        if gl_client and gl_client.enabled:
            active_ids = get_active_story_ids(BOARD_DIR / "sprint.md", BOARD_DIR / "backlog.md")
            comments_md = fetch_comments_for_context(active_ids, gl_client, max_chars=MAX_COMMENT_CONTEXT_CHARS)
            if comments_md:
                provider_section = f"\n## Issue Discussions (from {gl_client.name})\n{comments_md}"
    except Exception as e:
        logger.debug(f"Provider comments unavailable: {e}")

    # Communication rules
    comm_rules = agents_config["global"].get("communication_rules", "")

    context = f"""{system_prompt}

---
# CURRENT STATE

Time: {now} | Sprint: {sprint_num} | Cycle: {cycle}

## Project
{project_md[:2000] if project_md else "(empty)"}

## Sprint (COMPLETE)
{sprint_md if sprint_md else "(none)"}

## Backlog (truncated)
{backlog_md[:4000] if backlog_md else "(empty)"}

## Standup (current cycle)
{standup_content if standup_content.strip() else "(empty so far)"}

## Your Inbox ({agent_id})
{inbox_content if inbox_content else "(no messages)"}
{provider_section}

## Workspace
```
{workspace_tree}
```

---
# INSTRUCTIONS

{agents_config["global"].get("standup_instruction", "")}

{comm_rules}

Do your work. At the end you MUST return:

```
---FILES---
path: board/sprint.md
content:
(file content)
---
path: board/inbox/dev1.md
action: append
content:
## Message from {agent['name']}
(message text)
---END---
```

Rules:
- Each file starts with "path:" and "content:"
- To append to the end use "action: append"
- Only write relevant files
- Inbox files: po.md, pm.md, dev1.md, dev2.md, devops.md, tester.md, sec_analyst.md, sec_engineer.md, sec_pentester.md
- NEVER use dev.md, qa.md, security.md — these files do not exist!
"""

    return context


# =============================================================================
# Calling Claude Code CLI
# =============================================================================
def call_claude_code(prompt: str, verbose: bool = False) -> str:
    """
    Call Claude Code CLI with a prompt.
    Returns the response as a string.
    """
    try:
        # Call claude CLI
        # --print = just print the response, no interactive mode
        cmd = [
            "claude",
            "--print",              # Non-interactive, print response
            "--allowedTools", "Bash,Edit,Write,Read,Glob,Grep",  # Agents need full access
        ]

        if verbose:
            print(f"    Calling Claude Code CLI...")

        # Unset CLAUDECODE — otherwise claude CLI refuses to run ("nested session")
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        # Send prompt via stdin
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECONDS,
            cwd=str(BASE_DIR),  # Working directory
            env=env,
        )

        if result.returncode != 0:
            logger.error(f"Claude Code error: {result.stderr}")
            return f"ERROR: {result.stderr}"

        return result.stdout

    except subprocess.TimeoutExpired:
        logger.error("Claude Code timeout (%d s)", AGENT_TIMEOUT_SECONDS)
        return "ERROR: Timeout"
    except FileNotFoundError:
        logger.error("Claude Code CLI is not installed. Run: npm install -g @anthropic-ai/claude-code")
        return "ERROR: Claude Code CLI is not installed"
    except Exception as e:
        logger.error(f"Claude Code error: {e}")
        return f"ERROR: {e}"


def call_agent(agent_id: str, agents_config: dict, project_config: dict,
               verbose: bool = False) -> dict:
    """
    Call an agent via Claude Code CLI.
    """
    agent = agents_config["agents"][agent_id]

    # Build context
    context = build_agent_context(agent_id, agents_config, project_config)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  {agent['color']} {agent['name']}")
        print(f"{'='*60}")
        print(f"  Context: {len(context)} chars")

    # Call Claude Code
    response = call_claude_code(context, verbose)

    if verbose:
        print(f"  Response: {len(response)} chars")

    return {
        "agent_id": agent_id,
        "agent_name": agent["name"],
        "response": response,
        "timestamp": datetime.now().isoformat(),
        "context_size": len(context),
        "response_size": len(response),
    }


# =============================================================================
# Processing agent output (simpler parser)
# =============================================================================
def parse_files_section(response: str) -> list[dict[str, str]]:
    """
    Parse ---FILES--- section from the response.
    Simpler format than YAML for more reliable parsing.
    """
    files = []

    if "---FILES---" not in response:
        # Try alternative format
        if "---OUTPUT---" in response:
            return parse_output_yaml(response)
        return files

    # Extract FILES section
    start = response.find("---FILES---")
    end = response.find("---END---", start)
    if end == -1:
        end = len(response)

    section = response[start + len("---FILES---"):end]

    # Parse individual files
    current_file = None
    current_content = []
    in_content = False

    for line in section.split("\n"):
        stripped = line.strip()

        if stripped.startswith("path:"):
            # Save previous file
            if current_file:
                current_file["content"] = "\n".join(current_content).strip()
                if current_file["content"]:
                    files.append(current_file)

            # New file
            current_file = {
                "path": stripped[5:].strip(),
                "action": "overwrite",
            }
            current_content = []
            in_content = False

        elif stripped.startswith("action:"):
            if current_file:
                current_file["action"] = stripped[7:].strip()

        elif stripped.startswith("content:"):
            in_content = True
            # If content is on the same line
            rest = stripped[8:].strip()
            if rest:
                current_content.append(rest)

        elif stripped == "---" and current_file:
            # End of file
            current_file["content"] = "\n".join(current_content).strip()
            if current_file["content"]:
                files.append(current_file)
            current_file = None
            current_content = []
            in_content = False

        elif in_content and current_file:
            current_content.append(line)

    # Last file
    if current_file:
        current_file["content"] = "\n".join(current_content).strip()
        if current_file["content"]:
            files.append(current_file)

    return files


def parse_output_yaml(response: str) -> list[dict[str, str]]:
    """Fallback parser for YAML format."""
    files = []
    if "---OUTPUT---" not in response:
        return files

    try:
        section = response.split("---OUTPUT---", 1)[1]
        if "---END---" in section:
            section = section.split("---END---", 1)[0]

        # Try YAML
        data = yaml.safe_load(section)
        if data and "files_to_write" in data:
            return data["files_to_write"]
    except Exception:
        pass

    return files


def parse_standup_from_response(response: str, agent_id: str,
                                agent_name: str, agent_color: str) -> str:
    """
    Fallback parser — looks for ---STANDUP--- section in agent response.
    Returns formatted standup text or empty string.
    """
    if "---STANDUP---" not in response:
        return ""

    start = response.find("---STANDUP---") + len("---STANDUP---")
    end = response.find("---", start)
    if end == -1:
        end = min(start + 500, len(response))

    raw = response[start:end].strip()
    if not raw:
        return ""

    # Max 500 characters
    if len(raw) > 500:
        raw = raw[:497] + "..."

    return f"## {agent_color} {agent_name}\n{raw}\n"


def apply_output(agent_id: str, result: dict, agents_config: dict,
                 verbose: bool = False) -> int:
    """
    Apply agent output — write files.
    """
    files = parse_files_section(result["response"])

    # Warning: CLI version does not support integration_actions
    if "integration_actions" in result["response"]:
        logger.warning(f"{agent_id}: Response contains integration_actions, which the CLI version does not support. Use the API version (run_agent.py) for full integration support.")

    if verbose:
        print(f"  Files to write: {len(files)}")

    written = 0
    for file_info in files:
        path = file_info.get("path", "")
        content = file_info.get("content", "")
        action = file_info.get("action", "overwrite")

        if not path or not content:
            continue

        # Security check
        full_path = (BASE_DIR / path).resolve()
        if not str(full_path).startswith(str(BASE_DIR.resolve())):
            logger.warning(f"SECURITY: {agent_id} attempted to write outside the project: {path}")
            continue

        if verbose:
            icon = "📝" if action == "overwrite" else "📎"
            print(f"    {icon} {path}")

        if action == "append":
            existing = read_file_safe(full_path)
            write_file(full_path, existing + "\n" + content)
        else:
            write_file(full_path, content)

        written += 1

    # Standup fallback: if agent did not write to board/standup.md via FILES
    standup_written = any(
        "board/standup.md" in f.get("path", "") for f in files
    )
    if not standup_written:
        agent = agents_config["agents"].get(agent_id, {})
        fallback = parse_standup_from_response(
            result["response"],
            agent_id,
            agent.get("name", agent_id),
            agent.get("color", "💬"),
        )
        if fallback:
            existing = read_file_safe(STANDUP_FILE)
            write_file(STANDUP_FILE, existing + "\n" + fallback)
            if verbose:
                print(f"    📋 Standup (fallback) written")

    # Provider comments (WRITE path)
    try:
        from integrations.providers import detect_provider
        from scripts.sync_comments import post_agent_messages_to_provider, reset_mr_cache
        gl_client = detect_provider()
        if gl_client and gl_client.enabled:
            reset_mr_cache()  # Fresh MR list for each agent
            posted = post_agent_messages_to_provider(agent_id, files, gl_client)
            if posted and verbose:
                print(f"    💬 Provider: {posted} comments sent")
    except Exception as e:
        logger.warning(f"Provider comments: {e}")

    # Archive and clear inbox
    inbox_path = BOARD_DIR / "inbox" / f"{agent_id}.md"
    inbox_content = read_file_safe(inbox_path)
    if inbox_content.strip():
        archive_inbox(agent_id, inbox_content)
        write_file(inbox_path, "")

    return written


# =============================================================================
# Logging
# =============================================================================
def log_run(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Log run results."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_entry = {
        "timestamp": timestamp,
        "method": "claude-code-cli",
        "agents": [
            {
                "agent": r["agent_name"],
                "context_chars": r.get("context_size", 0),
                "response_chars": r.get("response_size", 0),
                **({"error": r["error"]} if r.get("error") else {}),
            }
            for r in results
        ],
    }

    # Write log
    log_path = LOGS_DIR / f"{timestamp}.json"
    with open(log_path, "w") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)

    # Symlink to latest
    latest = LOGS_DIR / "latest.json"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(log_path.name)

    return log_entry


# =============================================================================
# Sprint sync
# =============================================================================
def sync_sprint_from_board(project_config: dict[str, Any]) -> None:
    """
    Synchronize sprint number from board/sprint.md to project.yaml.
    Agents can advance the sprint earlier than cycle 10 —
    this function ensures project.yaml is always up to date.
    """
    sprint_md = read_file_safe(BOARD_DIR / "sprint.md")
    if not sprint_md:
        return

    # Find the highest sprint number in the file (agents may have multiple sprints)
    all_sprints = re.findall(r"#\s*Sprint\s+(\d+)", sprint_md)
    if not all_sprints:
        return

    board_sprint = max(int(s) for s in all_sprints)
    sprint_cfg = project_config.get("sprint", {})
    yaml_sprint = sprint_cfg.get("current_sprint", 1)

    if board_sprint != yaml_sprint:
        sprint_cfg["current_sprint"] = board_sprint
        # If agents advanced the sprint forward, reset cycle to 1
        if board_sprint > yaml_sprint:
            sprint_cfg["current_cycle"] = 1
            print(f"   🔄 Sprint sync: {yaml_sprint} -> {board_sprint} (cycle reset to 1)")
        else:
            print(f"   🔄 Sprint sync: {yaml_sprint} -> {board_sprint}")
        project_config["sprint"] = sprint_cfg
        with open(CONFIG_DIR / "project.yaml", "w") as f:
            yaml.dump(project_config, f, default_flow_style=False, allow_unicode=True)


# =============================================================================
# Main
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="AI Dev Team — Agent Runner (Claude Code CLI)")
    parser.add_argument("--agent", "-a", type=str, default=None,
                        help="Run a specific agent (po, pm, dev1, dev2, devops, tester, sec_analyst, sec_engineer, sec_pentester)")
    parser.add_argument("--all", action="store_true",
                        help="Run all agents (9) in order")
    parser.add_argument("--minimal", action="store_true",
                        help="Minimal mode: only PO, Dev1, Tester (3 agents)")
    parser.add_argument("--dev-team", action="store_true",
                        help="Dev team: PO, PM, Dev1, Dev2, DevOps, Tester (6 agents)")
    parser.add_argument("--security", action="store_true",
                        help="Security team only: Analyst, Engineer, Pentester (3 agents)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only display context, do not call Claude")
    parser.add_argument("--no-increment", action="store_true",
                        help="Do not increment cycle number (for retrospective)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # Load configuration
    agents_config, project_config = load_config()

    # Determine agents to run
    if args.agent:
        agent_ids = [args.agent]
    elif args.minimal:
        agent_ids = agents_config["global"].get("minimal_order", ["po", "dev1", "tester"])
    elif args.dev_team:
        agent_ids = agents_config["global"].get("dev_team_order", ["po", "pm", "dev1", "dev2", "devops", "tester"])
    elif args.security:
        agent_ids = agents_config["global"].get("security_order", ["sec_analyst", "sec_engineer", "sec_pentester"])
    elif args.all:
        agent_ids = agents_config["global"]["execution_order"]
    else:
        parser.print_help()
        print("\n💡 Modes:")
        print("   --minimal    3 agents (PO, Dev1, Tester)")
        print("   --dev-team   6 agents (core dev team)")
        print("   --security   3 agents (security team)")
        print("   --all        9 agents (all)")
        sys.exit(1)

    # Validation
    for aid in agent_ids:
        if aid not in agents_config["agents"]:
            print(f"ERROR: Unknown agent '{aid}'")
            sys.exit(1)

    # Increment cycle (unless --no-increment or --dry-run)
    sprint_cfg = project_config.get("sprint", {})
    if args.no_increment or args.dry_run:
        cycle = sprint_cfg.get("current_cycle", 0)
    else:
        cycle = sprint_cfg.get("current_cycle", 0) + 1
        sprint_cfg["current_cycle"] = cycle
        with open(CONFIG_DIR / "project.yaml", "w") as f:
            yaml.dump(project_config, f, default_flow_style=False, allow_unicode=True)

    sprint_num = sprint_cfg.get("current_sprint", 1)

    # Initialize standup file for new cycle (not during dry-run!)
    if not args.dry_run:
        initialize_standup_file(sprint_num, cycle)

    print(f"\n🤖 AI Dev Team — Cycle {cycle}")
    print(f"   Method: Claude Code CLI")
    print(f"   Agents: {', '.join(agent_ids)}")
    print(f"{'─'*50}")

    # Dry run?
    if args.dry_run:
        for aid in agent_ids:
            ctx = build_agent_context(aid, agents_config, project_config)
            print(f"\n--- {aid} ({len(ctx)} chars) ---")
            print(ctx[:1500] + "..." if len(ctx) > 1500 else ctx)
        return

    # Run agents
    results = []
    MAX_RETRIES = 1
    RETRY_DELAY = 30  # seconds

    for i, aid in enumerate(agent_ids):
        agent_name = agents_config["agents"][aid]["name"]
        agent_color = agents_config["agents"][aid]["color"]

        print(f"\n{agent_color} [{i+1}/{len(agent_ids)}] {agent_name}...")

        success = False
        last_error = None

        for attempt in range(1 + MAX_RETRIES):
            try:
                result = call_agent(aid, agents_config, project_config, verbose=args.verbose)

                if "ERROR" in result["response"]:
                    last_error = result["response"][:100]
                    if attempt < MAX_RETRIES:
                        print(f"   ⚠️  {last_error} — retrying in {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                        continue
                    else:
                        print(f"   ❌ {last_error} (after {attempt + 1} attempts)")
                        # Log error to results
                        results.append({
                            "agent_id": aid,
                            "agent_name": agent_name,
                            "response": result["response"],
                            "timestamp": datetime.now().isoformat(),
                            "context_size": result.get("context_size", 0),
                            "response_size": result.get("response_size", 0),
                            "error": last_error,
                        })
                        # Archive inbox even on agent error
                        inbox_path = BOARD_DIR / "inbox" / f"{aid}.md"
                        inbox_content = read_file_safe(inbox_path)
                        if inbox_content.strip():
                            archive_inbox(aid, inbox_content)
                            write_file(inbox_path, "")
                else:
                    if attempt > 0:
                        print(f"   🔄 Retry successful (attempt {attempt + 1})")
                    files_written = apply_output(aid, result, agents_config, verbose=args.verbose)
                    results.append(result)
                    print(f"   ✅ Done — {files_written} files")
                    success = True

                break  # Success or final error — end retry

            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    print(f"   ⚠️  Error: {e} — retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"   ❌ Error: {e} (after {attempt + 1} attempts)")
                    logger.exception(f"Error for {aid}")
                    results.append({
                        "agent_id": aid,
                        "agent_name": agent_name,
                        "response": "",
                        "timestamp": datetime.now().isoformat(),
                        "context_size": 0,
                        "response_size": 0,
                        "error": last_error,
                    })
                    # Archive inbox even on error
                    inbox_path = BOARD_DIR / "inbox" / f"{aid}.md"
                    inbox_content = read_file_safe(inbox_path)
                    if inbox_content.strip():
                        archive_inbox(aid, inbox_content)
                        write_file(inbox_path, "")

    # Sync sprint number from board/sprint.md -> project.yaml
    # (agents can advance the sprint earlier than cycle 10)
    sync_sprint_from_board(project_config)

    # Logging
    if results:
        log = log_run(results)
        ok_count = sum(1 for r in results if not r.get("error"))
        err_count = sum(1 for r in results if r.get("error"))
        print(f"\n{'─'*50}")
        print(f"✅ Cycle {cycle} completed")
        print(f"   Successful agents: {ok_count}/{len(agent_ids)}")
        if err_count:
            failed = [r["agent_name"] for r in results if r.get("error")]
            print(f"   ❌ Failed (after retry): {', '.join(failed)}")


if __name__ == "__main__":
    main()
