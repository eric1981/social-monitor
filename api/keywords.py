"""Keywords — GET /api/keywords, /api/comments/matched, POST /api/keywords"""

import json
from urllib.parse import parse_qs

from db import get_db
from utils import json_response, read_body, validate_str, MAX_KEYWORD_LEN


def handle(handler, method, path):
    if method == "GET":
        return _handle_get(handler, path)
    if method == "POST" and path == "/api/keywords":
        return _handle_post(handler)
    return False


def _handle_get(handler, path):
    if path == "/api/keywords":
        conn = get_db()
        rows = conn.execute(
            "SELECT k.*, a.nickname as account_nick, a.platform as acct_platform "
            "FROM keywords k LEFT JOIN accounts a ON k.account_id = a.id "
            "ORDER BY k.created_at DESC"
        ).fetchall()
        conn.close()
        json_response(handler, {"keywords": [dict(r) for r in rows]})
        return True

    if path == "/api/comments/matched":
        conn = get_db()
        parsed = handler.parsed_path
        if parsed:
            qs = parse_qs(parsed.query)
        else:
            from urllib.parse import urlparse

            qs = parse_qs(urlparse(handler.path).query)
        kw = qs.get("keyword", [""])[0]
        limit_val = int(qs.get("limit", ["50"])[0])
        if kw:
            rows = conn.execute("""
                SELECT c.*, v.title as video_title, v.aweme_id,
                       a.nickname as account_nick, a.account_name
                FROM comments c
                JOIN videos v ON v.id = c.video_id
                JOIN accounts a ON a.id = v.account_id
                WHERE c.matched_kw LIKE ?
                ORDER BY c.digg_count DESC, c.collected_at DESC
                LIMIT ?
            """, (f"%{kw}%", limit_val)).fetchall()
        else:
            rows = conn.execute("""
                SELECT c.*, v.title as video_title, v.aweme_id,
                       a.nickname as account_nick, a.account_name
                FROM comments c
                JOIN videos v ON v.id = c.video_id
                JOIN accounts a ON a.id = v.account_id
                WHERE c.matched_kw != ''
                ORDER BY c.digg_count DESC, c.collected_at DESC
                LIMIT ?
            """, (limit_val,)).fetchall()
        conn.close()
        json_response(handler, {"comments": [dict(r) for r in rows]})
        return True

    return False


def _handle_post(handler):
    body = read_body(handler)
    data = json.loads(body)
    action = data.get("action", "")
    conn = get_db()
    try:
        if action == "add":
            kw = data.get("keyword", "").strip()
            err = validate_str(kw, "关键词", MAX_KEYWORD_LEN)
            if err:
                json_response(handler, {"error": err}, 400)
                return True
            platform = data.get("platform") or None
            account_id = data.get("account_id") or None
            conn.execute(
                "INSERT INTO keywords (keyword, platform, account_id) VALUES (?, ?, ?)",
                (kw, platform, account_id),
            )
            conn.commit()
            json_response(handler, {"status": "ok"})
        elif action == "delete":
            kid = data.get("id")
            if not isinstance(kid, int):
                json_response(handler, {"error": "关键词ID无效"}, 400)
                return True
            conn.execute("DELETE FROM keywords WHERE id=?", (kid,))
            conn.commit()
            json_response(handler, {"status": "ok"})
        elif action == "toggle":
            kid = data.get("id")
            if not isinstance(kid, int):
                json_response(handler, {"error": "关键词ID无效"}, 400)
                return True
            is_active = data.get("is_active", 0)
            if not isinstance(is_active, int) or is_active not in (0, 1):
                json_response(handler, {"error": "状态值无效，需要 0 或 1"}, 400)
                return True
            conn.execute("UPDATE keywords SET is_active=? WHERE id=?", (is_active, kid))
            conn.commit()
            json_response(handler, {"status": "ok"})
        else:
            json_response(handler, {"error": "unknown action"}, 400)
    except Exception as e:
        conn.rollback()
        json_response(handler, {"error": str(e)}, 500)
    finally:
        conn.close()
    return True
