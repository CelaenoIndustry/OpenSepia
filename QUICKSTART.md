# Quick Start — AI Dev Team

## Environment

- **Linux** (Ubuntu, Debian, or any Linux with bash)
- **Claude Code CLI** with Pro or Max subscription
- **Python 3.10+**

> **Recommended:** Run AI Dev Team in an isolated environment — a dedicated VM, LXC container, or Docker container. The agents have access to shell tools (`Bash`, `Edit`, `Write`) and will create files, run commands, and modify your workspace. An isolated environment ensures they cannot accidentally affect your host system or other projects.

## 1. Install

### Claude Code CLI

AI Dev Team runs on Claude Code — Anthropic's CLI for Claude AI. You need a Pro ($20/mo) or Max ($100/mo) subscription.

```bash
# Install Claude Code
npm install -g @anthropic-ai/claude-code

# Login (opens browser)
claude login

# Verify
claude --version
```

### Python Dependencies

```bash
# Clone the project
git clone https://github.com/CelaenoIndustry/OpenSepia.git
cd ai-team

# Install dependencies
pip install -r requirements.txt
```

> **Note:** AI Dev Team does NOT use the Anthropic API. It calls `claude --print` directly, which uses your Claude subscription. No API key needed.

## 2. Set Up Your Project

### Option A: Use Claude Code (recommended)

The easiest way to get started — just open Claude Code in the project directory and tell it what you want to build:

```bash
cd ai-team
claude
```

Then tell Claude what to do:

```
> Initialize an AI dev team project for a REST API with FastAPI and PostgreSQL.
  Set up GitLab integration with token glpat-xxx on gitlab.example.com,
  project group/my-api. Start the team and set up cron.
```

Claude Code reads the `CLAUDE.md` instructions and knows how to:
- Initialize the project (`init_project.py`)
- Configure GitLab/GitHub integration (`.env` + `init_integrations.py`)
- Write a detailed brief to the PO agent's inbox
- Start the first cycle
- Set up cron for automated runs

This is how the [RAG example](examples/rag-app/) was built — a single conversation with Claude Code set up the entire project and team.

### Option B: Manual setup

```bash
# Initialize project
python scripts/init_project.py "My API" \
  "REST API for document management with FastAPI backend and PostgreSQL"

# (Optional) Write a detailed brief to the PO
cp examples/rag-app/po-brief.md board/inbox/po.md
# Edit board/inbox/po.md with your own project brief

# (Optional) Set up GitLab/GitHub integration
cp config/.env.example config/.env
nano config/.env  # fill in your tokens
python scripts/init_integrations.py
```

> **Tip:** See [examples/rag-app/po-brief.md](examples/rag-app/po-brief.md) for a real PO brief that produced 3,600 lines of code overnight.

## 3. Run Your First Cycle

```bash
# Core dev team (6 agents): PO, PM, Dev1, Dev2, DevOps, Tester
./scripts/orchestrator_cli.sh dev-team

# Minimal team (3 agents): PO, Dev1, Tester — saves rate limits
./scripts/orchestrator_cli.sh minimal

# Full team including security (9 agents)
./scripts/orchestrator_cli.sh all

# Security audit only (3 agents)
./scripts/orchestrator_cli.sh security

# Single agent (for debugging)
./scripts/orchestrator_cli.sh dev1
```

## 4. Set Up Automated Runs

```bash
# Edit crontab paths first
nano ai-team.crontab

# Install crontab
crontab ai-team.crontab
```

Or add manually:
```bash
crontab -e

# Dev team every 40 minutes
*/40 * * * * /path/to/ai-team/scripts/orchestrator_cli.sh dev-team >> /path/to/ai-team/logs/cron.log 2>&1

# Security audit once daily at 6:00 AM
0 6 * * * /path/to/ai-team/scripts/orchestrator_cli.sh security >> /path/to/ai-team/logs/cron.log 2>&1
```

Now go to sleep. The team works while you're away.

## 5. Check Results

```bash
# Sprint board
cat board/sprint.md

# Backlog
cat board/backlog.md

# Generated code
ls workspace/src/

# Standup reports
cat board/standup.md

# Agent messages
cat board/inbox/*.md

# Live monitoring
tail -f logs/cron.log
```

---

## GitLab / GitHub Integration

```bash
# Configure tokens
cp config/.env.example config/.env
nano config/.env  # fill in your tokens

# Initialize integration (creates labels, boards, clones repo)
python scripts/init_integrations.py
```

With integration enabled you get:
- Issues on a Kanban board
- Merge Requests / Pull Requests from developers
- Agent comments on issues
- Code review comments posted directly on MRs
- Automatic MR approval when agents approve code
- Auto-merge of approved MRs/PRs

---

## Human Intervention

Send messages to any agent by writing to their inbox:

```bash
echo "## Message from Human
STORY-003 priority is now CRITICAL!" >> board/inbox/pm.md
```

The agent reads your message in the next cycle. You can also comment directly on GitLab/GitHub issues — agents read those too.

---

## Rate Limits

| Plan | Messages/5h | Recommended cycles/day | Team size |
|------|-------------|----------------------|-----------|
| **Pro** ($20/mo) | ~45 | 3-4 | minimal (3) |
| **Max** ($100/mo) | ~225 | 15-20 | dev-team (6) or all (9) |

---

## Troubleshooting

### "Rate limit reached"
Wait for the rate limit to reset (~5 hours) or reduce team size to `minimal`.

### Claude Code not logged in
```bash
claude login
# Follow browser instructions
```

### Agents produce poor output
- Check `board/project.md` — is the project well described?
- Check `config/project.yaml` — is the tech stack correct?
- Try running a single agent first: `./scripts/orchestrator_cli.sh po`
