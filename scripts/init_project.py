#!/usr/bin/env python3
"""
AI Dev Team — Project Initialization
Creates initial board files for a new project.
"""

import sys
import yaml
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
BOARD_DIR = BASE_DIR / "board"
WORKSPACE_DIR = BASE_DIR / "workspace"
CONFIG_DIR = BASE_DIR / "config"


def init_project(name: str, description: str) -> None:
    """Initialize project with initial files."""

    print(f"🚀 Initializing project: {name}")

    # Create directories
    for d in ["inbox", "archive"]:
        (BOARD_DIR / d).mkdir(parents=True, exist_ok=True)
    for d in ["src", "tests", "docs", "config"]:
        (WORKSPACE_DIR / d).mkdir(parents=True, exist_ok=True)

    # project.md
    (BOARD_DIR / "project.md").write_text(f"""# {name}

## Description
{description}

## Status
- **Created**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
- **Phase**: Initialization
- **Sprint**: 1

## Goals
- [ ] Define product vision and MVP
- [ ] Create initial architecture
- [ ] Set up development environment
- [ ] Implement first feature

## Team
- 🟣 Product Owner — defines WHAT will be done
- 🔵 Project Manager — coordinates HOW and WHEN
- 🟢 Developer 1 — implements code, reviews dev2
- 🟩 Developer 2 — implements code, reviews dev1
- 🟠 DevOps Engineer — Docker, local deployment
- 🔴 Tester/QA — functional review and testing
- 🛡️ Security Analyst — security review
- 🔐 Security Engineer — implements security
- 💀 Penetration Tester — tests from attacker's perspective
""", encoding="utf-8")

    # backlog.md
    (BOARD_DIR / "backlog.md").write_text(f"""# Product Backlog — {name}

## 🔴 CRITICAL

## 🟠 HIGH
- **STORY-001**: Define MVP scope
  - *As a* Product Owner
  - *I want* a clearly defined MVP with prioritized features
  - *So that* the team knows what to work on
  - **Acceptance criteria:**
    - [ ] List of at least 5 user stories
    - [ ] Each story has priority and estimate
    - [ ] PO approved the order

## 🟡 MEDIUM
- **STORY-002**: Set up development environment
  - *As a* Developer
  - *I want* a functional development environment with CI/CD
  - *So that* I can start implementing
  - **Acceptance criteria:**
    - [ ] Defined project structure
    - [ ] Dockerfile / container
    - [ ] CI pipeline for tests
    - [ ] README with instructions

## 🟢 LOW

## ✅ DONE
""", encoding="utf-8")

    # sprint.md
    (BOARD_DIR / "sprint.md").write_text(f"""# Sprint 1 — Initialization

**Goal**: Define the project, create a foundation for development
**Start**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Cycle**: 0/10

## 📋 TODO
- [ ] STORY-001: Define MVP scope (PO)
- [ ] STORY-002: Set up development environment (DevOps + Dev)

## 🔄 IN PROGRESS

## ✅ DONE

## 🚫 BLOCKED

## 📊 Velocity
- Completed this sprint: 0
""", encoding="utf-8")

    # architecture.md
    (BOARD_DIR / "architecture.md").write_text(f"""# Architecture — {name}

## Overview
(Will be filled in after MVP definition)

## Tech Stack
(To be decided)

## Directory Structure
```
workspace/
├── src/          # Source code
├── tests/        # Tests
├── docs/         # Documentation
└── config/       # Configuration
```

## Decisions
(See decisions.md)
""", encoding="utf-8")

    # decisions.md
    (BOARD_DIR / "decisions.md").write_text(f"""# Decisions (Decision Log)

Format:
```
### DEC-XXX: Name (YYYY-MM-DD)
- **Context**: Why a decision is needed
- **Decision**: What was decided
- **Reason**: Why
- **Who**: Who decided
```

---

### DEC-001: Project initialization ({datetime.now().strftime("%Y-%m-%d")})
- **Context**: New project {name}
- **Decision**: Starting Sprint 1 — Initialization
- **Reason**: We need to define MVP and set up the environment
- **Who**: System (init)
""", encoding="utf-8")

    # Empty inboxes
    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester", "sec_analyst", "sec_engineer", "sec_pentester"]:
        inbox = BOARD_DIR / "inbox" / f"{agent}.md"
        if not inbox.exists():
            inbox.write_text("", encoding="utf-8")

    # Update project.yaml
    with open(CONFIG_DIR / "project.yaml", "r") as f:
        config = yaml.safe_load(f)

    config["project"]["name"] = name
    config["project"]["description"] = description
    config["sprint"]["current_sprint"] = 1
    config["sprint"]["current_cycle"] = 0

    with open(CONFIG_DIR / "project.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Seed message for PO
    (BOARD_DIR / "inbox" / "po.md").write_text(f"""## System message — Initialization

Project **{name}** has just been created.

**Description**: {description}

### Your first task:
1. Define the product vision
2. Break down the MVP into user stories (at least 5)
3. Prioritize the backlog
4. Send PM instructions for Sprint 1

Start by updating `project.md` and `backlog.md`.
""", encoding="utf-8")

    print(f"✅ Project initialized!")
    print(f"   Board:     {BOARD_DIR}")
    print(f"   Workspace: {WORKSPACE_DIR}")
    print(f"")
    print(f"Next steps:")
    print(f"  1. Log in to Claude Code: claude login")
    print(f"  2. Run the first cycle: ./scripts/orchestrator_cli.sh dev-team")
    print(f"  3. Or just one agent: ./scripts/orchestrator_cli.sh po")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python init_project.py 'Project Name' ['Project Description']")
        print("")
        print("Example:")
        print("  python init_project.py 'My API' 'REST API with FastAPI and PostgreSQL'")
        sys.exit(1)

    name = sys.argv[1]
    description = sys.argv[2] if len(sys.argv) > 2 else "New project"
    init_project(name, description)
