"""Health check — GET /api/health"""

from datetime import datetime, timedelta

from db import get_db
from utils import json_response


def handle(handler, method, path):
    if method != "GET" or path != "/api/health":
        return False

    conn = get_db()
    rows = conn.execute(
        "SELECT platform, COUNT(*) as total, "
        "SUM(CASE WHEN cookie_status='ok' THEN 1 ELSE 0 END) as ok "
        "FROM accounts WHERE is_active=1 GROUP BY platform"
    ).fetchall()

    stale = conn.execute("""
        SELECT v.platform, MAX(s.collected_at) as last_snap,
               CAST(julianday('now') - julianday(MAX(s.collected_at)) AS INTEGER) as days_stale
        FROM snapshots s JOIN videos v ON s.video_id=v.id
        WHERE v.platform IN ('douyin','kuaishou','xiaohongshu','shipinhao')
        GROUP BY v.platform
    """).fetchall()

    active_accounts = conn.execute(
        "SELECT id FROM accounts WHERE is_active=1"
    ).fetchall()
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    hl_counts = {"green": 0, "yellow": 0, "red": 0, "gray": 0}
    for acc in active_accounts:
        aid = acc["id"]
        video_rows = conn.execute("""
            SELECT v.id, MAX(s.collected_at) as last_collected, s.play_count
            FROM videos v
            JOIN snapshots s ON s.video_id = v.id
            WHERE v.account_id = ? AND s.collected_at >= ?
            GROUP BY v.id
            ORDER BY s.collected_at DESC
        """, (aid, seven_days_ago)).fetchall()
        if len(video_rows) >= 2:
            plays = [r["play_count"] for r in video_rows]
            latest_play = plays[0]
            avg_play = sum(plays) / len(plays)
            if latest_play > avg_play * 1.2:
                hl_counts["green"] += 1
            elif latest_play < avg_play * 0.8:
                hl_counts["red"] += 1
            else:
                hl_counts["yellow"] += 1
        elif len(video_rows) == 1:
            hl_counts["yellow"] += 1
        else:
            hl_counts["gray"] += 1
    conn.close()

    health = {}
    for r in rows:
        health[r["platform"]] = {
            "total": r["total"],
            "ok": r["ok"],
            "failed": r["total"] - r["ok"],
        }
    for r in stale:
        if r["platform"] in health:
            health[r["platform"]]["last_snap"] = r["last_snap"]
            health[r["platform"]]["days_stale"] = r["days_stale"]
    health["accounts_health"] = hl_counts
    json_response(handler, health)
    return True
