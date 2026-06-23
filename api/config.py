"""Config — GET/POST /api/config"""

import config
from utils import json_response, read_body, validate_int


def handle(handler, method, path):
    if path != "/api/config":
        return False

    if method == "GET":
        json_response(handler, config.get())
        return True

    if method == "POST":
        body = read_body(handler)
        import json

        data = json.loads(body)
        port = data.get("server", {}).get("port")
        if port is not None:
            err = validate_int(port, "端口", 1024, 65535)
            if err:
                json_response(handler, {"status": "error", "message": err}, 400)
                return True
        timeout = data.get("collect", {}).get("timeout_seconds")
        if timeout is not None:
            err = validate_int(timeout, "采集超时", 10, 600)
            if err:
                json_response(handler, {"status": "error", "message": err}, 400)
                return True
        config.save(data)
        json_response(handler, {"status": "ok", "config": config.get()})
        return True

    return False
