#!/usr/bin/env python3
"""Cron wrapper: run scheduled_collect.py, output ONLY on failures/alerts (watchdog pattern).
When stdout is empty → Hermes cronjob stays silent. When non-empty → delivered as notification."""
import json
import subprocess
import sys
from pathlib import Path

MONITOR_DIR = Path(__file__).parent

def main():
    result = subprocess.run(
        [sys.executable, str(MONITOR_DIR / 'scheduled_collect.py')],
        capture_output=True, text=True, timeout=3600,
        cwd=str(MONITOR_DIR)
    )

    summary_path = MONITOR_DIR / 'collect_summary.json'
    if not summary_path.exists():
        if result.returncode != 0:
            print(f"采集异常退出 (exit={result.returncode})")
            if result.stderr:
                print(result.stderr[-500:])
        # No summary = nothing to report → silent
        return result.returncode

    try:
        with open(summary_path) as f:
            summary = json.load(f)
    except Exception:
        return result.returncode

    alerts = summary.get('alerts', [])
    fail_count = summary.get('fail_count', 0)
    success_count = summary.get('success_count', 0)
    total = summary.get('total_accounts', 0)
    timestamp = summary.get('timestamp', '?')

    # Only output if there are failures or alerts
    if fail_count == 0 and not alerts:
        # All good → silent
        return 0

    lines = [f"📡 Social Monitor — {timestamp}"]
    lines.append(f"账号: {success_count}/{total} 成功")

    if fail_count > 0:
        lines.append(f"❌ {fail_count} 个账号采集失败:")
        for err in summary.get('errors', []):
            lines.append(f"  - {err['platform']}/{err['account']}: {err.get('message', '?')}")

    if alerts:
        lines.append(f"🚨 预警 ({len(alerts)} 项):")
        for a in alerts:
            if a.get('type') == 'cookie_expiring':
                lines.append(f"  ⚠️ Cookie过期: {a['nickname']} ({a['platform']}) 还剩{a['days_left']}天")
            elif a.get('type') == 'consecutive_failure':
                lines.append(f"  🚨 连续失败: {a['nickname']} ({a['platform']}) 已连续失败{a['consecutive_failures']}次")

    print('\n'.join(lines))
    return result.returncode

if __name__ == '__main__':
    sys.exit(main())
