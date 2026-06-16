#!/usr/bin/env python3
"""Windows 侧扫码登录脚本 — 由 WSL server.py 的 /api/relogin 触发
使用桌面的 social-auto-upload 项目进行扫码，登录后同步 cookie 到 social-monitor。
用法: python win_relogin.py <platform> <account_name>
"""
import sys, asyncio, os, json, shutil

platform = sys.argv[1] if len(sys.argv) > 1 else 'douyin'
account_name = sys.argv[2] if len(sys.argv) > 2 else 'unknown'
USERPROFILE = os.environ['USERPROFILE']

# 使用桌面的 social-auto-upload 项目（完整，有 uploader 模块）
sau_dir = os.path.join(USERPROFILE, 'Desktop', 'social-auto-upload')
os.chdir(sau_dir)
sys.path.insert(0, sau_dir)

# 根据平台选对应的 setup 函数
if platform == 'douyin':
    from uploader.douyin_uploader.main import douyin_setup as login_fn
elif platform == 'kuaishou':
    from uploader.ks_uploader.main import kuaishou_setup as login_fn
elif platform == 'xiaohongshu':
    from uploader.xiaohongshu_uploader.main import xiaohongshu_setup as login_fn
elif platform == 'shipinhao':
    from uploader.tencent_uploader.main import tencent_setup as login_fn
else:
    print(f"不支持的平台: {platform}")
    sys.exit(1)

# cookie 文件在 social-auto-upload 自己的目录
account_file = os.path.join(sau_dir, 'cookies', f'{platform}_{account_name}.json')

print(f"正在打开浏览器扫码登录 {platform}/{account_name}...")
print(f"cookie: {account_file}")
r = asyncio.run(login_fn(account_file, handle=True, headless=False))
print(f"登录结果: {r}")

# douyin_setup 返回 bool，True=成功
if r:
    # 同步到 social-monitor 的 cookie 目录（WSL 侧也可访问）
    monitor_cookie_dir = os.path.join(USERPROFILE, 'Desktop', 'social-monitor',
                                       'social-auto-upload', 'cookies')
    os.makedirs(monitor_cookie_dir, exist_ok=True)
    dst = os.path.join(monitor_cookie_dir, f'{platform}_{account_name}.json')
    shutil.copy2(account_file, dst)
    print(f"✓ cookie 已同步到: {dst}")
    sys.exit(0)
else:
    print(f"✗ 登录失败")
    sys.exit(1)
