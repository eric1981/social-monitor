"""Data endpoints — GET /api/data, /api/stats/history, /api/alerts, /api/trend,
/api/export/accounts, /api/export/videos, POST /api/alerts/dismiss"""

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from db import get_db, MONITOR_DIR
from utils import json_response, read_body, csv_quote


def build_url(v):
    """Build platform video URL from aweme_id."""
    p = v["platform"]
    vid = v["aweme_id"]
    if p == "douyin":
        return f"https://www.douyin.com/video/{vid}"
    elif p == "kuaishou":
        return (
            f'https://www.kuaishou.com/short-video/{vid.replace("ks_", "")}'
            if vid.startswith("ks_")
            else ""
        )
    elif p == "xiaohongshu":
        return (
            f'https://www.xiaohongshu.com/discovery/item/{vid.replace("xhs_", "")}'
            if vid.startswith("xhs_")
            else ""
        )
    elif p == "shipinhao":
        return (
            f'https://channels.weixin.qq.com/post/{vid.replace("sph_", "")}'
            if vid.startswith("sph_")
            else ""
        )
    return ""


def handle(handler, method, path):
    if method == "GET":
        return _handle_get(handler, path)
    if method == "POST":
        return _handle_post(handler, path)
    return False


def _handle_get(handler, path):
    if path == "/api/data":
        return _query_data(handler)

    if path == "/api/stats/history":
        conn = get_db()
        parsed = handler.parsed_path
        if parsed:
            qs = parse_qs(parsed.query)
        else:
            from urllib.parse import urlparse
            qs = parse_qs(urlparse(handler.path).query)
        platform = qs.get("platform", ["all"])[0]
        if platform and platform != "all":
            rows = conn.execute("""
                SELECT DATE(s.collected_at) as d,
                       COUNT(DISTINCT s.video_id) as videos,
                       COUNT(*) as snapshots,
                       SUM(s.play_count) as total_play
                FROM snapshots s
                JOIN videos v ON v.id = s.video_id
                WHERE v.platform = ?
                GROUP BY DATE(s.collected_at)
                ORDER BY d
            """, (platform,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DATE(s.collected_at) as d,
                       COUNT(DISTINCT s.video_id) as videos,
                       COUNT(*) as snapshots,
                       SUM(s.play_count) as total_play
                FROM snapshots s
                GROUP BY DATE(s.collected_at)
                ORDER BY d
            """).fetchall()
        conn.close()
        points = [
            {
                "date": r["d"],
                "videos": r["videos"],
                "snapshots": r["snapshots"],
                "play": r["total_play"],
            }
            for r in rows
        ]
        json_response(handler, {"points": points})
        return True

    if path == "/api/alerts":
        summary_path = MONITOR_DIR / "collect_summary.json"
        alerts = []
        try:
            if summary_path.exists():
                with open(summary_path) as f:
                    summary = json.load(f)
                alerts = summary.get("alerts", [])
        except Exception:
            pass
        conn = get_db()
        failure_rows = conn.execute(
            "SELECT platform, account_name, nickname, consecutive_failures "
            "FROM accounts WHERE is_active=1 AND consecutive_failures >= 3"
        ).fetchall()
        conn.close()
        existing_failures = {
            a["account"] for a in alerts if a.get("type") == "consecutive_failure"
        }
        for fr in failure_rows:
            if fr["account_name"] not in existing_failures:
                alerts.append(
                    {
                        "platform": fr["platform"],
                        "account": fr["account_name"],
                        "nickname": fr["nickname"] or fr["account_name"],
                        "consecutive_failures": fr["consecutive_failures"],
                        "type": "consecutive_failure",
                    }
                )
        json_response(handler, {"alerts": alerts, "count": len(alerts)})
        return True

    if path == "/api/trend":
        conn = get_db()
        parsed = handler.parsed_path
        if parsed:
            qs = parse_qs(parsed.query)
        else:
            from urllib.parse import urlparse
            qs = parse_qs(urlparse(handler.path).query)
        video_id = qs.get("video_id", [None])[0]
        if not video_id:
            json_response(handler, {"error": "缺少 video_id"}, 400)
            return True
        rows = conn.execute("""
            SELECT s.collected_at, s.play_count, s.digg_count,
                   s.comment_count, s.share_count, s.collect_count,
                   v.title, v.platform, v.account_name
            FROM snapshots s
            JOIN videos v ON v.id = s.video_id
            WHERE s.video_id = ?
            ORDER BY s.collected_at
        """, (video_id,)).fetchall()
        conn.close()
        points = [
            {
                "collected_at": r["collected_at"][:16],
                "play": r["play_count"],
                "digg": r["digg_count"],
                "comment": r["comment_count"],
                "share": r["share_count"],
                "collect": r["collect_count"],
            }
            for r in rows
        ]
        meta = {
            "title": rows[0]["title"] if rows else "",
            "platform": rows[0]["platform"] if rows else "",
            "account": rows[0]["account_name"] if rows else "",
        }
        json_response(handler, {"meta": meta, "points": points})
        return True

    if path == "/api/export/accounts":
        conn = get_db()
        rows = conn.execute("""
            SELECT platform, account_name, nickname, cookie_status,
                   follower_count, total_digg_count, total_play_count,
                   account_stats_updated
            FROM accounts WHERE is_active=1 ORDER BY platform, id
        """).fetchall()
        conn.close()
        csv = "平台,账号名,昵称,Cookie状态,粉丝,获赞,播放,统计更新时间\n"
        for r in rows:
            csv += (
                f'{r["platform"]},{csv_quote(r["account_name"])},'
                f'{csv_quote(r["nickname"])},{r["cookie_status"]},'
                f'{r["follower_count"] or 0},{r["total_digg_count"] or 0},'
                f'{r["total_play_count"] or 0},{r["account_stats_updated"] or ""}\n'
            )
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8-sig")
        handler.send_header(
            "Content-Disposition", "attachment; filename=social-monitor-accounts.csv"
        )
        handler.end_headers()
        handler.wfile.write(csv.encode("utf-8-sig"))
        return True

    if path == "/api/export/videos":
        conn = get_db()
        parsed = handler.parsed_path
        if parsed:
            qs = parse_qs(parsed.query)
        else:
            from urllib.parse import urlparse
            qs = parse_qs(urlparse(handler.path).query)
        account_id = qs.get("account_id", [None])[0]
        if account_id:
            rows = conn.execute("""
                SELECT v.platform, v.account_name, v.title, v.aweme_id, v.first_seen,
                       s.play_count, s.digg_count, s.comment_count, s.share_count,
                       s.collect_count, s.collected_at
                FROM videos v JOIN snapshots s ON s.video_id=v.id
                WHERE v.account_id=?
                  AND s.collected_at=(
                      SELECT MAX(s2.collected_at) FROM snapshots s2
                      WHERE s2.video_id=v.id)
                ORDER BY s.play_count DESC
            """, (account_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT v.platform, v.account_name, v.title, v.aweme_id, v.first_seen,
                       s.play_count, s.digg_count, s.comment_count, s.share_count,
                       s.collect_count, s.collected_at
                FROM videos v JOIN snapshots s ON s.video_id=v.id
                WHERE s.collected_at=(
                    SELECT MAX(s2.collected_at) FROM snapshots s2
                    WHERE s2.video_id=v.id)
                ORDER BY v.platform, s.play_count DESC
            """).fetchall()
        conn.close()
        csv = "平台,账号,标题,视频ID,发布时间,播放,点赞,评论,分享,收藏,采集时间\n"
        for r in rows:
            csv += (
                f'{r["platform"]},{csv_quote(r["account_name"])},'
                f'{csv_quote(r["title"])},{r["aweme_id"]},'
                f'{r["first_seen"] or ""},{r["play_count"]},'
                f'{r["digg_count"]},{r["comment_count"]},'
                f'{r["share_count"]},{r["collect_count"]},'
                f'{r["collected_at"]}\n'
            )
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8-sig")
        handler.send_header(
            "Content-Disposition", "attachment; filename=social-monitor-videos.csv"
        )
        handler.end_headers()
        handler.wfile.write(csv.encode("utf-8-sig"))
        return True

    return False


def _handle_post(handler, path):
    if path == "/api/alerts/dismiss":
        body = read_body(handler)
        data = json.loads(body)
        alert_key = data.get("key", "")
        if not alert_key:
            json_response(handler, {"status": "error", "message": "缺少 key"}, 400)
            return True
        dismiss_path = MONITOR_DIR / "alert_dismissals.json"
        try:
            if dismiss_path.exists():
                with open(dismiss_path) as f:
                    dismissed = json.load(f)
            else:
                dismissed = []
            if alert_key not in dismissed:
                dismissed.append(alert_key)
            with open(dismiss_path, "w") as f:
                json.dump(dismissed, f)
            json_response(handler, {"status": "ok"})
        except Exception as e:
            json_response(handler, {"status": "error", "message": str(e)}, 500)
        return True

    return False


def _query_data(handler):
    """GET /api/data — main dashboard data"""
    conn = get_db()
    accounts = [
        dict(r)
        for r in conn.execute(
            "SELECT id, platform, account_name, nickname, is_active "
            "FROM accounts WHERE is_active=1"
        )
    ]
    nickname_map = {
        a["account_name"]: (a["nickname"] or a["account_name"]) for a in accounts
    }

    now = datetime.now()
    yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=1
    )
    yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_before_start = yesterday_start - timedelta(days=1)

    def day_snapshot_map(conn, day_start, day_end):
        rows = conn.execute("""
            SELECT s.video_id, s.play_count
            FROM snapshots s
            INNER JOIN (
                SELECT video_id, MAX(collected_at) as max_ts
                FROM snapshots
                WHERE collected_at >= ? AND collected_at < ?
                GROUP BY video_id
            ) latest ON s.video_id = latest.video_id
                  AND s.collected_at = latest.max_ts
        """, (day_start, day_end)).fetchall()
        return {r["video_id"]: r["play_count"] for r in rows}

    yesterday_plays = day_snapshot_map(
        conn,
        yesterday_start.strftime("%Y-%m-%d %H:%M:%S"),
        yesterday_end.strftime("%Y-%m-%d %H:%M:%S"),
    )
    day_before_plays = day_snapshot_map(
        conn,
        day_before_start.strftime("%Y-%m-%d %H:%M:%S"),
        yesterday_start.strftime("%Y-%m-%d %H:%M:%S"),
    )

    cur = conn.execute("""
        SELECT v.id, v.platform, v.account_name, v.aweme_id, v.title,
               v.first_seen, v.url, v.cover_url,
               s.collected_at, s.play_count, s.digg_count,
               s.comment_count, s.share_count, s.collect_count
        FROM videos v
        JOIN snapshots s ON s.video_id = v.id
        WHERE s.collected_at = (
            SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id = s.video_id
        )
    """)
    videos = []
    for r in cur:
        v = dict(r)
        raw = v.get("first_seen", "") or ""
        if "年" in raw:
            try:
                clean = raw.replace("定时发布 ", "").replace("发布于 ", "")
                parts = (
                    clean.replace("年", "-")
                    .replace("月", "-")
                    .replace("日", "")
                    .split(" ")
                )
                dparts = parts[0].split("-")
                if len(dparts) == 3:
                    v["first_seen"] = (
                        f"{dparts[0].strip()}-{dparts[1].strip().zfill(2)}-"
                        f"{dparts[2].strip().zfill(2)} "
                        f"{parts[1].strip() if len(parts) > 1 else '00:00'}:00"
                    )
            except Exception:
                pass
        today_play = v["play_count"]
        yesterday_play = yesterday_plays.get(v["id"], None)
        day_before_play = day_before_plays.get(v["id"], None)
        if yesterday_play is not None and day_before_play is not None:
            v["yesterday_views"] = yesterday_play - day_before_play
        elif yesterday_play is not None:
            v["yesterday_views"] = yesterday_play
        else:
            v["yesterday_views"] = 0
        if yesterday_play is not None:
            v["play_delta"] = today_play - yesterday_play
        else:
            v["play_delta"] = 0
        v["nickname"] = nickname_map.get(v["account_name"], v["account_name"])
        v["url"] = v.get("url") or build_url(v)
        videos.append(v)
    conn.close()
    json_response(handler, {"accounts": accounts, "videos": videos})
    return True
