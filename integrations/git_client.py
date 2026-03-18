#!/usr/bin/env python3
"""
AI Dev Team — Git Integration
Developer agent uses this to commit and push code.
DevOps agent manages infrastructure manifests.
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class GitConfig:
    def __init__(self) -> None:
        self.repo_url: str = os.getenv("GIT_REPO_URL", "")
        self.repo_path: Path = Path(os.getenv("GIT_REPO_PATH", "./repo"))
        self.user_name: str = os.getenv("GIT_USER_NAME", "AI Dev Team")
        self.user_email: str = os.getenv("GIT_USER_EMAIL", "ai-team@example.com")
        self.main_branch: str = os.getenv("GIT_MAIN_BRANCH", "") or "main"
        self.auto_push: bool = os.getenv("GIT_AUTO_PUSH", "true").lower() == "true"
        # SSH key or token for push
        self.ssh_key: str = os.getenv("GIT_SSH_KEY", "")
        # For HTTPS: https://oauth2:TOKEN@gitlab.com/group/project.git
        self.token: str = os.getenv("GIT_TOKEN", "")

        if not self.repo_url:
            logger.warning("GIT_REPO_URL is empty — git integration will be disabled")
        if not self.main_branch:
            self.main_branch = "main"
            logger.warning("GIT_MAIN_BRANCH is empty — defaulting to 'main'")

    @property
    def is_configured(self) -> bool:
        return bool(self.repo_url)

    @property
    def auth_repo_url(self) -> str:
        """URL with authentication for push."""
        if self.token and self.repo_url.startswith("https://"):
            # Insert token into URL
            url = self.repo_url.replace("https://", f"https://oauth2:{self.token}@")
            return url
        return self.repo_url


class GitClient:
    """Git operations for AI agents."""

    def __init__(self, config: Optional[GitConfig] = None) -> None:
        self.config = config or GitConfig()

    @property
    def enabled(self) -> bool:
        return self.config.is_configured

    def _run(self, *args: str, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        cwd = cwd or self.config.repo_path

        logger.debug(f"git {' '.join(args)} (cwd={cwd})")

        result = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=60,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": self.config.user_name,
                "GIT_AUTHOR_EMAIL": self.config.user_email,
                "GIT_COMMITTER_NAME": self.config.user_name,
                "GIT_COMMITTER_EMAIL": self.config.user_email,
            }
        )

        if check and result.returncode != 0:
            stderr = result.stderr
            if self.config.token and self.config.token in stderr:
                stderr = stderr.replace(self.config.token, "***")
            logger.error(f"git {args[0]} failed: {stderr}")

        return result

    # =========================================================================
    # Repo management
    # =========================================================================

    def clone_or_pull(self) -> bool:
        """Clone the repo or update the existing one."""
        if not self.enabled:
            logger.warning("Git is not configured")
            return False

        repo_path = self.config.repo_path

        if (repo_path / ".git").exists():
            # Pull
            logger.info(f"Pulling {repo_path}")
            self._run("fetch", "--all")
            self._run("reset", "--hard", f"origin/{self.config.main_branch}")
            return True
        else:
            # Clone
            logger.info(f"Cloning {self.config.repo_url} → {repo_path}")
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            result = self._run(
                "clone", self.config.auth_repo_url, str(repo_path),
                cwd=repo_path.parent, check=False
            )
            if result.returncode == 0:
                self._run("config", "user.name", self.config.user_name)
                self._run("config", "user.email", self.config.user_email)
                return True
            return False

    # =========================================================================
    # Branch operations
    # =========================================================================

    def create_branch(self, branch_name: str, from_branch: Optional[str] = None) -> bool:
        """Create and switch to a new branch."""
        from_branch = from_branch or self.config.main_branch

        # Update
        self._run("fetch", "origin")
        self._run("checkout", from_branch)
        self._run("pull", "origin", from_branch)

        # Create branch
        result = self._run("checkout", "-b", branch_name, check=False)
        if result.returncode != 0:
            # Branch already exists, switch to it
            self._run("checkout", branch_name)

        logger.info(f"Branch: {branch_name}")
        return True

    def current_branch(self) -> str:
        """Return the current branch."""
        result = self._run("branch", "--show-current")
        return result.stdout.strip()

    def switch_branch(self, branch_name: str) -> bool:
        """Switch to an existing branch."""
        result = self._run("checkout", branch_name, check=False)
        return result.returncode == 0

    # =========================================================================
    # Commit & Push
    # =========================================================================

    def stage_files(self, paths: Optional[list[str]] = None) -> bool:
        """Add files to staging."""
        if paths:
            for p in paths:
                self._run("add", str(p))
        else:
            self._run("add", "-A")
        return True

    def commit(self, message: str, agent_role: str = "system") -> bool:
        """Commit staged changes."""
        # Prefix commit message with agent role
        role_prefixes = {
            "dev": "feat",
            "devops": "infra",
            "tester": "test",
            "pm": "docs",
            "po": "docs",
        }
        prefix = role_prefixes.get(agent_role, "chore")

        full_message = f"{prefix}: {message}\n\nAuthor: AI-{agent_role.upper()}\nCycle: {datetime.now().isoformat()}"

        # Check if there is anything to commit
        status = self._run("status", "--porcelain")
        if not status.stdout.strip():
            logger.info("Nothing to commit")
            return False

        result = self._run("commit", "-m", full_message, check=False)
        if result.returncode == 0:
            logger.info(f"Commit: {prefix}: {message}")
            return True

        logger.warning(f"Commit failed: {result.stderr}")
        return False

    def push(self, branch: Optional[str] = None, force: bool = False) -> bool:
        """Push to remote."""
        if not self.config.auto_push:
            logger.info("Auto-push disabled, skipping")
            return True

        branch = branch or self.current_branch()
        args = ["push", "origin", branch]
        if force:
            args.insert(1, "--force-with-lease")

        # Set upstream
        args.extend(["--set-upstream"])

        result = self._run(*args, check=False)
        if result.returncode == 0:
            logger.info(f"Pushed: {branch}")
            return True

        logger.error(f"Push failed: {result.stderr}")
        return False

    def commit_and_push(self, message: str, agent_role: str = "system",
                        paths: Optional[list[str]] = None, branch: Optional[str] = None) -> dict:
        """Combination: stage + commit + push. Main method for agents."""
        result = {
            "staged": False,
            "committed": False,
            "pushed": False,
            "branch": "",
            "error": None,
        }

        try:
            # Switch to branch if specified
            if branch and branch != self.current_branch():
                self.create_branch(branch)
            result["branch"] = self.current_branch()

            # Stage
            self.stage_files(paths)
            result["staged"] = True

            # Commit
            committed = self.commit(message, agent_role)
            result["committed"] = committed

            # Push
            if committed:
                pushed = self.push()
                result["pushed"] = pushed

        except Exception as e:
            result["error"] = str(e)
            logger.exception(f"Git operation failed: {e}")

        return result

    # =========================================================================
    # Diff & Status (for agent context)
    # =========================================================================

    def get_status(self) -> str:
        """Return git status."""
        result = self._run("status", "--short")
        return result.stdout.strip()

    def get_diff(self, branch: Optional[str] = None) -> str:
        """Return diff against the main branch."""
        target = branch or self.config.main_branch
        result = self._run("diff", f"origin/{target}...HEAD", "--stat", check=False)
        return result.stdout.strip()

    def get_log(self, count: int = 10) -> str:
        """Return the last N commits."""
        result = self._run(
            "log", f"--oneline", f"-{count}",
            "--format=%h %s (%an, %ar)"
        )
        return result.stdout.strip()

    def get_git_context_md(self) -> str:
        """Return git context as Markdown for agents."""
        if not self.enabled:
            return "(Git integration is not active)"

        lines = ["## 🔀 Git Status\n"]
        lines.append(f"**Branch**: `{self.current_branch()}`")
        lines.append(f"**Remote**: `{self.config.repo_url}`\n")

        status = self.get_status()
        if status:
            lines.append("### Uncommitted changes")
            lines.append(f"```\n{status}\n```\n")

        log = self.get_log(5)
        if log:
            lines.append("### Recent commits")
            lines.append(f"```\n{log}\n```\n")

        return "\n".join(lines)


# =============================================================================
# Workspace -> repo synchronization
# =============================================================================
def sync_workspace_to_repo(workspace_dir: Path, repo_dir: Path,
                           src_subdir: str = "src"):
    """
    Copy files from workspace to the repo directory.
    This is called before committing so that the Developer can work in the
    workspace and then the code gets copied to the git repo.
    """
    import shutil

    src = workspace_dir
    dst = repo_dir

    if not src.exists():
        logger.warning(f"Workspace {src} does not exist")
        return

    # Copy relevant directories
    for subdir in ["src", "tests", "docs", "config"]:
        src_path = src / subdir
        dst_path = dst / subdir
        if src_path.exists():
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
            logger.info(f"Synced: {subdir}/ → repo")

    # Copy files in workspace root (Dockerfile, README, etc.)
    for f in src.iterdir():
        if f.is_file() and not f.name.startswith("."):
            dst_file = dst / f.name
            shutil.copy2(f, dst_file)
            logger.info(f"Synced: {f.name} → repo")


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    config = GitConfig()
    client = GitClient(config)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "clone":
        client.clone_or_pull()
    elif cmd == "status":
        print(client.get_git_context_md())
    elif cmd == "branch":
        name = sys.argv[2] if len(sys.argv) > 2 else f"feature/cycle-{datetime.now().strftime('%Y%m%d%H%M')}"
        client.create_branch(name)
    elif cmd == "commit":
        msg = sys.argv[2] if len(sys.argv) > 2 else "auto-commit"
        result = client.commit_and_push(msg, "dev")
        print(json.dumps(result, indent=2))
    elif cmd == "log":
        print(client.get_log())
    else:
        print("Usage: python git_client.py [clone|status|branch|commit|log]")
