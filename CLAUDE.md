# AI Dev Team — Claude Code Project Guide

## What This Is

Autonomous AI development team framework. 9 Claude-powered agents work as an agile team: plan sprints, write code, review, test, handle security, deploy. Orchestrated by cron, communicates via Markdown files.

## Project Structure

- `config/agents.yaml` — Agent definitions and system prompts (9 agents)
- `config/project.yaml` — Sprint counter, project description, tech stack
- `config/.env` — Tokens and credentials (gitignored, see .env.example)
- `scripts/orchestrator_cli.sh` — Main orchestrator (bash), runs agents sequentially
- `scripts/run_agent_cli.py` — Agent runner, builds context and calls `claude --print`
- `scripts/sync_board.py` — Syncs board/backlog.md + sprint.md → GitLab/GitHub issues
- `scripts/sync_comments.py` — Syncs agent messages → issue comments
- `scripts/restore_board.py` — Board health check and restore from snapshot/provider
- `scripts/merge_approved_mrs.py` — Auto-merges approved MRs/PRs
- `integrations/base.py` — BoardProvider ABC (shared interface for GitLab/GitHub)
- `integrations/providers/gitlab.py` — GitLab API v4 implementation
- `integrations/providers/github.py` — GitHub REST API implementation
- `integrations/git_client.py` — Git operations (branch, commit, push)
- `integrations/docker_client.py` — Docker/docker-compose operations
- `integrations/logging_config.py` — Shared logging + env loader

## Key Conventions

- Board state lives in `board/*.md` files (sprint.md, backlog.md, etc.)
- Agents communicate via `board/inbox/{agent_id}.md`
- Story IDs: `STORY-XXX`, Bug IDs: `BUG-XXX`
- Status flow: TODO → IN_PROGRESS → REVIEW → TESTING → DONE
- Labels on GitLab/GitHub: `status::todo`, `priority::high`, etc.
- Provider auto-detection: GitLab if GITLAB_URL+GITLAB_TOKEN set, GitHub if GITHUB_TOKEN+GITHUB_REPO set

## Running

```bash
# Initialize project
python3 scripts/init_project.py "Name" "Description"

# Run one cycle (all core agents)
./scripts/orchestrator_cli.sh dev-team

# Run single agent
./scripts/orchestrator_cli.sh dev1

# Run tests
python3 -m pytest tests/ -v
```

## Code Style

- Python 3.10+ with modern type hints (list[str] not List[str])
- Shared logging via `integrations/logging_config.py` — use `setup_logging("name")`
- Shared env loading via `load_env()` from same module
- No external dependencies beyond pyyaml (API calls use urllib)
- All provider integrations go through BoardProvider ABC

## Tests

Tests in `tests/` — run with `python3 -m pytest tests/ -v`. No external API calls, all mocked.
