"""
AI Dev Team — Shared Logging Configuration
"""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(__file__).parent.parent / "logs"


def load_env() -> None:
    """Load config/.env into os.environ (if exists)."""
    env_file = Path(__file__).parent.parent / "config" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()


def setup_logging(name: str = "ai-team", level: str = "INFO",
                  log_to_file: bool = True) -> logging.Logger:
    """Configure logging for AI Dev Team scripts.

    Args:
        name: Logger name (used as prefix)
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_to_file: Also write to logs/ai-team.log

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # File handler (if enabled)
    if log_to_file:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / "ai-team.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger
