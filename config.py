"""
Social Monitor 配置模块 — 跨平台（Windows / WSL / macOS / Linux）
所有模块统一通过此文件读取配置，不再硬编码。
"""
import json
import platform
import re
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"

# ── 平台检测 ──
_SYSTEM = platform.system()          # "Windows" | "Linux" | "Darwin"
_IS_WSL = "microsoft" in platform.release().lower()


def is_windows() -> bool:
    return _SYSTEM == "Windows"


def is_wsl() -> bool:
    return _SYSTEM == "Linux" and _IS_WSL


def is_macos() -> bool:
    return _SYSTEM == "Darwin"


def is_linux() -> bool:
    return _SYSTEM == "Linux" and not _IS_WSL


# ── 默认值 ──
_DEFAULTS = {
    "server": {"port": 5408},
    "collect": {
        "cookie_max_age_days": 30,
        "timeout_seconds": 120,
        "retry_delay_seconds": 3,
    },
    "schedule": {
        "max_retries": 3,
        "retry_delay_seconds": 3600,
        "platforms": ["douyin", "kuaishou", "xiaohongshu", "shipinhao"],
    },
    "snapshot_retention_days": 90,
    "image_proxy": {
        "referer": "https://www.kuaishou.com/",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "cache_max_age_seconds": 86400,
        "allowed_domains": [
            r".*\.douyinpic\.com$",
            r".*\.douyinvod\.com$",
            r".*\.douyin\.com$",
            r".*\.snssdk\.com$",
            r".*\.byteimg\.com$",
            r".*\.bytecdn\.com$",
            r".*\.yximgs\.com$",
            r".*\.kuaishou\.com$",
            r".*\.kuaishou\.net$",
            r".*\.xhscdn\.com$",
            r".*\.xiaohongshu\.com$",
            r".*\.xhs\.nuomi\.com$",
            r".*\.wx\.qlogo\.cn$",
            r".*\.qq\.com$",
            r".*\.gtimg\.com$",
            r".*\.weixin\.qq\.com$",
            r".*\.qpic\.cn$",
        ],
    },
}


def _deep_merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load() -> dict:
    cfg = json.loads(json.dumps(_DEFAULTS))
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        _deep_merge(cfg, user_cfg)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


_cfg = None


def refresh():
    global _cfg
    _cfg = _load()


def get() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = _load()
    return _cfg


def save(new_config: dict) -> None:
    current = get()
    _deep_merge(current, new_config)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    _cfg = current


# ── 便捷访问器 ──

def server_port() -> int:
    return get()["server"]["port"]


def collect_cookie_max_age_days() -> int:
    return get()["collect"]["cookie_max_age_days"]


def collect_timeout() -> int:
    return get()["collect"]["timeout_seconds"]


def collect_retry_delay() -> int:
    return get()["collect"]["retry_delay_seconds"]


def schedule_max_retries() -> int:
    return get()["schedule"]["max_retries"]


def schedule_retry_delay() -> int:
    return get()["schedule"]["retry_delay_seconds"]


def schedule_platforms() -> list:
    return list(get()["schedule"]["platforms"])


def snapshot_retention_days() -> int:
    return get()["snapshot_retention_days"]


def image_proxy_referer() -> str:
    return get()["image_proxy"]["referer"]


def image_proxy_user_agent() -> str:
    return get()["image_proxy"]["user_agent"]


def image_proxy_cache_max_age() -> int:
    return get()["image_proxy"]["cache_max_age_seconds"]


def image_proxy_allowed_domains() -> list:
    return list(get()["image_proxy"]["allowed_domains"])


def image_proxy_allowed_patterns() -> list:
    return [re.compile(p) for p in image_proxy_allowed_domains()]
