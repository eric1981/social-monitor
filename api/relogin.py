"""Login / Relogin — QR login, relogin status, QR image"""

import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

from db import get_db, MONITOR_DIR
from utils import (
    json_response,
    read_body,
    spawn_script,
    validate_str,
    validate_platform,
)


def handle(handler, method, path):
    if method == "GET":
        return _handle_get(handler, path)
    if method == "POST":
        return _handle_post(handler, path)
    return False


def _handle_get(handler, path):
    if path == "/api/relogin/status":
        status_path = MONITOR_DIR / "relogin_status.json"
        if status_path.exists():
            try:
                with open(status_path) as f:
                    st = json.load(f)
                account_name = st.get("account_name", "")
                platform = st.get("platform", "")
                done_file = (
                    MONITOR_DIR
                    / "social-auto-upload"
                    / "cookies"
                    / f".{platform}_{account_name}_done"
                )
                if done_file.exists():
                    done_file.unlink(missing_ok=True)
                    st["status"] = "success"
                    st["message"] = "扫码登录成功"
                    with open(status_path, "w") as f:
                        json.dump(st, f, ensure_ascii=False)
                    conn = get_db()
                    conn.execute(
                        "UPDATE accounts SET cookie_status='ok', is_active=1 "
                        "WHERE platform=? AND account_name=?",
                        (platform, account_name),
                    )
                    conn.commit()
                    conn.close()
                json_response(handler, st)
            except Exception:
                json_response(handler, {"status": "idle", "message": "无扫码登录任务"})
        else:
            json_response(handler, {"status": "idle", "message": "无扫码登录任务"})
        return True

    if path == "/api/qr-login/status":
        qs = urlparse(handler.path).query
        params = dict(p.split("=") for p in qs.split("&") if "=" in p) if qs else {}
        token = params.get("token", "")
        if not token:
            json_response(handler, {"status": "error", "error": "missing token"}, 400)
            return True
        status_path = MONITOR_DIR / "tmp" / f"qr_{token}.json"
        if not status_path.exists():
            json_response(handler, {"status": "starting", "message": "正在生成二维码..."})
            return True
        try:
            with open(status_path) as f:
                st = json.load(f)
            if st.get("status") == "success":
                conn = get_db()
                conn.execute(
                    "UPDATE accounts SET cookie_status='ok', is_active=1 "
                    "WHERE platform=? AND account_name=?",
                    (st.get("platform", ""), st.get("account_name", "")),
                )
                conn.commit()
                conn.close()
                status_path.unlink(missing_ok=True)
                qr_img = MONITOR_DIR / "tmp" / f"qr_{token}.png"
                qr_img.unlink(missing_ok=True)
            json_response(handler, st)
        except Exception as e:
            json_response(handler, {"status": "error", "error": str(e)}, 500)
        return True

    if path == "/api/qr-image":
        qs = urlparse(handler.path).query
        params = dict(p.split("=") for p in qs.split("&") if "=" in p) if qs else {}
        token = params.get("token", "")
        if not token:
            handler.send_response(400)
            handler.end_headers()
            return True
        # First try the fixed path, then check JSON for douyin_cookie_gen's path
        status_file = MONITOR_DIR / "tmp" / f"qr_{token}.json"
        if status_file.exists():
            try:
                with open(status_file) as f:
                    st = json.load(f)
                img_file = st.get('qr_image_path', '')
                if img_file and Path(img_file).exists():
                    img_path = Path(img_file)
                else:
                    img_path = MONITOR_DIR / "tmp" / f"qr_{token}.png"
            except Exception:
                img_path = MONITOR_DIR / "tmp" / f"qr_{token}.png"
        else:
            img_path = MONITOR_DIR / "tmp" / f"qr_{token}.png"
        if not img_path.exists():
            handler.send_response(404)
            handler.end_headers()
            return True
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        with open(str(img_path), "rb") as f:
            handler.wfile.write(f.read())
        return True

    return False


def _handle_post(handler, path):
    if path == "/api/login":
        body = read_body(handler)
        data = json.loads(body)
        platform = data.get("platform", "")
        account_name = data.get("account_name", "")

        err = validate_platform(platform)
        if err:
            json_response(handler, {"error": err}, 400)
            return True
        err = validate_str(account_name, "账号名", 100)
        if err:
            json_response(handler, {"error": err}, 400)
            return True

        conn = get_db()
        dup = conn.execute(
            "SELECT id FROM accounts WHERE platform=? AND account_name=?",
            (platform, account_name),
        ).fetchone()
        if not dup:
            conn.execute(
                "INSERT OR IGNORE INTO accounts (platform, account_name, is_active) "
                "VALUES (?, ?, 0)",
                (platform, account_name),
            )
            conn.commit()
        conn.close()

        token = str(uuid.uuid4())[:8]
        spawn_script(str(MONITOR_DIR / "login_bridge.py"), token, platform, account_name)
        json_response(
            handler,
            {
                "status": "ok",
                "token": token,
                "message": f"二维码已生成，请用手机扫码登录 {platform}",
            },
        )
        return True

    if path.startswith("/api/relogin"):
        parts = path.split("/")
        if len(parts) >= 5:
            platform = parts[3]
            account_name = parts[4]
            err = validate_platform(platform)
            if err:
                json_response(handler, {"status": "error", "message": err}, 400)
                return True
            err = validate_str(account_name, "账号名", 100)
            if err:
                json_response(handler, {"status": "error", "message": err}, 400)
                return True
            try:
                import uuid as _uuid
                token = str(_uuid.uuid4())[:8]
                spawn_script(str(MONITOR_DIR / "login_bridge.py"), token, platform, account_name)
                json_response(
                    handler,
                    {
                        "status": "ok",
                        "token": token,
                        "message": f"二维码已生成，请扫码登录 {platform}/{account_name}",
                    },
                )
            except Exception as e:
                json_response(handler, {"status": "error", "message": str(e)}, 500)
        else:
            json_response(
                handler,
                {"status": "error", "message": "参数不足: /api/relogin/{platform}/{account}"},
                400,
            )
        return True

    return False
