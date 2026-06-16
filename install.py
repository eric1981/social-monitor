#!/usr/bin/env python3
"""
Social Monitor — 跨平台安装脚本
自动检测系统、安装依赖、初始化数据库。

用法：
  python3 install.py           # 交互式安装
  python3 install.py --quick   # 快速安装（非交互）
  python3 install.py --start   # 安装后启动服务
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# ── 平台检测 ──────────────────────────────────────────

SYSTEM = platform.system()  # "Windows" | "Linux" | "Darwin"
IS_WSL = "microsoft" in platform.release().lower()
PROJECT_ROOT = Path(__file__).parent


def detect_platform():
    """返回用户友好的平台名称。"""
    if SYSTEM == "Windows":
        return "Windows"
    elif SYSTEM == "Linux" and IS_WSL:
        return "WSL (Windows Subsystem for Linux)"
    elif SYSTEM == "Linux":
        return "Linux"
    elif SYSTEM == "Darwin":
        return "macOS"
    return SYSTEM


def check_python():
    """检查 Python 版本。"""
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        print(f"❌ 需要 Python 3.9+，当前: {major}.{minor}")
        return False
    print(f"  ✓ Python {major}.{minor}")
    return True


def run(cmd, **kwargs):
    """执行命令并返回 (success, output)。"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=kwargs.pop("timeout", 300), **kwargs,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "命令超时"
    except FileNotFoundError:
        return False, f"命令未找到: {cmd[0]}"


def find_python():
    """定位 Python 解释器路径。"""
    # 优先用 sys.executable
    if Path(sys.executable).exists():
        return sys.executable
    # 回退：尝试常见路径
    for name in ["python3", "python"]:
        path = shutil.which(name)
        if path:
            return path
    return "python3"


def find_pip():
    """定位 pip。"""
    python = find_python()
    for cmd in [[python, "-m", "pip"], [sys.executable, "-m", "pip"]]:
        ok, _ = run(cmd + ["--version"])
        if ok:
            return cmd
    return None


# ── 安装步骤 ─────────────────────────────────────────

def step_install_pip_deps(quick=False):
    """安装 requirements.txt 中的 Python 依赖。"""
    print("\n📦 安装 Python 依赖...")
    req_file = PROJECT_ROOT / "requirements.txt"

    pip = find_pip()
    if not pip:
        print("  ❌ 找不到 pip")
        return False

    ok, out = run(pip + ["install", "-r", str(req_file)])
    if ok:
        print("  ✓ Python 依赖安装完成")
    else:
        print(f"  ❌ 安装失败:\n{out[-500:]}")
        if not quick:
            input("\n按 Enter 继续...")
    return ok


def step_install_playwright(quick=False):
    """安装 Playwright + Chromium。"""
    print("\n🎭 安装 Playwright + Chromium...")

    pip = find_pip()
    if not pip:
        return False

    # 安装 Playwright（如果还没装）
    ok, out = run(pip + ["install", "playwright"])
    if not ok:
        # 尝试 patchright 作为备选
        ok2, out2 = run(pip + ["install", "patchright"])
        if not ok2:
            print(f"  ❌ 安装失败:\n{out[-300:]}")
            return False
        browser_pkg = "patchright"
    else:
        browser_pkg = "playwright"

    print(f"  ✓ {browser_pkg} 已安装")

    # 安装 Chromium 浏览器
    print("  ⏳ 下载 Chromium（约 150MB，首次需要几分钟）...")
    python = find_python()
    ok, out = run([python, "-m", browser_pkg, "install", "chromium"], timeout=600)
    if ok:
        print("  ✓ Chromium 安装完成")
    else:
        # macOS/Linux 可能缺少系统库
        if SYSTEM in ("Linux", "Darwin"):
            print(f"  ⚠ Chromium 安装可能需要系统依赖:")
            if SYSTEM == "Linux":
                print("    运行: playwright install-deps chromium")
                if not quick:
                    ans = input("  是否自动安装系统依赖? [Y/n] ").strip().lower()
                    if ans != "n":
                        run([python, "-m", browser_pkg, "install-deps", "chromium"], timeout=300)
                        run([python, "-m", browser_pkg, "install", "chromium"], timeout=600)
            elif SYSTEM == "Darwin":
                print("    macOS 通常无需额外依赖，请手动重试:")
                print(f"    {python} -m {browser_pkg} install chromium")
        else:
            print(f"  ⚠ 安装 Chromium 失败，请手动运行:")
            print(f"    {python} -m {browser_pkg} install chromium")
    return True


def step_init_directories():
    """创建必要的目录。"""
    print("\n📁 创建目录...")
    dirs = [
        PROJECT_ROOT / "tmp",
        PROJECT_ROOT / "logs",
        PROJECT_ROOT / "social-auto-upload" / "cookies",
        PROJECT_ROOT / "social-auto-upload" / "cookies" / "tencent_uploader",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {d.relative_to(PROJECT_ROOT)}")


def step_init_database():
    """初始化数据库（如果不存在）。"""
    print("\n🗄 初始化数据库...")
    db_path = PROJECT_ROOT / "monitor.db"
    schema_path = PROJECT_ROOT / "schema.sql"

    if db_path.exists():
        print("  ✓ monitor.db 已存在，跳过初始化")
        return

    if not schema_path.exists():
        print("  ❌ schema.sql 未找到")
        return

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        print("  ✓ 数据库初始化完成")
    except Exception as e:
        print(f"  ❌ 初始化失败: {e}")
    finally:
        conn.close()


def step_check_config():
    """确保 config.json 存在。"""
    config_path = PROJECT_ROOT / "config.json"
    if not config_path.exists():
        print("\n⚙ 生成默认配置文件...")
        import json
        defaults = {
            "server": {"port": 5408},
            "collect": {"cookie_max_age_days": 30, "timeout_seconds": 120, "retry_delay_seconds": 3},
            "schedule": {"max_retries": 3, "retry_delay_seconds": 3600,
                         "platforms": ["douyin", "kuaishou", "xiaohongshu", "shipinhao"]},
            "snapshot_retention_days": 90,
            "image_proxy": {
                "referer": "https://www.kuaishou.com/",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "cache_max_age_seconds": 86400,
                "allowed_domains": [
                    ".*\\.douyinpic\\.com$", ".*\\.douyinvod\\.com$", ".*\\.douyin\\.com$",
                    ".*\\.snssdk\\.com$", ".*\\.byteimg\\.com$", ".*\\.bytecdn\\.com$",
                    ".*\\.yximgs\\.com$", ".*\\.kuaishou\\.com$", ".*\\.kuaishou\\.net$",
                    ".*\\.xhscdn\\.com$", ".*\\.xiaohongshu\\.com$",
                    ".*\\.wx\\.qlogo\\.cn$", ".*\\.qq\\.com$", ".*\\.gtimg\\.com$",
                    ".*\\.weixin\\.qq\\.com$", ".*\\.qpic\\.cn$",
                ],
            },
        }
        config_path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  ✓ config.json 已创建")
    else:
        print("\n⚙ config.json 已存在")


def step_verify():
    """验证安装是否可用。"""
    print("\n🔍 验证安装...")

    python = find_python()
    ok, out = run([python, "-c", "import config; print('config.py OK')"])
    if ok:
        print("  ✓ config.py 可导入")
    else:
        print(f"  ❌ config.py 导入失败: {out[:100]}")

    ok, out = run([python, "-c", "import sqlite3; print('sqlite3 OK')"])
    if ok:
        print("  ✓ sqlite3 可用")

    # 检查 Playwright
    ok, out = run([python, "-c", "from playwright.sync_api import sync_playwright; print('playwright OK')"])
    if not ok:
        ok, out = run([python, "-c", "from patchright.sync_api import sync_playwright; print('patchright OK')"])
    if ok:
        print("  ✓ Playwright/patchright 可用")
    else:
        print("  ⚠ Playwright 未安装（采集功能不可用，服务仍可启动）")


def print_banner():
    print("""
╔══════════════════════════════════════════╗
║       📡 Social Monitor Installer       ║
║          跨平台社交数据监控系统           ║
╚══════════════════════════════════════════╝
""")


# ── 主入口 ────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Social Monitor 安装脚本")
    parser.add_argument("--quick", action="store_true", help="非交互模式")
    parser.add_argument("--start", action="store_true", help="安装后启动服务")
    parser.add_argument("--skip-playwright", action="store_true", help="跳过 Playwright 安装")
    args = parser.parse_args()

    print_banner()
    print(f"  🖥 检测到系统: {detect_platform()}")
    print(f"  📂 项目目录: {PROJECT_ROOT}")
    print()

    # ── 检查 ──
    if not check_python():
        sys.exit(1)

    # ── 安装 ──
    step_init_directories()
    step_init_database()
    step_check_config()
    step_install_pip_deps(quick=args.quick)

    if not args.skip_playwright:
        step_install_playwright(quick=args.quick)
    else:
        print("\n⏭ 跳过 Playwright 安装（--skip-playwright）")

    step_verify()

    # ── 完成 ──
    print("\n" + "=" * 50)
    print("✅ 安装完成！")
    print()
    print("  启动服务:")
    print(f"    cd {PROJECT_ROOT}")
    print(f"    python3 server.py")
    print()
    print(f"  浏览器打开: http://localhost:5408")
    print("=" * 50)

    if args.start:
        print("\n🚀 启动服务...")
        os.chdir(str(PROJECT_ROOT))
        os.execv(find_python(), [find_python(), "server.py"])


if __name__ == "__main__":
    main()
