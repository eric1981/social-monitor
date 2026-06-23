"""Collection — GET collect/log/summary, POST /api/collect, GET /api/collect/stats"""

import json

from db import MONITOR_DIR
from utils import json_response, read_body, spawn_script, COLLECTOR


def handle(handler, method, path):
    if method == "GET":
        if path == "/api/collect/log":
            log_path = MONITOR_DIR / "collect_status.json"
            if log_path.exists():
                try:
                    with open(log_path) as f:
                        st = json.load(f)
                    json_response(handler, st)
                except Exception:
                    json_response(handler, {"status": "idle", "lines": []})
            else:
                json_response(handler, {"status": "idle", "lines": []})
            return True

        if path == "/api/collect/summary":
            summary_path = MONITOR_DIR / "collect_summary.json"
            if summary_path.exists():
                try:
                    with open(summary_path) as f:
                        summary = json.load(f)
                    json_response(handler, summary)
                except Exception as e:
                    json_response(handler, {"error": str(e)}, 500)
            else:
                json_response(handler, {"status": "idle", "message": "暂无采集摘要"})
            return True

        if path == "/api/collect/stats":
            try:
                spawn_script(str(COLLECTOR), "--stats-only")
                json_response(handler, {"status": "ok"})
            except Exception as e:
                json_response(handler, {"status": "error", "message": str(e)}, 500)
            return True

    if method == "POST" and path == "/api/collect":
        try:
            log_path = MONITOR_DIR / "collect_status.json"
            with open(log_path, "w") as f:
                json.dump({"status": "running", "lines": []}, f)
            spawn_script(str(COLLECTOR))
            json_response(handler, {"status": "ok"})
        except Exception as e:
            json_response(handler, {"status": "error", "message": str(e)}, 500)
        return True

    return False
