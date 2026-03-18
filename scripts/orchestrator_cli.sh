#!/bin/bash
# =============================================================================
# AI Dev Team — Orchestrator (Claude Code CLI version)
# For Claude Max subscription with Opus 4.5
# =============================================================================

# NOTE: set -e is intentionally NOT used. This orchestrator must continue past
# non-critical failures (agent errors, sync failures, etc.) and handle them
# individually with || clauses and explicit checks.
set -uo pipefail

# Sanitize output to prevent token leakage
sanitize_output() {
    sed "s|oauth2:[^@]*@|oauth2:***@|g"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR" || { echo "$(date) [ERROR] Cannot cd to project dir: $PROJECT_DIR"; exit 1; }

# Ensure PATH for cron (where PATH is often limited)
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin:$PATH"

# Unset CLAUDECODE — otherwise claude CLI refuses to run ("nested session")
unset CLAUDECODE 2>/dev/null || true

# Mode: minimal | dev-team | security | all | <agent_name>
MODE="${1:-dev-team}"

# Lock file — per mode so dev-team and security can run in parallel
# (their agent sets don't overlap)
LOCKFILE="/tmp/ai-team-cli-${MODE}.lock"
if [ -f "$LOCKFILE" ]; then
    PID=$(cat "$LOCKFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "$(date) [WARN] Previous ${MODE} cycle is running (PID: $PID)"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

echo ""
echo "============================================"
echo "  AI Dev Team — Claude Code CLI"
echo "  $(date)"
echo "  Mode: ${MODE}"
echo "============================================"

# ---- Load .env variables (needed for git sync and agents) ----
load_env() {
    local env_file="$PROJECT_DIR/config/.env"
    if [ -f "$env_file" ]; then
        while IFS='=' read -r key value; do
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            [[ -z "$key" || "$key" == \#* ]] && continue
            export "${key}=${value}"
        done < "$env_file"
    fi
}
load_env

REPO_PATH="${GIT_REPO_PATH:-$PROJECT_DIR/repo}"
AUTH_URL=$(echo "${GIT_REPO_URL:-}" | sed "s|https://|https://oauth2:${GIT_TOKEN:-}@|")

# Track whether agents ran successfully
AGENTS_OK=false

# ---- Board health check (auto-restore if critical files missing) ----
BOARD_OK=true
for f in sprint.md backlog.md; do
    if [ ! -f "$PROJECT_DIR/board/$f" ] || [ ! -s "$PROJECT_DIR/board/$f" ]; then
        echo "$(date) [WARN] Critical board file missing or empty: board/$f"
        BOARD_OK=false
    fi
done

if [ "$BOARD_OK" != "true" ]; then
    echo "$(date) [INFO] Attempting board restore from snapshot..."
    if [ -d "$PROJECT_DIR/board/.snapshot" ]; then
        python3 "$SCRIPT_DIR/restore_board.py" --from-snapshot 2>&1
    fi

    # Re-check after snapshot restore
    BOARD_OK=true
    for f in sprint.md backlog.md; do
        if [ ! -f "$PROJECT_DIR/board/$f" ] || [ ! -s "$PROJECT_DIR/board/$f" ]; then
            BOARD_OK=false
        fi
    done

    if [ "$BOARD_OK" != "true" ]; then
        echo "$(date) [INFO] Snapshot restore insufficient, trying provider..."
        python3 "$SCRIPT_DIR/restore_board.py" --from-provider 2>&1 || true
    fi
fi

# Ensure inbox files exist
mkdir -p "$PROJECT_DIR/board/inbox"
for agent in po pm dev1 dev2 devops tester sec_analyst sec_engineer sec_pentester; do
    touch "$PROJECT_DIR/board/inbox/${agent}.md"
done

# ---- Check Claude Code CLI ----
if ! command -v claude &> /dev/null; then
    echo "$(date) [WARN] Claude Code CLI not in PATH — agents will not run"
    echo "  PATH=$PATH"
    echo "  Install: npm install -g @anthropic-ai/claude-code"
else
    echo "  Claude CLI: $(claude --version 2>/dev/null || echo 'ok')"

    # Check end of sprint
    check_sprint() {
        python3 -c "
import yaml
with open('config/project.yaml') as f:
    c = yaml.safe_load(f)
sprint = c.get('sprint', {})
cycle = sprint.get('current_cycle', 0)
max_cycles = sprint.get('cycles_per_sprint', 10)
if cycle >= max_cycles:
    print(f'SPRINT_END:{cycle}')
else:
    print(f'OK:{cycle}/{max_cycles}')
"
    }

    SPRINT_STATUS=$(check_sprint)
    if [[ "$SPRINT_STATUS" == SPRINT_END* ]]; then
        echo "$(date) [INFO] Sprint completed. Running PO and PM for retrospective."
        python3 scripts/run_agent_cli.py --agent po --verbose --no-increment 2>&1 || echo "$(date) [WARN] PO agent failed"
        python3 scripts/run_agent_cli.py --agent pm --verbose --no-increment 2>&1 || echo "$(date) [WARN] PM agent failed"

        # Auto-increment sprint — synchronize with number from sprint.md (agents may be ahead)
        echo "$(date) [INFO] Auto-increment: synchronizing sprint with board..."
        python3 -c "
import yaml, re
with open('config/project.yaml') as f:
    c = yaml.safe_load(f)
s = c.get('sprint', {})
old_sprint = s.get('current_sprint', 1)

# Get sprint number from sprint.md (agents determine it)
new_sprint = old_sprint + 1
try:
    with open('board/sprint.md') as f:
        header = f.readline()
    m = re.search(r'Sprint\s+(\d+)', header)
    if m:
        board_sprint = int(m.group(1))
        if board_sprint > old_sprint:
            new_sprint = board_sprint
except:
    pass

s['current_sprint'] = new_sprint
s['current_cycle'] = 0
c['sprint'] = s
with open('config/project.yaml', 'w') as f:
    yaml.dump(c, f, default_flow_style=False, allow_unicode=True)
print(f'Sprint {old_sprint} -> {new_sprint}, cycle reset to 0')
"
        AGENTS_OK=true
    else
        echo "  Sprint status: $SPRINT_STATUS"

        # ---- Board snapshot (before agents run) ----
        SNAPSHOT_DIR="$PROJECT_DIR/board/.snapshot"
        mkdir -p "$SNAPSHOT_DIR"
        for f in sprint.md backlog.md project.md architecture.md decisions.md; do
            [ -f "$PROJECT_DIR/board/$f" ] && cp "$PROJECT_DIR/board/$f" "$SNAPSHOT_DIR/$f.bak"
        done
        echo "  Board snapshot: saved to board/.snapshot/"

        # Run agents by mode
        case "$MODE" in
            all)
                echo "  Agents: all 9 (PO, PM, Dev1, Dev2, DevOps, Tester + Security)"
                python3 scripts/run_agent_cli.py --all --verbose 2>&1 && AGENTS_OK=true
                ;;
            dev-team|dev)
                echo "  Agents: dev team (6)"
                python3 scripts/run_agent_cli.py --dev-team --verbose 2>&1 && AGENTS_OK=true
                ;;
            minimal|min)
                echo "  Agents: minimal (3)"
                python3 scripts/run_agent_cli.py --minimal --verbose 2>&1 && AGENTS_OK=true
                ;;
            security|sec)
                echo "  Agents: security team (3)"
                python3 scripts/run_agent_cli.py --security --verbose 2>&1 && AGENTS_OK=true
                ;;
            po|pm|dev1|dev2|devops|tester|sec_analyst|sec_engineer|sec_pentester)
                echo "  Agent: $MODE"
                python3 scripts/run_agent_cli.py --agent "$MODE" --verbose 2>&1 && AGENTS_OK=true
                ;;
            *)
                echo "Unknown mode: $MODE"
                echo ""
                echo "Usage: $0 [mode]"
                echo ""
                echo "Modes:"
                echo "  all        - all 9 agents"
                echo "  dev-team   - 6 agents (core team)"
                echo "  minimal    - 3 agents (PO, Dev1, Tester)"
                echo "  security   - 3 agents (security team)"
                echo "  <agent>    - specific agent (po, pm, dev1, dev2, devops, tester,"
                echo "               sec_analyst, sec_engineer, sec_pentester)"
                # Unknown mode = skip git sync etc.
                rm -f "$LOCKFILE"
                exit 1
                ;;
        esac

        if [ "$AGENTS_OK" != "true" ]; then
            echo "$(date) [WARN] Agents failed, but continuing with git sync and auto-merge"
        fi
    fi
fi

# =============================================================================
# POST-AGENT PHASE: Always runs (even if agents failed or claude CLI is missing)
# =============================================================================

# ---- Standup -> provider sync ----
echo "$(date) [INFO] Standup -> provider sync..."
PROJECT_DIR="$PROJECT_DIR" python3 -c "
import sys, os
project_dir = os.environ.get('PROJECT_DIR', '')
sys.path.insert(0, project_dir)
os.chdir(project_dir)
from pathlib import Path
from integrations.providers import detect_provider
from scripts.sync_comments import post_standup_to_provider
client = detect_provider()
if client and client.enabled:
    posted = post_standup_to_provider(Path('board/standup.md'), client)
    print(f'  Standup: {posted} comments posted to provider')
else:
    print('  Standup: provider not configured, skipping')
" 2>&1 || echo "$(date) [WARN] Standup provider sync failed (non-critical)"

# ---- Auto-merge approved MRs ----
echo "$(date) [INFO] Auto-merge approved MRs..."
python3 "$SCRIPT_DIR/merge_approved_mrs.py" 2>&1 || echo "$(date) [WARN] Auto-merge failed (non-critical)"

# ---- Git Sync: feature branch + MR ----
GIT_SYNC() {
    if [ -z "${GIT_REPO_URL:-}" ] || [ ! -d "$REPO_PATH/.git" ]; then
        echo "$(date) [INFO] Git sync skipped (repo does not exist or is not configured)"
        return 0
    fi

    # If agents did not run, still sync what is in workspace (there may be manual changes)
    CYCLE_NUM=$(PROJECT_DIR="$PROJECT_DIR" python3 -c "import yaml, os; c=yaml.safe_load(open(os.path.join(os.environ['PROJECT_DIR'],'config','project.yaml'))); print(c.get('sprint',{}).get('current_cycle',0))" 2>/dev/null || echo "0")
    SPRINT_NUM=$(PROJECT_DIR="$PROJECT_DIR" python3 -c "import yaml, os; c=yaml.safe_load(open(os.path.join(os.environ['PROJECT_DIR'],'config','project.yaml'))); print(c.get('sprint',{}).get('current_sprint',1))" 2>/dev/null || echo "1")

    # Get active story IDs from sprint.md for branch naming
    STORY_SLUG=$(PROJECT_DIR="$PROJECT_DIR" python3 -c "
import re, os
try:
    with open(os.path.join(os.environ['PROJECT_DIR'], 'board', 'sprint.md')) as f:
        content = f.read()
    # Find stories with status IN_PROGRESS, REVIEW, TESTING or DONE (in this cycle)
    stories = re.findall(r'###\s+(STORY-\d+|BUG-\d+).*?\n\*\*Status\*\*:\s*(IN_PROGRESS|REVIEW|TESTING)', content, re.DOTALL)
    if stories:
        ids = [s[0].lower().replace('-', '') for s in stories[:3]]
        print('-'.join(ids))
    else:
        print('')
except:
    print('')
" 2>/dev/null)

    if [ -n "$STORY_SLUG" ]; then
        BRANCH_NAME="ai-team/${STORY_SLUG}-s${SPRINT_NUM}c${CYCLE_NUM}"
    else
        BRANCH_NAME="ai-team/sprint-${SPRINT_NUM}-cycle-${CYCLE_NUM}"
    fi
    TIMESTAMP=$(date -Iseconds)

    echo "$(date) [INFO] Git sync: workspace/src -> branch $BRANCH_NAME"

    cd "$REPO_PATH" || { echo "$(date) [ERROR] Cannot cd to repo: $REPO_PATH"; return 1; }

    # Update main
    if ! git fetch "$AUTH_URL" main 2>&1 | sanitize_output; then
        echo "$(date) [ERROR] git fetch failed"
        cd "$PROJECT_DIR"
        return 1
    fi
    git checkout main 2>/dev/null || true
    git reset --hard FETCH_HEAD 2>/dev/null || true

    # Create feature branch
    git checkout -b "$BRANCH_NAME" 2>/dev/null || git checkout "$BRANCH_NAME" 2>/dev/null || true

    # --- Sync code ---
    echo "$(date) [INFO] Sync workspace/src -> repo/src"
    rsync -a --delete \
        --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
        --exclude='.venv' --exclude='venv' --exclude='.claude' \
        "$PROJECT_DIR/workspace/src/" "$REPO_PATH/src/" 2>/dev/null || true

    # --- Board is NOT synced to repo (stays local only) ---

    # --- Commit on feature branch ---
    git add src/

    CODE_CHANGES=$(git diff --cached --name-only -- src/ | head -5)

    if git diff --cached --quiet; then
        echo "$(date) [INFO] Git: no changes to commit"
        git checkout main 2>/dev/null || true
        git branch -D "$BRANCH_NAME" 2>/dev/null || true
        cd "$PROJECT_DIR"
        return 0
    fi

    # Commit message with list of changes
    if [ -n "$STORY_SLUG" ]; then
        COMMIT_MSG="feat(${STORY_SLUG}): sprint ${SPRINT_NUM} cycle ${CYCLE_NUM}"
    else
        COMMIT_MSG="feat: sprint ${SPRINT_NUM} cycle ${CYCLE_NUM}"
    fi
    COMMIT_MSG="$COMMIT_MSG

Automatic commit after AI Dev Team run.
Mode: $MODE | Time: $TIMESTAMP"

    if [ -n "$CODE_CHANGES" ]; then
        COMMIT_MSG="$COMMIT_MSG

Changed files (code):
$CODE_CHANGES"
    fi

    git commit -m "$COMMIT_MSG"

    # --- Push feature branch ---
    git push "$AUTH_URL" "$BRANCH_NAME" --force 2>&1 | sanitize_output || true
    echo "$(date) [INFO] Git: pushed branch $BRANCH_NAME"

    # --- Create/update MR via provider API ---
    echo "$(date) [INFO] Creating Merge Request..."
    BRANCH_NAME="$BRANCH_NAME" SPRINT_NUM="$SPRINT_NUM" CYCLE_NUM="$CYCLE_NUM" \
    STORY_SLUG="${STORY_SLUG:-}" MODE="$MODE" CODE_CHANGES="${CODE_CHANGES:-}" \
    python3 -c "
import os, sys, json, urllib.request, urllib.parse

url = os.environ.get('GITLAB_URL', '')
token = os.environ.get('GITLAB_TOKEN', '')
project = os.environ.get('GITLAB_PROJECT_ID', '')
branch_name = os.environ.get('BRANCH_NAME', '')
sprint_num = os.environ.get('SPRINT_NUM', '0')
cycle_num = os.environ.get('CYCLE_NUM', '0')
story_slug = os.environ.get('STORY_SLUG', '')
mode = os.environ.get('MODE', '')
code_changes = os.environ.get('CODE_CHANGES', '')

if not all([url, token, project]):
    print('  MR: missing configuration, skipping')
    sys.exit(0)

encoded_project = urllib.parse.quote(project, safe='')
api_base = f'{url}/api/v4/projects/{encoded_project}'

# Check existing MR for this branch
check_url = f'{api_base}/merge_requests?source_branch={urllib.parse.quote(branch_name)}&state=opened'
req = urllib.request.Request(check_url, headers={'PRIVATE-TOKEN': token})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        existing = json.loads(resp.read())
except Exception as e:
    print(f'  MR: error checking: {e}')
    sys.exit(0)

if existing:
    print(f'  MR !{existing[0][\"iid\"]} already exists — OK')
    sys.exit(0)

# Create new MR
title_slug = story_slug if story_slug else f'sprint-{sprint_num}'
mr_data = json.dumps({
    'source_branch': branch_name,
    'target_branch': 'main',
    'title': f'AI Team: {title_slug} (S{sprint_num}C{cycle_num})',
    'description': f'''## AI Dev Team — automatic MR

**Sprint**: {sprint_num} | **Cycle**: {cycle_num} | **Mode**: {mode}

### Code changes
{code_changes}

---
*Created automatically by the ai-team orchestrator.*
''',
    'remove_source_branch': True,
}).encode()

req = urllib.request.Request(
    f'{api_base}/merge_requests',
    data=mr_data,
    method='POST',
    headers={'PRIVATE-TOKEN': token, 'Content-Type': 'application/json'}
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        mr = json.loads(resp.read())
        print(f'  MR !{mr[\"iid\"]} created: {mr[\"web_url\"]}')
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')
    print(f'  MR error {e.code}: {body[:200]}')
except Exception as e:
    print(f'  MR error: {e}')
" 2>&1 || echo "$(date) [WARN] MR creation failed (non-critical)"

    # Return to main
    git checkout main 2>/dev/null || true
    cd "$PROJECT_DIR"
}

GIT_SYNC

# ---- Board Sync: backlog/sprint -> GitLab/GitHub Issues ----
echo "$(date) [INFO] Board sync..."
python3 "$SCRIPT_DIR/sync_board.py" 2>&1 || echo "$(date) [WARN] Board sync failed (non-critical)"

# =============================================================================
# STRUCTURED LOG (JSON) — for parseable audit
# =============================================================================
LOG_JSON_DIR="$PROJECT_DIR/logs/runs"
mkdir -p "$LOG_JSON_DIR"

CYCLE_LOG=$(PROJECT_DIR="$PROJECT_DIR" LOG_JSON_DIR="$LOG_JSON_DIR" MODE="$MODE" python3 -c "
import json, yaml, os
from datetime import datetime

project_dir = os.environ.get('PROJECT_DIR', '')
log_json_dir = os.environ.get('LOG_JSON_DIR', '')
mode = os.environ.get('MODE', '')

project_file = os.path.join(project_dir, 'config', 'project.yaml')
try:
    with open(project_file) as f:
        cfg = yaml.safe_load(f)
    sprint = cfg.get('sprint', {})
except:
    sprint = {}

# Load last run log (agent-level details)
latest = os.path.join(log_json_dir, 'latest.json')
agent_details = []
try:
    with open(latest) as f:
        run = json.load(f)
    agent_details = run.get('agents', [])
except:
    pass

failed = [a['agent'] for a in agent_details if a.get('error')]
ok = [a['agent'] for a in agent_details if not a.get('error')]

log = {
    'timestamp': datetime.now().isoformat(),
    'mode': mode,
    'sprint': sprint.get('current_sprint', 0),
    'cycle': sprint.get('current_cycle', 0),
    'agents_ok': ok,
    'agents_failed': failed,
    'agents_ok_count': len(ok),
    'agents_failed_count': len(failed),
    'status': 'error' if failed else 'ok',
    'git_sync': os.environ.get('GIT_REPO_URL', '') != '',
    'gitlab_sync': os.environ.get('GITLAB_TOKEN', '') != '',
}

# Write cycle-level log
fname = datetime.now().strftime('cycle_%Y%m%d_%H%M%S.json')
with open(os.path.join(log_json_dir, fname), 'w') as f:
    json.dump(log, f, indent=2, ensure_ascii=False)

print(json.dumps(log))
" 2>/dev/null || echo '{}')

echo ""
echo "$(date) [INFO] Cycle completed."
echo "  Log: $CYCLE_LOG"

# =============================================================================
# ALERTING — notifications on agent failure
# =============================================================================
FAILED_AGENTS=$(echo "$CYCLE_LOG" | python3 -c "
import sys, json
try:
    log = json.load(sys.stdin)
    failed = log.get('agents_failed', [])
    if failed:
        print(','.join(failed))
except:
    pass
" 2>/dev/null)

if [ -n "$FAILED_AGENTS" ]; then
    ALERT_MSG="[AI Dev Team ALERT] Failed agents: $FAILED_AGENTS ($(date), mode: $MODE)"
    echo "$(date) [ALERT] $ALERT_MSG"

    # Alert to file (always)
    echo "$ALERT_MSG" >> "$PROJECT_DIR/logs/alerts.log"

    # Alert via provider issue (if configured)
    FAILED_AGENTS="$FAILED_AGENTS" MODE="$MODE" PROJECT_DIR="$PROJECT_DIR" \
    python3 -c "
import os, sys
project_dir = os.environ.get('PROJECT_DIR', '')
failed_agents = os.environ.get('FAILED_AGENTS', '')
mode = os.environ.get('MODE', '')
sys.path.insert(0, project_dir)
from integrations.providers import detect_provider
client = detect_provider()
if client and client.enabled:
    from datetime import datetime
    now = datetime.now()
    title = f'[Alert] Agent failure: {failed_agents} ({now.strftime(\"%Y-%m-%d %H:%M\")})'
    body = f'''## Agent Failure Alert

**Time**: {now.isoformat()}
**Mode**: {mode}
**Failed**: {failed_agents}

Check logs in \`logs/runs/\` for details.

---
*Automatic alert from the AI Dev Team orchestrator.*
'''
    result = client.create_issue(title, body, labels=['alert', 'bug'])
    if isinstance(result, dict) and 'iid' in result:
        print(f'  Alert issue #{result[\"iid\"]} created on provider')
    else:
        print(f'  Alert issue failed: {result}')
else:
    print('  Provider not configured, local log only')
" 2>&1 || true
fi

echo "============================================"
