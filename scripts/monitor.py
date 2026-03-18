#!/usr/bin/env python3
"""
AI Dev Team — Monitoring & Reporting
Displays run statistics, costs, and project status.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.logging_config import setup_logging
logger = setup_logging("monitor")

LOGS_DIR = Path(__file__).parent.parent / "logs" / "runs"


def load_logs(days: int = 7) -> list[dict[str, Any]]:
    """Load logs from the last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    logs = []

    if not LOGS_DIR.exists():
        return logs

    for log_file in sorted(LOGS_DIR.glob("*.json")):
        if log_file.name == "latest.json":
            continue
        try:
            ts = datetime.strptime(log_file.stem, "%Y%m%d_%H%M%S")
            if ts >= cutoff:
                with open(log_file) as f:
                    data = json.load(f)
                    data["_timestamp"] = ts
                    logs.append(data)
        except (ValueError, json.JSONDecodeError):
            continue

    return logs


def report_summary(days: int = 7) -> None:
    """Display summary report."""
    logs = load_logs(days)

    if not logs:
        print(f"📊 No logs for the last {days} days.")
        return

    total_context = sum(
        sum(a.get("context_chars", 0) for a in l.get("agents", []))
        for l in logs
    )
    total_response = sum(
        sum(a.get("response_chars", 0) for a in l.get("agents", []))
        for l in logs
    )
    total_cycles = len(logs)

    # Daily breakdown
    daily = defaultdict(lambda: {"cycles": 0, "chars": 0})
    for l in logs:
        day = l["_timestamp"].strftime("%Y-%m-%d")
        daily[day]["cycles"] += 1
        daily[day]["chars"] += sum(
            a.get("context_chars", 0) + a.get("response_chars", 0)
            for a in l.get("agents", [])
        )

    # Agent breakdown
    agent_stats = defaultdict(lambda: {"runs": 0, "context": 0, "response": 0})
    for l in logs:
        for a in l.get("agents", []):
            name = a["agent"]
            agent_stats[name]["runs"] += 1
            agent_stats[name]["context"] += a.get("context_chars", 0)
            agent_stats[name]["response"] += a.get("response_chars", 0)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║          AI Dev Team — Report ({days} days)               ║
╠══════════════════════════════════════════════════════════╣
║  Total cycles:      {total_cycles:<37}║
║  Total chars:       {total_context + total_response:<37}║
║    - Context:       {total_context:<37}║
║    - Response:      {total_response:<37}║
║  Avg context/cycle: {total_context // max(total_cycles, 1):<37}║
║  Avg response/cycle:{total_response // max(total_cycles, 1):<37}║
╠══════════════════════════════════════════════════════════╣
║  Daily overview                                         ║
╠══════════════════════════════════════════════════════════╣""")

    for day in sorted(daily.keys()):
        d = daily[day]
        print(f"║  {day}:  {d['cycles']:>3} cycles  {d['chars']:>12} chars       ║")

    print(f"""╠══════════════════════════════════════════════════════════╣
║  Agents                                                 ║
╠══════════════════════════════════════════════════════════╣""")

    for name in sorted(agent_stats.keys()):
        s = agent_stats[name]
        total = s["context"] + s["response"]
        print(f"║  {name:<20} {s['runs']:>4} runs  {total:>10} chars    ║")

    print(f"╚══════════════════════════════════════════════════════════╝")


def report_last() -> None:
    """Display last run."""
    latest = LOGS_DIR / "latest.json"
    if not latest.exists():
        print("No log.")
        return

    with open(latest) as f:
        data = json.load(f)

    print(f"\n📋 Last cycle: {data.get('timestamp', '?')}")
    for a in data.get("agents", []):
        ctx = a.get("context_chars", 0)
        resp = a.get("response_chars", 0)
        err = f" [ERROR: {a['error']}]" if a.get("error") else ""
        print(f"   - {a['agent']}: {ctx} ctx / {resp} resp{err}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7

    if cmd == "summary":
        report_summary(days)
    elif cmd == "last":
        report_last()
    else:
        print(f"Usage: python monitor.py [summary|last] [days]")
