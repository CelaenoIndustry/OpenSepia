#!/usr/bin/env python3
"""
AI Dev Team — Integration Initialization
Run once after setting up the .env file.
Initializes GitLab board, clones repo, verifies Docker.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.logging_config import load_env
load_env()

from integrations.providers.gitlab import GitLabProvider, GitLabConfig
from integrations.git_client import GitClient, GitConfig
from integrations.docker_client import DockerClient, DockerConfig
from integrations.logging_config import setup_logging
logger = setup_logging("init_integrations")


def main() -> None:
    print("=" * 60)
    print("  AI Dev Team — Integration Initialization")
    print("=" * 60)

    errors = []

    # =========================================================================
    # GitLab
    # =========================================================================
    print("\n📋 GitLab...")
    gitlab_config = GitLabConfig()
    if gitlab_config.is_configured:
        try:
            client = GitLabProvider(gitlab_config)
            client.init()  # Creates labels and board
            summary = client.get_board_summary_md()
            print(f"   ✅ GitLab board ready")
            print(f"   URL: {gitlab_config.url}")
            print(f"   Project: {gitlab_config.project_id}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            errors.append(f"GitLab: {e}")
    else:
        print("   ⏭️  Skipped (GITLAB_URL/TOKEN/PROJECT_ID not set)")

    # =========================================================================
    # Git
    # =========================================================================
    print("\n🔀 Git...")
    git_config = GitConfig()
    if git_config.is_configured:
        try:
            client = GitClient(git_config)
            success = client.clone_or_pull()
            if success:
                branch = client.current_branch()
                print(f"   ✅ Repo cloned/updated")
                print(f"   Path: {git_config.repo_path}")
                print(f"   Branch: {branch}")
                print(f"   Auto-push: {git_config.auto_push}")
            else:
                print(f"   ❌ Clone/pull failed")
                errors.append("Git: clone/pull failed")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            errors.append(f"Git: {e}")
    else:
        print("   ⏭️  Skipped (GIT_REPO_URL not set)")

    # =========================================================================
    # Docker
    # =========================================================================
    print("\n🐳 Docker...")
    try:
        docker_config = DockerConfig()
        docker_client = DockerClient(docker_config)

        # Test docker info
        containers = docker_client.ps(all=True)
        images = docker_client.images()

        running = [c for c in containers if c.get("State") == "running"]

        print(f"   ✅ Docker connected")
        print(f"   Containers: {len(running)} running, {len(containers)} total")
        print(f"   Images: {len(images)}")
        print(f"   Max containers: {docker_config.max_containers}")

        if running:
            print(f"   Running:")
            for c in running[:5]:  # Max 5
                print(f"      🟢 {c.get('Names')}: {c.get('Image')}")

        if docker_config.registry:
            print(f"   Registry: {docker_config.registry}")

    except Exception as e:
        print(f"   ❌ Docker unavailable: {e}")
        errors.append(f"Docker: {e}")
        print(f"   Make sure Docker is running: systemctl status docker")

    # =========================================================================
    # Summary
    # =========================================================================
    print(f"\n{'=' * 60}")
    if errors:
        print(f"⚠️  Completed with {len(errors)} errors:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("✅ All integrations initialized!")

    print(f"\nNext step: python scripts/run_agent.py --all --verbose")


if __name__ == "__main__":
    main()
