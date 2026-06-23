#!/usr/bin/env python3
"""
Douyin video collector — uses social-auto-upload's stealth.js for anti-fingerprinting,
same cookie persistence pattern as douyin_cookie_gen.

Usage: python douyin_collector.py <account_name>
"""

import asyncio
import json
import os
import sys
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(PROJECT_ROOT)))
COOKIES_DIR = DATA_DIR / 'social-auto-upload' / 'cookies'
TMP_DIR = PROJECT_ROOT / 'tmp'

# social-auto-upload stealth.js path (no import needed)
_STEALTH_JS_PATH = str(PROJECT_ROOT / 'social-auto-upload' / 'utils' / 'stealth.min.js')


async def set_init_script(context):
    if os.path.exists(_STEALTH_JS_PATH):
        await context.add_init_script(path=_STEALTH_JS_PATH)
    return context


def find_cookie(account_name):
    candidates = [
        COOKIES_DIR / f'douyin_{account_name}.json',
        COOKIES_DIR / 'douyin_uploader' / account_name,
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return str(candidates[0])


async def collect():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    account_file = find_cookie(account_name)

    if not os.path.exists(account_file):
        print(f"ERROR: Cookie not found: {account_file}")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--headless=new',
                '--disable-features=HeadlessChrome',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        try:
            context = await browser.new_context(
                storage_state=account_file,
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
                viewport={'width': 1400, 'height': 900},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            )
            context = await set_init_script(context)
            page = await context.new_page()

            await page.goto(
                'https://creator.douyin.com/creator-micro/content/upload',
                wait_until='domcontentloaded'
            )
            await page.wait_for_timeout(5000)

            # Check login state
            if await page.get_by_text('扫码登录').first.count() or \
               await page.get_by_text('手机号登录').first.count():
                print("  NOT LOGGED IN: cookie invalid, please re-scan", flush=True)
                sys.exit(1)

            PAGE_SIZE = 20
            all_videos = []
            has_more = True
            max_cursor = 0
            page_num = 1

            while has_more:
                url = (f"/janus/douyin/creator/pc/work_list"
                       f"?page_size={PAGE_SIZE}&page_num={page_num}&status=0")
                if max_cursor:
                    url += f"&max_cursor={max_cursor}"

                api_json = await page.evaluate(f"""async () => {{
                    const r = await fetch('{url}', {{ credentials: "include" }});
                    return JSON.stringify(await r.json());
                }}""")
                data = json.loads(api_json)

                work_list = (data.get('data') or {}).get('work_list',
                           data.get('aweme_list', []) or data.get('items', []))

                if not work_list:
                    break

                existing_ids = {v['aweme_id'] for v in all_videos}
                new_items = [v for v in work_list if v.get('aweme_id') not in existing_ids]

                if not new_items:
                    has_more = False
                else:
                    all_videos.extend(new_items)
                    has_more = data.get('has_more', False)
                    max_cursor = data.get('max_cursor', max_cursor)
                    page_num += 1

                print(f"  Page {page_num-1}: {len(work_list)} items, {len(new_items)} new", flush=True)
                await page.wait_for_timeout(300)

            out_path = TMP_DIR / f'{account_name}.json'
            TMP_DIR.mkdir(parents=True, exist_ok=True)

            nickname = ''
            for v in all_videos:
                author = v.get('author', {})
                if isinstance(author, dict) and author.get('nickname'):
                    nickname = author['nickname']
                    break

            cleaned = []
            for v in all_videos:
                stats = v.get('statistics', {})
                create_time = v.get('create_time') or v.get('public_time', 0)
                video_info = v.get('video', {}) or {}
                cover_list = video_info.get('cover', {}).get('url_list', []) or []
                cover_url = cover_list[0] if cover_list else ''
                cleaned.append({
                    'aweme_id': v.get('aweme_id', ''),
                    'desc': v.get('desc', ''),
                    'create_time': create_time,
                    'play_count': stats.get('play_count', 0),
                    'digg_count': stats.get('digg_count', 0),
                    'comment_count': stats.get('comment_count', 0),
                    'share_count': stats.get('share_count', 0),
                    'collect_count': stats.get('collect_count', 0),
                    'duration': video_info.get('duration', 0) or 0,
                    'share_url': v.get('share_url', ''),
                    'cover_url': cover_url,
                })

            out_data = {'videos': cleaned}
            if nickname:
                out_data['nickname'] = nickname

            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)

            print(f"OK: {len(cleaned)} videos -> {out_path}", flush=True)

        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(collect())
