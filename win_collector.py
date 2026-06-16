#!/usr/bin/env python3
"""
Windows 侧抖音采集脚本
用 Playwright + cookie 直接调用创作者后台 API，支持全量翻页（游标模式）。
输出到 Windows 桌面 social-monitor/tmp/<account_name>.json

用法: python win_collector.py <account_name>
"""

import json
import os
import sys
import asyncio
from pathlib import Path

# ── 导入 playwright/patchright ──────────────────────
try:
    from patchright.async_api import async_playwright
except ImportError:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Need playwright or patchright")
        sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
COOKIES_DIR = PROJECT_ROOT / "social-auto-upload" / "cookies"
TMP_DIR = PROJECT_ROOT / "tmp"


def find_cookie(account_name):
    """在项目 cookies 目录查找 cookie 文件（跨平台）。"""
    candidates = [
        COOKIES_DIR / f"douyin_{account_name}.json",
        COOKIES_DIR / f"douyin_uploader" / account_name,
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
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=account_file)
            page = await context.new_page()

            await page.goto(
                "https://creator.douyin.com/creator-micro/content/upload",
                wait_until="domcontentloaded"
            )
            await page.wait_for_timeout(3000)

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

                api_json = await page.evaluate(f"""
                    async () => {{
                        const r = await fetch('{url}', {{ credentials: "include" }});
                        return JSON.stringify(await r.json());
                    }}
                """)
                data = json.loads(api_json)
                
                work_list = (data.get('data') or {}).get('work_list',
                           data.get('aweme_list', []) or data.get('items', []))

                if not work_list:
                    break

                # 去重检查
                existing_ids = {v['aweme_id'] for v in all_videos}
                new_items = [v for v in work_list if v.get('aweme_id') not in existing_ids]

                if not new_items:
                    # 连续两次无新数据就退出
                    if not has_more:
                        break
                    has_more = False
                else:
                    all_videos.extend(new_items)
                    has_more = data.get('has_more', False)
                    max_cursor = data.get('max_cursor', max_cursor)
                    page_num += 1

                print(f"  Page {page_num-1}: {len(work_list)} items, {len(new_items)} new, more={has_more}", flush=True)
                await page.wait_for_timeout(300)

            # 写入输出文件
            out_path = TMP_DIR / f'{account_name}.json'
            TMP_DIR.mkdir(parents=True, exist_ok=True)

            # 提取账号昵称（从第一个视频的 author 或返回数据中）
            nickname = ''
            for v in all_videos:
                author = v.get('author', {})
                if isinstance(author, dict) and author.get('nickname'):
                    nickname = author['nickname']
                    break

            # 只保留需要的字段，精简存储
            cleaned = []
            for v in all_videos:
                stats = v.get('statistics', {})
                create_time = v.get('create_time') or v.get('public_time', 0)
                # 封面图：从 video.cover.url_list 取第一张
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

            out_data = {'videos': cleaned, 'nickname': nickname}
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)

            print(f"OK: {len(cleaned)} videos -> {out_path}", flush=True)

        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(collect())
