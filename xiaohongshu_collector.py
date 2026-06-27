#!/usr/bin/env python3
"""小红书采集 — xvfb + 真实滚动翻页"""
import json, os, sys, asyncio, subprocess
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(PROJECT_ROOT)))
COOKIES_DIR = DATA_DIR / 'social-auto-upload' / 'cookies'
TMP_DIR = PROJECT_ROOT / 'tmp'


def find_cookie(account_name):
    for p in [COOKIES_DIR / f"xiaohongshu_{account_name}.json",
              COOKIES_DIR / "xiaohongshu_uploader" / account_name]:
        if p.exists():
            return str(p)
    return None


async def collect():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'xhs1'
    account_file = find_cookie(account_name)
    if not account_file:
        print(f"ERROR: Cookie not found"); sys.exit(1)

    # Start xvfb if not already running
    if 'DISPLAY' not in os.environ or not os.environ.get('DISPLAY'):
        xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1920x1080x24', '-ac'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ['DISPLAY'] = ':99'
        await asyncio.sleep(1)
    else:
        xvfb = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            try:
                context = await browser.new_context(
                    storage_state=account_file,
                    viewport={'width': 1400, 'height': 900}
                )
                page = await context.new_page()

                all_notes = []
                seen_ids = set()

                async def capture_api(route):
                    resp = await route.fetch()
                    if 'user/posted' in route.request.url and resp.status == 200:
                        try:
                            body = await resp.json()
                            notes = (body.get('data', {}) or {}).get('notes', [])
                            for n in notes:
                                nid = n.get('id', '')
                                if nid and nid not in seen_ids:
                                    seen_ids.add(nid)
                                    imgs = n.get('images_list', [])
                                    all_notes.append({
                                        'id': nid,
                                        'title': n.get('display_title', ''),
                                        'date': n.get('time', ''),
                                        'cover_url': imgs[0].get('url', '') if imgs else '',
                                        'views': n.get('view_count', 0) or 0,
                                        'comments': n.get('comments_count', 0) or 0,
                                        'likes': n.get('likes', 0) or 0,
                                        'collects': n.get('collected_count', 0) or 0,
                                    })
                            print(f"  api: +{len(notes)} (total {len(all_notes)})", flush=True)
                        except: pass
                    await route.fulfill(response=resp)

                await page.route('**/api/galaxy/**', capture_api)

                await page.goto(
                    "https://creator.xiaohongshu.com/new/note-manager",
                    wait_until="networkidle", timeout=30000
                )
                await page.wait_for_timeout(5000)

                if 'login' in page.url.lower():
                    print(f"[{account_name}] Cookie expired", flush=True)
                    sys.exit(1)

                # Click "全部" tab
                await page.evaluate("""
                    () => { for (const t of document.querySelectorAll('.tab-item'))
                        if (t.innerText.includes('全部')) { t.click(); break; } }
                """)
                await page.wait_for_timeout(2000)

                # Scroll with real mouse wheel events to trigger virtual list
                prev_count = 0
                stale_count = 0
                for i in range(60):
                    box = await page.evaluate("""
                        () => {
                            const c = document.querySelector('.notes-container');
                            if (!c) return null;
                            const r = c.getBoundingClientRect();
                            return { x: r.x + r.width / 2, y: r.y + r.height - 50 };
                        }
                    """)
                    if box:
                        await page.mouse.move(box['x'], box['y'])
                        await page.mouse.wheel(0, 1000)

                    await page.wait_for_timeout(2000)
                    count = len(all_notes)
                    print(f"  scroll {i}: {count} notes", flush=True)
                    if count == prev_count:
                        stale_count += 1
                        if stale_count >= 5:
                            break
                    else:
                        stale_count = 0
                    prev_count = count

                # Nickname
                body_text = await page.evaluate("() => document.body?.innerText || ''")
                nickname = ''
                skip = {'全部','已发布','审核中','未通过','仅自己可见','公开',
                        '首页','笔记管理','数据看板','活动中心','笔记灵感',
                        '创作学院','创作百科','发布笔记','创作服务平台',
                        '收起侧边栏','正在加载中','遇到问题'}
                lines = [l.strip() for l in body_text.split('\n') if l.strip()]
                for i, line in enumerate(lines):
                    if line in ('发布笔记','创作服务平台') and i+1 < len(lines):
                        c = lines[i+1]
                        if len(c) < 20 and c not in skip:
                            nickname = c; break

                out_data = {'videos': all_notes, 'nickname': nickname}
                out_path = TMP_DIR / f'xiaohongshu_{account_name}.json'
                TMP_DIR.mkdir(parents=True, exist_ok=True)
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(out_data, f, ensure_ascii=False)

                print(f"FINAL: {len(all_notes)} notes, nickname={nickname}", flush=True)

            finally:
                await browser.close()
    finally:
        if xvfb:
            xvfb.terminate()
            xvfb.wait()


if __name__ == '__main__':
    asyncio.run(collect())
