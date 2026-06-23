#!/usr/bin/env python3
"""
Windows 侧小红书采集脚本 — Playwright + cookie 文件
通过访问 note-manager 页面并从 DOM 提取笔记数据
"""

import json, os, sys, asyncio
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Need playwright or patchright"); sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(PROJECT_ROOT)))
COOKIES_DIR = DATA_DIR / 'social-auto-upload' / 'cookies'
TMP_DIR = PROJECT_ROOT / 'tmp'

def find_cookie(account_name):
    """在项目 cookies 目录查找 cookie 文件。"""
    candidates = [
        COOKIES_DIR / f"xiaohongshu_{account_name}.json",
        COOKIES_DIR / f"xiaohongshu_uploader" / account_name,
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

async def collect():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'xhs1'
    account_file = find_cookie(account_name)
    if not account_file:
        print(f"ERROR: Cookie not found"); sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                storage_state=account_file,
                viewport={'width': 1400, 'height': 900}
            )
            page = await context.new_page()

            # 访问笔记管理页面（不用 API）
            await page.goto(
                "https://creator.xiaohongshu.com/new/note-manager",
                wait_until="domcontentloaded"
            )
            await page.wait_for_timeout(8000)

            url = page.url
            if 'login' in url.lower():
                print(f"[{account_name}] Cookie expired", flush=True)
                sys.exit(1)

            print(f"[{account_name}] Page loaded: {url[:60]}", flush=True)

            # DOM 提取笔记列表（参考 OpenCLI adapter 的逻辑）
            notes = await page.evaluate("""
                () => {
                    const noteIdRe = /"noteId":"([0-9a-f]{24})"/;
                    const cards = document.querySelectorAll('div.note[data-impression], div.note');
                    return Array.from(cards).map((card) => {
                        const impression = card.getAttribute('data-impression') || '';
                        const id = impression.match(noteIdRe)?.[1] || '';
                        const title = (card.querySelector('.title, .raw')?.innerText || '').trim();
                        const dateText = (card.querySelector('.time_status, .time')?.innerText || '').trim();
                        const date = dateText.replace(/^发布于\s*/, '');
                        const cover = card.querySelector('img')?.getAttribute('src') || '';
                        const metrics = Array.from(card.querySelectorAll('.icon_list .icon'))
                            .map((el) => parseInt((el.innerText || '').trim(), 10))
                            .filter((value) => Number.isFinite(value));
                        return { id, title, date, cover, metrics };
                    }).filter(n => n.title || n.id);
                }
            """)

            print(f"DOM cards: {len(notes)}", flush=True)

            # 转换为标准格式
            result = []
            for n in notes:
                m = n.get('metrics', [])
                result.append({
                    'id': n.get('id', ''),
                    'title': n.get('title', ''),
                    'date': n.get('date', ''),
                    'cover_url': n.get('cover', ''),
                    'views': m[0] if len(m) > 0 else 0,
                    'comments': m[1] if len(m) > 1 else 0,
                    'likes': m[2] if len(m) > 2 else 0,
                    'collects': m[3] if len(m) > 3 else 0,
                })

            # 如果 DOM 没取到，fallback: 从 body text 解析
            if not result:
                body_text = await page.evaluate("() => document.body?.innerText || ''")
                print(f"Falling back to text parse...", flush=True)

                import re
                lines = [l.strip() for l in body_text.split('\n') if l.strip()]
                i = 0
                while i < len(lines):
                    date_match = re.match(r'^发布于 (\d{4}年\d{2}月\d{2}日 \d{2}:\d{2})$', lines[i])
                    if date_match:
                        title = lines[i-1] if i > 0 else ''
                        date = date_match.group(1)
                        metrics = []
                        j = i + 1
                        while j < len(lines) and re.match(r'^\d+$', lines[j]) and len(metrics) < 5:
                            metrics.append(int(lines[j]))
                            j += 1
                        if len(metrics) >= 4:
                            result.append({
                                'id': '',
                                'title': title,
                                'date': date,
                                'views': metrics[0],
                                'comments': metrics[1],
                                'likes': metrics[2],
                                'collects': metrics[3],
                            })
                        i = j
                    else:
                        i += 1

            # 提取昵称
            nickname = ''
            nick = await page.evaluate("""
                () => {
                    const el = document.querySelector('[class*="userName"], [class*="nickname"]');
                    return el?.textContent?.trim()?.slice(0, 30) || '';
                }
            """)
            if nick:
                nickname = nick

            out_data = {'videos': result, 'nickname': nickname}
            out_path = TMP_DIR / f'xiaohongshu_{account_name}.json'
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)

            print(f"OK: {len(result)} notes, nickname={nickname}", flush=True)
            for n in result[:3]:
                try:
                    print(f"  views={n['views']:>6} likes={n['likes']:>4} | {n['title'][:40]}", flush=True)
                except:
                    pass

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(collect())
