#!/usr/bin/env python3
"""
AI Dev Team — Provider Auto-Discovery
Detects the active board provider from environment variables.
"""

import os
import logging
from typing import Optional

from ..base import BoardProvider

logger = logging.getLogger(__name__)


def detect_provider() -> Optional[BoardProvider]:
    """
    Detect the active provider from env vars.

    Priority:
    1. GitLab — if GITLAB_URL + GITLAB_TOKEN are set
    2. GitHub — if GITHUB_TOKEN + GITHUB_REPO are set
    """
    # GitLab
    if os.getenv("GITLAB_URL") and os.getenv("GITLAB_TOKEN"):
        from .gitlab import GitLabProvider
        provider = GitLabProvider()
        if provider.enabled:
            logger.info("Board provider: GitLab")
            return provider

    # GitHub
    if os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPO"):
        from .github import GitHubProvider
        provider = GitHubProvider()
        if provider.enabled:
            logger.info("Board provider: GitHub")
            return provider

    logger.warning("No board provider found")
    return None
