#!/usr/bin/env python3
"""
定时采集调度脚本 — 每天 6:00 执行，失败后每小时重试
被 cron 触发调用
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config

MONITOR_DIR = Path(__file__).parent
LOG_DIR = MONITOR_DIR / "logs"
LOG_FILE = LOG_DIR / f"collect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

MAX_RETRIES = config.schedule_max_retries()
RETRY_DELAY = config.schedule_retry_delay()
PLATFORMS = config.schedule_platforms()


def log(msg):
    msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(msg, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


def run_collector(platform):
    """运行采集器，返回 (成功数, 失败数)"""
    log(f"开始采集 {platform}...")
    result = subprocess.run(
        [sys.executable, str(MONITOR_DIR / 'collector.py'), '--platform', platform],
        capture_output=True, text=False, timeout=600
    )
    out = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
    err = result.stderr.decode('gbk', errors='replace') if result.stderr else ''

    if result.returncode == 0:
        log(f"{platform} 采集完成")
        return True, out
    else:
        log(f"{platform} 采集失败:\n{err[:500]}")
        return False, err


def main():
    log("="*50)
    log("定时采集开始")
    log(f"平台列表: {', '.join(PLATFORMS)}")
    log("="*50)

    # 是否有平台需要重试
    pending = list(PLATFORMS)

    for attempt in range(1, MAX_RETRIES + 1):
        if not pending:
            break

        if attempt > 1:
            log(f"\n第 {attempt} 轮重试 — 剩余: {', '.join(pending)}")
            log(f"等待 {RETRY_DELAY//60} 分钟后重试...")
            time.sleep(RETRY_DELAY)

        failed = []
        for platform in pending:
            success, output = run_collector(platform)
            if success:
                # 提取摘要行
                for line in output.split('\n'):
                    if '共' in line and '视频' in line:
                        log(f"  → {line.strip()}")
            else:
                failed.append(platform)

        pending = failed

    # 最终结果
    if pending:
        log(f"\n❌ 采集未完全成功，以下平台仍有失败: {', '.join(pending)}")
    else:
        log(f"\n✅ 全部平台采集完成")

    log(f"日志文件: {LOG_FILE}")
    log("="*50)


if __name__ == '__main__':
    main()
