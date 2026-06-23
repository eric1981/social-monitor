#!/usr/bin/env python3
"""
Headless QR code login script — embedded flow (no popup Chrome window).
Captures the QR code from the platform's login page, saves it as an image,
then polls until the user scans and completes login via phone.

Usage: python qr_login.py <token> <platform> <account_name>
Status: written to tmp/qr_<token>.json
QR image: written to tmp/qr_<token>.png
"""

import json, os, sys, asyncio, uuid
from pathlib import Path
from datetime import datetime

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent
COOKIES_DIR = PROJECT_ROOT / 'social-auto-upload' / 'cookies'
TMP_DIR = PROJECT_ROOT / 'tmp'
STEALTH_JS_PATH = str(PROJECT_ROOT / 'social-auto-upload' / 'utils' / 'stealth.min.js')

PLATFORM_CONFIG = {
    'douyin': {
        'cookie_dir': 'douyin_uploader',
        'login_url': 'https://creator.douyin.com/creator-micro/content/upload',
        'qr_selector': 'img[src*="qrcode"], .qrcode-img, .login-qrcode img, canvas[class*="qr"]',
    },
    'kuaishou': {
        'cookie_dir': 'kuaishou_uploader',
        'login_url': 'https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api',
        'qr_selector': 'img[src*="qr"], .qrcode img, .login-qr img, canvas[class*="qr"], #qr-image',
    },
    'xiaohongshu': {
        'cookie_dir': 'xiaohongshu_uploader',
        'login_url': 'https://creator.xiaohongshu.com/login',
        'qr_selector': 'img[src*="qr"], .qrcode-img, .login-qrcode img, canvas[class*="qr"]',
    },
    'shipinhao': {
        'cookie_dir': 'tencent_uploader',
        'login_url': 'https://channels.weixin.qq.com/platform/post/create',
        'qr_selector': 'img[src*="qr"], .qrcode-img, .login-qrcode img, .qr-code img',
    },
}


def write_status(token, **kwargs):
    """Write status to tmp/qr_{token}.json"""
    TMP_DIR.mkdir(exist_ok=True)
    path = TMP_DIR / f'qr_{token}.json'
    with open(path, 'w') as f:
        json.dump(kwargs, f)


async def run(token, platform, account_name):
    config = PLATFORM_CONFIG.get(platform)
    if not config:
        write_status(token, status='error', error=f'Unknown platform: {platform}')
        sys.exit(1)

    cookie_base = str(COOKIES_DIR)
    os.makedirs(cookie_base, exist_ok=True)

    # Cookie file path
    if platform == 'shipinhao':
        cookie_dir = os.path.join(cookie_base, 'tencent_uploader')
    else:
        cookie_dir = os.path.join(cookie_base, f'{platform}_uploader')
    os.makedirs(cookie_dir, exist_ok=True)
    cookie_file = os.path.join(cookie_dir, account_name)

    write_status(token, status='starting', platform=platform, account_name=account_name,
                 started_at=datetime.now().isoformat())

    async with async_playwright() as p:
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-infobars',
        ]

        # Try system Chrome first (headless), fall back to Chromium
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=True,
                channel='chrome',
                args=launch_args,
            )
        except Exception:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=launch_args,
                )
            except Exception as e:
                write_status(token, status='error', error=f'Browser launch failed: {e}')
                sys.exit(1)

        try:
            context = await browser.new_context(
                viewport={'width': 1400, 'height': 900},
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )

            # Inject stealth
            if os.path.exists(STEALTH_JS_PATH):
                await context.add_init_script(path=STEALTH_JS_PATH)

            page = await context.new_page()

            # ── Kuaishou callback listener ──
            ks_login_done = False

            if platform == 'kuaishou':
                async def on_response(resp):
                    nonlocal ks_login_done
                    if 'qr/callback' in resp.url and not ks_login_done:
                        try:
                            body = await resp.text()
                            data = json.loads(body)
                            if data.get('result') == 1:
                                ks_login_done = True
                        except:
                            pass
                page.on('response', on_response)

            # Navigate to login page
            await page.goto(config['login_url'], wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Try to find and screenshot QR code element
            qr_image_path = TMP_DIR / f'qr_{token}.png'
            qr_found = False

            for selector in config['qr_selector'].split(','):
                selector = selector.strip()
                try:
                    qr_el = await page.wait_for_selector(selector, timeout=5000)
                    if qr_el:
                        await qr_el.screenshot(path=str(qr_image_path))
                        qr_found = True
                        break
                except Exception:
                    continue

            if not qr_found:
                # Fallback: take full page screenshot
                await page.screenshot(path=str(qr_image_path))

            write_status(token, status='waiting_scan', platform=platform,
                         account_name=account_name, qr_found=qr_found,
                         updated_at=datetime.now().isoformat())

            # Poll for login completion — max 2 minutes
            success = False
            for i in range(120):
                await page.wait_for_timeout(1000)
                current_url = page.url

                # Shipinhao special check
                if platform == 'shipinhao':
                    if 'login' not in current_url.lower() and ('post' in current_url.lower() or 'platform' in current_url.lower()):
                        success = True
                        break
                else:
                    if 'login' not in current_url.lower():
                        success = True
                        break

                # Kuaishou callback detected
                if platform == 'kuaishou' and ks_login_done:
                    await page.goto(
                        "https://cp.kuaishou.com/article/manage/video?status=2",
                        wait_until="domcontentloaded"
                    )
                    await page.wait_for_timeout(5000)
                    success = True
                    break

                if i == 118:  # About to timeout
                    write_status(token, status='expired', platform=platform,
                                 error='QR code expired — 2 minute timeout',
                                 updated_at=datetime.now().isoformat())
                    await browser.close()
                    sys.exit(0)

            if not success:
                write_status(token, status='expired', platform=platform,
                             error='QR code expired or login failed',
                             updated_at=datetime.now().isoformat())
                await browser.close()
                sys.exit(0)

            # Login succeeded — wait for page to stabilize
            await page.wait_for_timeout(3000)

            # Save cookies
            await context.storage_state(path=cookie_file)

            # Also save flat copy (for win_collect_stats.py compatibility)
            if platform != 'shipinhao':
                flat_path = os.path.join(cookie_base, f'{platform}_{account_name}.json')
                os.system(f'cp "{cookie_file}" "{flat_path}" 2>/dev/null || true')

            write_status(token, status='success', platform=platform,
                         account_name=account_name,
                         updated_at=datetime.now().isoformat())

        except Exception as e:
            write_status(token, status='error', error=str(e),
                         updated_at=datetime.now().isoformat())
        finally:
            await browser.close()


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python qr_login.py <token> <platform> <account_name>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
