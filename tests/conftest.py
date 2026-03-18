"""Shared fixtures for AI Dev Team tests."""

import pytest
from pathlib import Path


@pytest.fixture
def temp_board_dir(tmp_path):
    """Create a temporary board directory with template files."""
    board = tmp_path / "board"
    board.mkdir()

    # Critical files
    (board / "sprint.md").write_text("# Sprint\n\n## TODO\n- [ ] STORY-001: Test story\n", encoding="utf-8")
    (board / "backlog.md").write_text("# Backlog\n\n## MEDIUM\n\n### STORY-001: Test story\n**Status**: todo\n", encoding="utf-8")

    # Important files
    (board / "project.md").write_text("# Project\nTest project\n", encoding="utf-8")
    (board / "architecture.md").write_text("# Architecture\nTest arch\n", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (board / "standup.md").write_text("# Standup\n", encoding="utf-8")

    # Inbox directory
    inbox = board / "inbox"
    inbox.mkdir()
    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester",
                   "sec_analyst", "sec_engineer", "sec_pentester"]:
        (inbox / f"{agent}.md").write_text("", encoding="utf-8")

    return board


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all provider-related env vars to ensure a clean state."""
    env_vars = [
        "GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT_ID",
        "GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO", "GITHUB_API_URL",
        "GIT_REPO_URL", "GIT_REPO_PATH", "GIT_USER_NAME", "GIT_USER_EMAIL",
        "GIT_MAIN_BRANCH", "GIT_AUTO_PUSH", "GIT_SSH_KEY", "GIT_TOKEN",
        "DOCKER_HOST", "DOCKER_REGISTRY", "DOCKER_REGISTRY_USER",
        "DOCKER_REGISTRY_PASS", "DOCKER_IMAGE_PREFIX",
        "DOCKER_COMPOSE_FILE", "DOCKER_MAX_CONTAINERS",
        "DOCKER_ALLOWED_NETWORKS",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch
