"""Tests for GitConfig and DockerConfig classes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.git_client import GitConfig
from integrations.docker_client import DockerConfig


# ---------------------------------------------------------------------------
# GitConfig
# ---------------------------------------------------------------------------

def test_git_config_defaults(clean_env):
    config = GitConfig()
    assert config.repo_url == ""
    assert config.repo_path == Path("./repo")
    assert config.user_name == "AI Dev Team"
    assert config.user_email == "ai-team@example.com"
    assert config.main_branch == "main"
    assert config.auto_push is True


def test_git_config_is_configured_false_when_empty(clean_env):
    config = GitConfig()
    assert config.is_configured is False


def test_git_config_is_configured_true_when_set(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "https://gitlab.com/group/project.git")
    config = GitConfig()
    assert config.is_configured is True


def test_git_config_auth_repo_url_with_token(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "https://gitlab.com/group/project.git")
    monkeypatch.setenv("GIT_TOKEN", "my-secret-token")
    config = GitConfig()
    expected = "https://oauth2:my-secret-token@gitlab.com/group/project.git"
    assert config.auth_repo_url == expected


def test_git_config_auth_repo_url_without_token(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "https://gitlab.com/group/project.git")
    config = GitConfig()
    assert config.auth_repo_url == "https://gitlab.com/group/project.git"


def test_git_config_auth_repo_url_ssh(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "git@gitlab.com:group/project.git")
    monkeypatch.setenv("GIT_TOKEN", "my-secret-token")
    config = GitConfig()
    # Token should not be inserted into SSH URLs
    assert config.auth_repo_url == "git@gitlab.com:group/project.git"


def test_git_config_reads_env_vars(clean_env, monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "https://example.com/repo.git")
    monkeypatch.setenv("GIT_REPO_PATH", "/tmp/myrepo")
    monkeypatch.setenv("GIT_USER_NAME", "Test User")
    monkeypatch.setenv("GIT_USER_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_MAIN_BRANCH", "develop")
    monkeypatch.setenv("GIT_AUTO_PUSH", "false")

    config = GitConfig()
    assert config.repo_url == "https://example.com/repo.git"
    assert config.repo_path == Path("/tmp/myrepo")
    assert config.user_name == "Test User"
    assert config.user_email == "test@example.com"
    assert config.main_branch == "develop"
    assert config.auto_push is False


# ---------------------------------------------------------------------------
# DockerConfig
# ---------------------------------------------------------------------------

def test_docker_config_defaults(clean_env):
    config = DockerConfig()
    assert config.docker_host == ""
    assert config.registry == ""
    assert config.max_containers == 10
    assert config.compose_file == "docker-compose.yml"
    assert config.is_configured is True  # Always True (inside LXC)


def test_docker_config_max_containers_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("DOCKER_MAX_CONTAINERS", "5")
    config = DockerConfig()
    assert config.max_containers == 5


def test_docker_config_max_containers_invalid_defaults_to_10(clean_env, monkeypatch):
    monkeypatch.setenv("DOCKER_MAX_CONTAINERS", "not_a_number")
    config = DockerConfig()
    assert config.max_containers == 10


def test_docker_config_max_containers_zero_defaults_to_10(clean_env, monkeypatch):
    monkeypatch.setenv("DOCKER_MAX_CONTAINERS", "0")
    config = DockerConfig()
    assert config.max_containers == 10


def test_docker_config_max_containers_negative_defaults_to_10(clean_env, monkeypatch):
    monkeypatch.setenv("DOCKER_MAX_CONTAINERS", "-3")
    config = DockerConfig()
    assert config.max_containers == 10


def test_docker_config_allowed_networks(clean_env, monkeypatch):
    monkeypatch.setenv("DOCKER_ALLOWED_NETWORKS", "bridge,overlay,mynet")
    config = DockerConfig()
    assert config.allowed_networks == ["bridge", "overlay", "mynet"]


def test_docker_config_allowed_networks_default(clean_env):
    config = DockerConfig()
    assert config.allowed_networks == ["bridge", "host"]
