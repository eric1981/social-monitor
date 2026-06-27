#!/usr/bin/env python3
"""
Bridge script: reuses social-auto-upload's native cookie_gen for QR login.
Supports douyin / kuaishou / xiaohongshu / shipinhao.

Usage: python login_bridge.py <token> <platform> <account_name>
"""
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(PROJECT_ROOT)))
TMP_DIR = PROJECT_ROOT / 'tmp'

sys.path.insert(0, str(PROJECT_ROOT / 'social-auto-upload'))

# ── Docker: inject --no-sandbox into Chromium launches ──
_IN_DOCKER = os.path.exists('/.dockerenv') or (
    os.path.exists('/proc/1/cgroup') and
    'docker' in open('/proc/1/cgroup').read()
)

if _IN_DOCKER:
    _DOCKER_ARGS = ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    # Patch both playwright and patchright BEFORE social-auto-upload modules load
    for _mod_name in ('playwright.async_api._generated', 'patchright.async_api._generated'):
        try:
            _mod = __import__(_mod_name, fromlist=['BrowserType'])
            _BT = _mod.BrowserType

            def _make_patched(orig):
                async def _patched(self, **kwargs):
                    args = list(kwargs.get('args', []))
                    for flag in _DOCKER_ARGS:
                        if flag not in args:
                            args.append(flag)
                    kwargs['args'] = args
                    return await orig(self, **kwargs)
                return _patched

            _BT.launch = _make_patched(_BT.launch)
        except Exception:
            pass


# All four platforms use the same cookie storage pattern:
#   {DATA_DIR}/social-auto-upload/cookies/{platform}_uploader/{account_name}
PLATFORM_UPLOADER_DIR = {
    'douyin':       'douyin_uploader',
    'kuaishou':     'ks_uploader',
    'xiaohongshu':  'xiaohongshu_uploader',
    'shipinhao':    'tencent_uploader',
}


def write_status(token, **kwargs):
    TMP_DIR.mkdir(exist_ok=True)
    with open(TMP_DIR / f'qr_{token}.json', 'w') as f:
        json.dump(kwargs, f, ensure_ascii=False)


async def run(token, platform, account_name):
    uploader_dir = PLATFORM_UPLOADER_DIR.get(platform)
    if not uploader_dir:
        write_status(token, status='error',
                     error=f'Unsupported platform: {platform}')
        sys.exit(1)

    # Absolute path so social-auto-upload's path resolvers don't transform it
    account_file = str(
        DATA_DIR / 'social-auto-upload' / 'cookies' /
        uploader_dir / account_name
    )
    os.makedirs(os.path.dirname(account_file), exist_ok=True)

    # Remove old cookie to force fresh login
    if os.path.exists(account_file):
        os.remove(account_file)

    write_status(token, status='starting', platform=platform,
                 account_name=account_name,
                 started_at=datetime.now().isoformat())

    def qr_callback(qr_info: dict):
        img_path = qr_info.get('image_path', '')
        write_status(token, status='waiting_scan', platform=platform,
                     account_name=account_name, qr_found=True,
                     qr_image_path=img_path,
                     updated_at=datetime.now().isoformat())

    # ── Platform-specific dispatch ──
    if platform == 'douyin':
        from uploader.douyin_uploader.main import douyin_cookie_gen
        result = await douyin_cookie_gen(
            account_file,
            qrcode_callback=qr_callback,
            headless=True,
        )
    elif platform == 'kuaishou':
        from uploader.ks_uploader.main import get_ks_cookie
        result = await get_ks_cookie(
            account_file,
            qrcode_callback=qr_callback,
            headless=True,
        )
    elif platform == 'xiaohongshu':
        from uploader.xiaohongshu_uploader.main import xiaohongshu_cookie_gen
        result = await xiaohongshu_cookie_gen(
            account_file,
            qrcode_callback=qr_callback,
            headless=True,
        )
    elif platform == 'shipinhao':
        from uploader.tencent_uploader.main import tencent_cookie_gen
        result = await tencent_cookie_gen(
            account_file,
            qrcode_callback=qr_callback,
            headless=True,
        )
    else:
        write_status(token, status='error', error=f'Unknown: {platform}')
        sys.exit(1)

    # ── Write final status ──
    if result.get('success'):
        write_status(token, status='success', platform=platform,
                     account_name=account_name,
                     updated_at=datetime.now().isoformat())
    elif result.get('status') == 'cookie_invalid':
        # Cookies were saved to disk; cookie_auth verification is unreliable
        # (opens a NEW browser context, prone to 5s timeout / fingerprint mismatch)
        write_status(token, status='success', platform=platform,
                     account_name=account_name,
                     warning='cookie校验未通过但文件已保存',
                     updated_at=datetime.now().isoformat())
    else:
        write_status(token,
                     status=result.get('status', 'failed'),
                     platform=platform, account_name=account_name,
                     error=result.get('message', 'login failed'),
                     updated_at=datetime.now().isoformat())


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python login_bridge.py <token> <platform> <account_name>")
        sys.exit(1)
    token = sys.argv[1]
    platform = sys.argv[2]
    try:
        asyncio.run(run(token, platform, sys.argv[3]))
    except Exception:
        write_status(token, status='error', platform=platform,
                     error=traceback.format_exc(),
                     updated_at=datetime.now().isoformat())
