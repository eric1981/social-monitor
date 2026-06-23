"""Accounts — list, detail, growth, toggle"""

from datetime import datetime, timedelta

from db import get_db
from utils import json_response, read_body, validate_int


def handle(handler, method, path):
    if method == "GET":
        return _handle_get(handler, path)
    if method == "POST":
        return _handle_post(handler, path)
    return False


def _handle_get(handler, path):
    if path == "/api/accounts":
        return _list_accounts(handler)
    if path.startswith("/api/account/"):
        return _account_detail(handler, path)
    if path == "/api/compare":
        return _compare(handler)
    return False


def _handle_post(handler, path):
    if path == "/api/account/toggle":
        return _toggle(handler)
    return False


def _list_accounts(handler):
    conn = get_db()
    accounts = [
        dict(r)
        for r in conn.execute(
            "SELECT id, platform, account_name, nickname, is_active, "
            "follower_count, total_digg_count, total_play_count, "
            "total_following_count, profile_bio, profile_douyin_id, "
            "profile_avatar_url, profile_like_count, cookie_status "
            "FROM accounts ORDER BY platform, id"
        )
    ]
    # Health score per account
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    for a in accounts:
        aid = a["id"]
        rows = conn.execute("""
            SELECT v.id, MAX(s.collected_at) as last_collected, s.play_count
            FROM videos v
            JOIN snapshots s ON s.video_id = v.id
            WHERE v.account_id = ? AND s.collected_at >= ?
            GROUP BY v.id
            ORDER BY s.collected_at DESC
        """, (aid, seven_days_ago)).fetchall()
        if len(rows) >= 2:
            plays = [r["play_count"] for r in rows]
            latest = plays[0]
            avg = sum(plays) / len(plays)
            if latest > avg * 1.2:
                a["health_level"] = "green"
                a["health_score"] = round(90 - (latest - avg * 1.2) / avg * 10, 1)
                a["health_score"] = max(70, min(100, a["health_score"]))
                a["health_detail"] = (
                    f"最新播放 {latest:,} › 7日均值 {int(avg):,} "
                    f"(↑{int((latest / avg - 1) * 100)}%)"
                )
            elif latest < avg * 0.8:
                a["health_level"] = "red"
                a["health_score"] = round(30 - (avg * 0.8 - latest) / avg * 30, 1)
                a["health_score"] = max(0, min(50, a["health_score"]))
                a["health_detail"] = (
                    f"最新播放 {latest:,} ‹ 7日均值 {int(avg):,} "
                    f"(↓{int((1 - latest / avg) * 100)}%)"
                )
            else:
                a["health_level"] = "yellow"
                a["health_score"] = round(60 + (latest - avg) / avg * 20, 1)
                a["health_score"] = max(50, min(80, a["health_score"]))
                a["health_detail"] = f"最新播放 {latest:,} ≈ 7日均值 {int(avg):,}"
        elif len(rows) == 1:
            a["health_level"] = "yellow"
            a["health_score"] = 50
            a["health_detail"] = "仅1条数据，无法对比"
        else:
            a["health_level"] = "gray"
            a["health_score"] = 0
            a["health_detail"] = "7天内无数据"
    conn.close()
    json_response(handler, {"accounts": accounts})
    return True


def _account_detail(handler, path):
    parts = path.split("/")
    account_id = parts[3] if len(parts) >= 4 else ""
    platform_filter = parts[4] if len(parts) >= 5 else None

    # /api/account/<id>/growth
    if platform_filter == "growth":
        conn = get_db()
        account = conn.execute(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not account:
            json_response(handler, {"error": "账号不存在"}, 404)
            conn.close()
            return True
        related = conn.execute(
            "SELECT id FROM accounts WHERE account_name=?",
            (account["account_name"],),
        ).fetchall()
        related_ids = [r["id"] for r in related]
        placeholders = ",".join("?" * len(related_ids))
        rows = conn.execute(
            f"""
            SELECT DATE(s.collected_at) as d,
                   SUM(s.play_count) as total_play, SUM(s.digg_count) as total_digg,
                   SUM(s.comment_count) as total_comment
            FROM snapshots s JOIN videos v ON s.video_id=v.id
            WHERE v.account_id IN ({placeholders})
            GROUP BY DATE(s.collected_at) ORDER BY d
            """,
            related_ids,
        ).fetchall()
        conn.close()
        points = [
            {
                "date": r["d"],
                "play": r["total_play"],
                "digg": r["total_digg"],
                "comment": r["total_comment"],
            }
            for r in rows
        ]
        json_response(handler, {"points": points})
        return True

    conn = get_db()
    account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not account:
        json_response(handler, {"error": "账号不存在"}, 404)
        conn.close()
        return True

    account = dict(account)
    related_accounts = conn.execute(
        "SELECT * FROM accounts WHERE account_name=? ORDER BY platform",
        (account["account_name"],),
    ).fetchall()

    total_followers = sum(r["follower_count"] or 0 for r in related_accounts)
    total_digg = sum(r["total_digg_count"] or 0 for r in related_accounts)
    total_play = sum(r["total_play_count"] or 0 for r in related_accounts)

    by_platform = {}
    all_videos = []

    for ra in related_accounts:
        p = ra["platform"]
        video_rows = conn.execute("""
            SELECT v.id, v.platform, v.account_name, v.aweme_id, v.title,
                   v.first_seen, v.url, v.cover_url,
                   s.collected_at, s.play_count, s.digg_count,
                   s.comment_count, s.share_count, s.collect_count
            FROM videos v
            JOIN snapshots s ON s.video_id = v.id
            WHERE v.account_id = ?
              AND s.collected_at = (
                  SELECT MAX(s2.collected_at) FROM snapshots s2
                  WHERE s2.video_id = s.video_id
              )
            ORDER BY s.collected_at DESC
        """, (ra["id"],)).fetchall()

        videos = [dict(r) for r in video_rows]
        all_videos.extend(videos)
        total_video_play = sum(v.get("play_count", 0) or 0 for v in videos)
        total_video_digg = sum(v.get("digg_count", 0) or 0 for v in videos)

        by_platform[p] = {
            "account": dict(ra),
            "videos": videos if not platform_filter or p == platform_filter else [],
            "video_count": len(videos),
            "total_play": total_video_play,
            "total_digg": total_video_digg,
        }

    if platform_filter:
        all_videos = by_platform.get(platform_filter, {}).get("videos", [])

    result = {
        "account": account,
        "related_accounts": [dict(r) for r in related_accounts],
        "summary": {
            "total_followers": total_followers,
            "total_digg": total_digg,
            "total_play": total_play,
            "total_videos": len(all_videos),
            "platforms": list(by_platform.keys()),
            "stats_updated": account.get("account_stats_updated", ""),
        },
        "by_platform": by_platform,
        "videos": all_videos,
    }
    conn.close()
    json_response(handler, result)
    return True


def _compare(handler):
    conn = get_db()
    rows = conn.execute("""
        SELECT a.id, a.account_name, a.platform, a.nickname, a.cookie_status,
               a.follower_count, a.total_digg_count, a.total_play_count,
               a.group_id, g.group_name
        FROM accounts a
        LEFT JOIN groups g ON g.id = a.group_id
        WHERE a.is_active=1
        ORDER BY COALESCE(g.group_name, a.account_name), a.platform
    """).fetchall()

    seven_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    fourteen_ago = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    growth_rows = conn.execute("""
        WITH per_video AS (
            SELECT v.account_id,
                   (SELECT s.play_count FROM snapshots s
                    WHERE s.video_id = v.id AND s.collected_at >= ?
                    ORDER BY s.collected_at DESC LIMIT 1) as recent_play,
                   (SELECT s.play_count FROM snapshots s
                    WHERE s.video_id = v.id AND s.collected_at >= ? AND s.collected_at < ?
                    ORDER BY s.collected_at DESC LIMIT 1) as prior_play
            FROM videos v
        )
        SELECT account_id,
               COALESCE(SUM(recent_play), 0) as recent_total,
               COALESCE(SUM(prior_play), 0) as prior_total
        FROM per_video
        GROUP BY account_id
    """, (seven_ago, fourteen_ago, seven_ago)).fetchall()
    growth_map = {}
    for gr in growth_rows:
        growth_map[gr["account_id"]] = gr["recent_total"] - gr["prior_total"]
    conn.close()

    groups = {}
    for r in rows:
        if r["group_id"]:
            key = "g:" + str(r["group_id"])
            label = r["group_name"] or f'分组{r["group_id"]}'
        else:
            key = "u:" + r["account_name"]
            label = r["nickname"] or r["account_name"]
        if key not in groups:
            groups[key] = {"id": key, "label": label, "platforms": {}}
        growth = growth_map.get(r["id"], 0)
        groups[key]["platforms"][r["platform"]] = {
            "nickname": r["nickname"],
            "cookie_status": r["cookie_status"],
            "followers": r["follower_count"],
            "diggs": r["total_digg_count"],
            "plays": r["total_play_count"],
            "account_name": r["account_name"],
            "growth_plays": growth,
        }
    json_response(handler, {"groups": list(groups.values())})
    return True


def _toggle(handler):
    body = read_body(handler)
    import json

    data = json.loads(body)
    account_id = data.get("id")
    is_active = data.get("is_active", 1)
    if not isinstance(account_id, int):
        json_response(handler, {"error": "账号ID无效"}, 400)
        return True
    if not isinstance(is_active, int) or is_active not in (0, 1):
        json_response(handler, {"error": "状态值无效，需要 0 或 1"}, 400)
        return True
    conn = get_db()
    conn.execute("UPDATE accounts SET is_active=? WHERE id=?", (is_active, account_id))
    conn.commit()
    conn.close()
    json_response(handler, {"status": "ok"})
    return True
