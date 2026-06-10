#!/usr/bin/env python3
"""DB 维护：每周 VACUUM + 清理 90 天前的快照"""
import sqlite3, sys
from datetime import datetime, timedelta

DB = '/home/eric/social-monitor/monitor.db'

db = sqlite3.connect(DB)
cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
deleted = db.execute("DELETE FROM snapshots WHERE collected_at < ?", (cutoff,)).rowcount
db.execute("VACUUM")
db.commit()
db.close()
print(f"VACUUM done. Deleted {deleted} old snapshots (before {cutoff}).")
