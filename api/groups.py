"""Groups — GET/POST /api/groups"""

import json

from db import get_db
from utils import json_response, read_body, validate_str


def handle(handler, method, path):
    if path != "/api/groups":
        return False

    if method == "GET":
        conn = get_db()
        gs = conn.execute("SELECT * FROM groups ORDER BY group_name").fetchall()
        result = []
        for g in gs:
            members = conn.execute(
                "SELECT id, platform, account_name, nickname FROM accounts "
                "WHERE group_id=? ORDER BY platform",
                (g["id"],),
            ).fetchall()
            result.append(
                {
                    "id": g["id"],
                    "name": g["group_name"],
                    "members": [dict(m) for m in members],
                }
            )
        ungrouped = conn.execute(
            "SELECT id, platform, account_name, nickname FROM accounts "
            "WHERE is_active=1 AND group_id IS NULL ORDER BY platform, account_name"
        ).fetchall()
        conn.close()
        json_response(handler, {"groups": result, "ungrouped": [dict(u) for u in ungrouped]})
        return True

    if method == "POST":
        body = read_body(handler)
        data = json.loads(body)
        action = data.get("action", "")
        conn = get_db()
        try:
            if action == "create":
                name = data.get("name", "").strip()
                err = validate_str(name, "分组名", 50)
                if err:
                    json_response(handler, {"error": err}, 400)
                    return True
                conn.execute("INSERT OR IGNORE INTO groups (group_name) VALUES (?)", (name,))
                conn.commit()
                gid = conn.execute(
                    "SELECT id FROM groups WHERE group_name=?", (name,)
                ).fetchone()[0]
                for aid in data.get("account_ids") or []:
                    if not isinstance(aid, int):
                        continue
                    conn.execute("UPDATE accounts SET group_id=? WHERE id=?", (gid, aid))
                conn.commit()
                json_response(handler, {"status": "ok", "id": gid})

            elif action == "delete":
                gid = data.get("id")
                if not isinstance(gid, int):
                    json_response(handler, {"error": "分组ID无效"}, 400)
                    return True
                conn.execute("UPDATE accounts SET group_id=NULL WHERE group_id=?", (gid,))
                conn.execute("DELETE FROM groups WHERE id=?", (gid,))
                conn.commit()
                json_response(handler, {"status": "ok"})

            elif action == "add_member":
                gid = data.get("group_id")
                aid = data.get("account_id")
                if not isinstance(gid, int) or not isinstance(aid, int):
                    json_response(handler, {"error": "参数无效"}, 400)
                    return True
                conn.execute("UPDATE accounts SET group_id=? WHERE id=?", (gid, aid))
                conn.commit()
                json_response(handler, {"status": "ok"})

            elif action == "remove_member":
                aid = data.get("account_id")
                if not isinstance(aid, int):
                    json_response(handler, {"error": "账号ID无效"}, 400)
                    return True
                conn.execute("UPDATE accounts SET group_id=NULL WHERE id=?", (aid,))
                conn.commit()
                json_response(handler, {"status": "ok"})

            elif action == "rename":
                gid = data.get("id")
                name = data.get("name", "").strip()
                if not isinstance(gid, int):
                    json_response(handler, {"error": "分组ID无效"}, 400)
                    return True
                err = validate_str(name, "分组名", 50)
                if err:
                    json_response(handler, {"error": err}, 400)
                    return True
                conn.execute("UPDATE groups SET group_name=? WHERE id=?", (name, gid))
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

    return False
