"""Shared utilities for API handlers."""

import json
import os
import ipaddress
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import config
from db import MONITOR_DIR

COLLECTOR = MONITOR_DIR / "collector.py"

# ── Constants ──
MAX_BODY_LEN = 1024 * 100  # 100KB max POST body
MAX_STR_LEN = 256
MAX_KEYWORD_LEN = 100
VALID_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "shipinhao"}

# ── Response helpers ──


def json_response(handler, data, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length > MAX_BODY_LEN:
        return ""  # reject oversized body
    if length:
        return handler.rfile.read(length).decode("utf-8")
    return ""


# ── Process spawning ──


def spawn_script(*args):
    """Spawn a Python script using the correct interpreter.
    Under WSL, uses the configured Windows Python so Playwright works.
    In Docker/Linux, uses sys.executable directly.
    """
    # Detect Docker: /proc/1/cgroup contains 'docker' or /.dockerenv exists
    _in_docker = os.path.exists('/.dockerenv') or (
        os.path.exists('/proc/1/cgroup') and 'docker' in open('/proc/1/cgroup').read()
    )
    if config.is_wsl() and not _in_docker:
        win_path = config.windows_python_path()
        exe = win_path.replace("C:\\", "/mnt/c/").replace("\\", "/")
    else:
        exe = sys.executable

    if _in_docker:
        log_dir = MONITOR_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "spawn.log"
        stderr_fh = open(str(log_path), "a") if log_path else subprocess.DEVNULL
    else:
        stderr_fh = subprocess.DEVNULL

    return subprocess.Popen(
        [exe, *args],
        stdout=subprocess.DEVNULL,
        stderr=stderr_fh,
        cwd=str(MONITOR_DIR),
    )


# ── Validation ──


def validate_str(val, name="参数", max_len=MAX_STR_LEN, allow_empty=False):
    if not isinstance(val, str):
        return f"{name} 类型无效，需要字符串"
    if not allow_empty and not val.strip():
        return f"{name} 不能为空"
    if len(val) > max_len:
        return f"{name} 超过最大长度 {max_len}"
    return None


def validate_int(val, name="参数", min_v=None, max_v=None):
    if val is None:
        return f"{name} 不能为空"
    if not isinstance(val, (int, float)):
        return f"{name} 类型无效，需要数字"
    if min_v is not None and val < min_v:
        return f"{name} 不能小于 {min_v}"
    if max_v is not None and val > max_v:
        return f"{name} 不能大于 {max_v}"
    return None


def validate_platform(val):
    err = validate_str(val, "平台", 20)
    if err:
        return err
    if val not in VALID_PLATFORMS:
        return f'平台 "{val}" 无效，仅支持: {", ".join(sorted(VALID_PLATFORMS))}'
    return None


# ── CSV ──


def csv_quote(val):
    """将值转为 CSV 安全格式：必要时加双引号包裹，内嵌引号转义"""
    s = str(val or "")
    if "," in s or '"' in s or "\n" in s or "\r" in s:
        s = s.replace('"', '""')
        return f'"{s}"'
    return s


# ── SSRF protection ──


def is_safe_image_url(raw_url: str) -> bool:
    """检查图片代理 URL 是否安全（防 SSRF）"""
    try:
        u = urlparse(raw_url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not u.hostname:
        return False
    hostname = u.hostname.strip("[]")
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if addr.is_loopback or addr.is_private or addr.is_link_local:
            return False
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in resolved:
            ip = sockaddr[0]
            try:
                a = ipaddress.ip_address(ip)
                if a.is_loopback or a.is_private or a.is_link_local:
                    return False
            except ValueError:
                continue
    except socket.gaierror:
        return False
    for pat in config.image_proxy_allowed_patterns():
        if pat.match(hostname):
            return True
    return False
