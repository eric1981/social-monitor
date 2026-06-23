#!/usr/bin/env python3
"""
Bridge script: uses social-auto-upload's douyin_cookie_gen for QR login.
Writes status to tmp/qr_{token}.json for web frontend polling.

Usage: python login_bridge.py <token> <platform> <account_name>
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(PROJECT_ROOT)))
TMP_DIR = PROJECT_ROOT / 'tmp'

sys.path.insert(0, str(PROJECT_ROOT / 'social-auto-upload'))
from uploader.douyin_uploader.main import douyin_cookie_gen


def write_status(token, **kwargs):
    TMP_DIR.mkdir(exist_ok=True)
    with open(TMP_DIR / f'qr_{token}.json', 'w') as f:
        json.dump(kwargs, f, ensure_ascii=False)


async def run(token, platform, account_name):
    if platform != 'douyin':
        write_status(token, status='error', error=f'Unsupported: {platform}')
        sys.exit(1)

    account_file = str(
        DATA_DIR / 'social-auto-upload' / 'cookies' /
        f'{platform}_uploader' / account_name
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

    result = await douyin_cookie_gen(
        account_file,
        qrcode_callback=qr_callback,
        headless=True,
    )

    if result.get('success'):
        write_status(token, status='success', platform=platform,
                     account_name=account_name,
                     updated_at=datetime.now().isoformat())
    else:
        write_status(token, status=result.get('status', 'failed'),
                     platform=platform, account_name=account_name,
                     error=result.get('message', 'login failed'),
                     updated_at=datetime.now().isoformat())


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python login_bridge.py <token> <platform> <account_name>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
