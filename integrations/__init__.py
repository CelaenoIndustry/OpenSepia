#!/usr/bin/env python3
"""
AI Dev Team — Integration Dispatcher
Processes agent actions and maps them to the appropriate integrations.

Agents can define integration_actions in their output in addition to
files_to_write, which are invoked after files are written.
"""

import logging
from pathlib import Path
from typing import Optional

from .providers import detect_provider
from .git_client import GitClient, GitConfig, sync_workspace_to_repo
from .docker_client import DockerClient, DockerConfig
from .base import BoardProvider

logger = logging.getLogger(__name__)


class IntegrationDispatcher:
    """
    Central dispatcher for all integrations.
    Processes integration_actions from agent output.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.workspace_dir = base_dir / "workspace"

        # Initialize clients
        self.board: Optional[BoardProvider] = detect_provider()
        self.git = GitClient()
        self.docker = DockerClient()

    @property
    def active_integrations(self) -> list[str]:
        """Return the list of active integrations."""
        active: list[str] = []
        if self.board:
            active.append(self.board.name)
        if self.git.enabled:
            active.append("git")
        active.append("docker")  # Docker is always available inside LXC
        return active

    def get_context_for_agent(self, agent_id: str) -> str:
        """Return integration context relevant for the given agent."""
        parts = []

        # Board state — relevant for all agents
        if self.board:
            try:
                parts.append(self.board.get_board_summary_md())
            except Exception as e:
                logger.warning("Board summary failed: %s", e, exc_info=True)
                parts.append(f"(Board unavailable: {e})")

        # Open MR/PR — relevant for code review agents
        if self.board and agent_id in ("dev1", "dev2", "tester", "sec_analyst", "sec_engineer"):
            try:
                parts.append(self.board.get_open_mrs_md())
            except Exception as e:
                logger.warning("Open MRs/PRs fetch failed: %s", e, exc_info=True)
                parts.append(f"(MR/PR unavailable: {e})")

        # Git context — relevant for dev, devops, tester, security
        if self.git.enabled and agent_id in ("dev1", "dev2", "devops", "tester", "sec_analyst", "sec_engineer", "sec_pentester"):
            try:
                parts.append(self.git.get_git_context_md())
            except Exception as e:
                logger.warning("Git context failed: %s", e, exc_info=True)
                parts.append(f"(Git unavailable: {e})")

        # Docker context — relevant mainly for devops
        if agent_id == "devops":
            try:
                parts.append(self.docker.get_docker_context_md())
            except Exception as e:
                logger.warning("Docker context failed: %s", e, exc_info=True)
                parts.append(f"(Docker unavailable: {e})")

        if not parts:
            return "(No active integrations)"

        return "\n\n---\n\n".join(parts)

    # =========================================================================
    # Action processing
    # =========================================================================

    def process_actions(self, agent_id: str, actions: list[dict]) -> list[dict]:
        """
        Process a list of integration_actions from agent output.

        Action format:
        {
            "type": "docker_deploy",
            "params": { ... }
        }
        """
        results = []

        for action in actions:
            action_type = action.get("type", "")
            params = action.get("params", {})

            logger.info(f"Agent {agent_id}: action {action_type}")

            try:
                result = self._dispatch(agent_id, action_type, params)
                results.append({
                    "action": action_type,
                    "success": "error" not in result,
                    "result": result,
                })
            except Exception as e:
                logger.exception(f"Action {action_type} failed: {e}")
                results.append({
                    "action": action_type,
                    "success": False,
                    "error": str(e),
                })

        return results

    def _dispatch(self, agent_id: str, action_type: str, params: dict) -> dict:
        """Route the action to the correct integration."""

        # ---- Board actions (provider-agnostic) ----
        if action_type == "board_create_story":
            if self.board:
                return self.board.create_story(**params)
            return {"error": "Board provider is not configured"}

        elif action_type == "board_create_bug":
            if self.board:
                return self.board.create_bug(**params)
            return {"error": "Board provider is not configured"}

        elif action_type == "board_move_issue":
            if self.board:
                return self.board.update_issue_status(**params)
            return {"error": "Board provider is not configured"}

        elif action_type == "board_comment":
            issue_id = params.get("issue_iid")
            message = params.get("message", "")
            if self.board:
                return self.board.comment_on_issue(issue_id, agent_id, message)
            return {"error": "Board provider is not configured"}

        elif action_type == "board_close_issue":
            if self.board:
                return self.board.close_issue(params.get("issue_iid"))
            return {"error": "Not supported"}

        # ---- Git actions ----
        elif action_type == "git_commit_and_push":
            if not self.git.enabled:
                return {"error": "Git is not configured"}

            # First sync workspace -> repo
            if self.git.config.repo_path.exists():
                sync_workspace_to_repo(self.workspace_dir, self.git.config.repo_path)

            return self.git.commit_and_push(
                message=params.get("message", f"auto-commit by {agent_id}"),
                agent_role=agent_id,
                branch=params.get("branch"),
                paths=params.get("paths"),
            )

        elif action_type == "git_create_branch":
            if not self.git.enabled:
                return {"error": "Git is not configured"}
            self.git.create_branch(params.get("branch_name", ""))
            return {"success": True, "branch": params.get("branch_name")}

        elif action_type == "git_create_mr":
            if not self.board:
                return {"error": "Board provider is not configured for MR/PR"}
            return self.board.create_mr(
                source_branch=params.get("source_branch", ""),
                title=params.get("title", ""),
                description=params.get("description", ""),
                target_branch=params.get("target_branch", "main"),
            )

        # ---- MR/PR Review actions ----
        elif action_type == "mr_comment":
            if not self.board:
                return {"error": "Board provider is not configured"}
            return self.board.comment_on_mr(
                mr_id=params.get("mr_iid"),
                body=params.get("body", ""),
                agent_id=agent_id,
            )

        elif action_type == "mr_approve":
            if not self.board:
                return {"error": "Board provider is not configured"}
            return self.board.approve_mr(params.get("mr_iid"))

        elif action_type == "mr_merge":
            if not self.board:
                return {"error": "Board provider is not configured"}
            return self.board.merge_mr(
                mr_id=params.get("mr_iid"),
                squash=params.get("squash", False),
            )

        # ---- Docker actions ----
        elif action_type == "docker_build":
            return self.docker.build(
                path=params.get("path", "."),
                tag=params.get("tag"),
                dockerfile=params.get("dockerfile"),
                build_args=params.get("build_args"),
                no_cache=params.get("no_cache", False),
            )

        elif action_type == "docker_run":
            return self.docker.run(
                image=params.get("image", ""),
                name=params.get("name"),
                ports=params.get("ports"),
                volumes=params.get("volumes"),
                env=params.get("env"),
                network=params.get("network"),
                command=params.get("command"),
            )

        elif action_type == "docker_stop":
            return self.docker.stop(params.get("container", ""))

        elif action_type == "docker_restart":
            return self.docker.restart(params.get("container", ""))

        elif action_type == "docker_rm":
            return self.docker.rm(
                params.get("container", ""),
                force=params.get("force", False)
            )

        elif action_type == "docker_deploy":
            # Full deploy: build -> stop -> run
            return self.docker.deploy(
                image=params.get("image", ""),
                name=params.get("name", ""),
                tag=params.get("tag", "latest"),
                build_path=params.get("build_path"),
                ports=params.get("ports"),
                volumes=params.get("volumes"),
                env=params.get("env"),
            )

        elif action_type == "docker_pull":
            return self.docker.pull(params.get("image", ""))

        elif action_type == "docker_push":
            return self.docker.push(params.get("image", ""))

        # ---- Docker Compose actions ----
        elif action_type == "compose_up":
            cwd = Path(params.get("cwd", self.workspace_dir))
            return self.docker.compose_up(
                cwd=cwd,
                services=params.get("services"),
                detach=params.get("detach", True),
                build=params.get("build", False),
            )

        elif action_type == "compose_down":
            cwd = Path(params.get("cwd", self.workspace_dir))
            return self.docker.compose_down(
                cwd=cwd,
                volumes=params.get("volumes", False),
            )

        elif action_type == "compose_restart":
            cwd = Path(params.get("cwd", self.workspace_dir))
            return self.docker.compose_restart(
                cwd=cwd,
                services=params.get("services"),
            )

        else:
            return {"error": f"Unknown action: {action_type}"}


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    base_dir = Path(__file__).parent.parent
    dispatcher = IntegrationDispatcher(base_dir)

    logger.info("Active integrations: %s", dispatcher.active_integrations)
    logger.info("Context for devops agent:\n%s",
                dispatcher.get_context_for_agent("devops"))
