"""
Social Monitor 配置模块
所有模块统一通过此文件读取配置，不再硬编码。
"""
import json
import re
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"

# ── 默认值（当配置文件缺失或不完整时的回退） ──
_DEFAULTS = {
    "server": {"port": 5408},
    "windows": {
        "base_dir": "C:\\Users\\NINGMEI\\Desktop\\social-monitor",
        "wsl_mount_base": "/mnt/c/Users/NINGMEI/Desktop/social-monitor",
        "scripts": {
            "douyin": "win_collector.py",
            "kuaishou": "win_kuaishou.py",
            "xiaohongshu": "win_xiaohongshu.py",
            "shipinhao": "win_shipinhao.py",
            "login": "win_login.py",
            "relogin": "win_relogin.py",
            "stats": "win_collect_stats.py",
        },
    },
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
    """递归合并 overlay 到 base（overlay 优先）"""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load() -> dict:
    """加载配置（含默认回退）"""
    cfg = json.loads(json.dumps(_DEFAULTS))  # 深拷贝默认值
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        _deep_merge(cfg, user_cfg)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


# ── 模块级缓存 ──
_cfg = None


def refresh():
    """强制重新加载配置（写入配置后调用）"""
    global _cfg
    _cfg = _load()


def get() -> dict:
    """获取完整配置"""
    global _cfg
    if _cfg is None:
        _cfg = _load()
    return _cfg


def save(new_config: dict) -> None:
    """保存配置到文件（merge 模式：只更新提供的字段）"""
    current = get()
    # 深度合并
    _deep_merge(current, new_config)
    # 写入文件，保留格式
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    # 重新加载缓存
    _cfg = current


# ── 便捷访问器 ──

def server_port() -> int:
    return get()["server"]["port"]


def windows_base_dir() -> str:
    return get()["windows"]["base_dir"]


def windows_wsl_base() -> str:
    return get()["windows"]["wsl_mount_base"]


def windows_script(name: str) -> str:
    """获取 Windows 侧脚本完整路径 (C:\\...\\xxx.py)"""
    base = windows_base_dir()
    script = get()["windows"]["scripts"].get(name, name)
    return rf"{base}\{script}"


def wsl_path(rel: str) -> str:
    """拼接 WSL 侧 mount 路径"""
    return str(Path(windows_wsl_base()) / rel)


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
    """返回编译好的正则表达式列表（用于 SSRF 检查）"""
    return [re.compile(p) for p in image_proxy_allowed_domains()]
