# Testing with Claude Pro / Max

A guide for testing AI Dev Team with Claude Pro ($20/mo) or Max ($100/mo) subscriptions.

## Prerequisites

1. **Claude Code CLI** installed and logged in:
```bash
npm install -g @anthropic-ai/claude-code
claude login
```

2. **Project initialized**:
```bash
cd /path/to/ai-team
python scripts/init_project.py "Test Project" "A test project to validate the concept"
```

## Rate Limits

| Metric | Pro ($20) | Max ($100) |
|--------|-----------|------------|
| Messages/5h | ~45 | ~225 |
| Recommended cycles/day | 3-4 | 15-20 |
| Agents per cycle | 3 (minimal) | 6-9 (full team) |

## Test Scenarios

### 1. Single Agent (smallest test)
```bash
# Run just the Product Owner
./scripts/orchestrator_cli.sh po

# Check output
cat board/backlog.md
cat board/inbox/pm.md
```

### 2. Minimal Team (3 agents)
```bash
# PO → Dev1 → Tester
./scripts/orchestrator_cli.sh minimal

# Check results
cat board/sprint.md
ls workspace/src/
```

### 3. Full Dev Team (6 agents)
```bash
# All core agents (recommended for Max plan)
./scripts/orchestrator_cli.sh dev-team
```

### 4. Full Team with Security (9 agents)
```bash
# Everyone — only with Max plan
./scripts/orchestrator_cli.sh all
```

## Recommended Test Plan

### Day 1: Validate the concept
```bash
# Morning — initialize project
python scripts/init_project.py "MyProject" "Project description"

# Test 1: PO defines the backlog
./scripts/orchestrator_cli.sh po
cat board/backlog.md

# Test 2: Minimal cycle
./scripts/orchestrator_cli.sh minimal
```

### Day 2: Multiple cycles
```bash
# 3-4 minimal cycles throughout the day
./scripts/orchestrator_cli.sh minimal  # morning
./scripts/orchestrator_cli.sh minimal  # afternoon
./scripts/orchestrator_cli.sh minimal  # evening

# Track progress
cat board/sprint.md
```

### Day 3: Evaluate
```bash
# What got done?
cat board/sprint.md | grep "DONE"

# What code was generated?
find workspace/src -name "*.py" | head -20

# Is agent communication working?
cat board/inbox/*.md
```

## Cron for Automated Cycles

For Pro plan — max 3-4 cycles/day:
```bash
# Every 6 hours, work hours only
0 8,14,20 * * * /path/to/ai-team/scripts/orchestrator_cli.sh minimal >> /path/to/ai-team/logs/cron.log 2>&1
```

For Max plan — you can run more:
```bash
# Every 2 hours
0 */2 8-22 * * * /path/to/ai-team/scripts/orchestrator_cli.sh dev-team >> /path/to/ai-team/logs/cron.log 2>&1
```

## Troubleshooting

### "Rate limit reached"
```bash
# Wait for reset (~5 hours) or:
# - Use minimal mode (3 agents instead of 6-9)
# - Reduce cycle frequency
```

### Claude Code not logged in
```bash
claude login
# Follow browser instructions
```

### Agents produce poor results
```bash
# Check their inbox — they might lack context
cat board/inbox/dev1.md

# Check project.md — is it descriptive enough?
cat board/project.md
```
