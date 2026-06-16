#!/usr/bin/env python3
"""
Windows 侧快手采集脚本 — 精确 DOM 提取版
"""
import json, os, sys, asyncio, re

try:
    from patchright.async_api import async_playwright
except ImportError:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Need playwright or patchright"); sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
COOKIES_DIR = PROJECT_ROOT / 'social-auto-upload' / 'cookies'
TMP_DIR = PROJECT_ROOT / 'tmp'

def find_cookie(account_name):
    """在项目 cookies 目录查找 cookie 文件。"""
    candidates = [
        COOKIES_DIR / f"kuaishou_{account_name}.json",
        COOKIES_DIR / f"kuaishou_uploader" / account_name,
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

async def collect():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'ks1'
    account_file = find_cookie(account_name)
    if not account_file:
        print(f"ERROR: Cookie not found"); sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=account_file,
                viewport={'width': 1400, 'height': 900})
            page = await context.new_page()

            await page.goto(
                "https://cp.kuaishou.com/article/manage/video?status=2",
                wait_until="domcontentloaded"
            )
            await page.wait_for_timeout(5000)

            # 点"已发布" tab
            await page.evaluate("""
                () => {
                    const tabs = document.querySelectorAll('.el-tabs__item');
                    for (const tab of tabs) {
                        if (tab.textContent?.includes('已发布')) { tab.click(); break; }
                    }
                }
            """)
            await page.wait_for_timeout(3000)

            # 精确提取每个 video-item 的数据
            videos = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.video-item');
                    return Array.from(items).map(item => {
                        // 时长
                        const duration = item.querySelector('.video-item__cover__duration')?.textContent?.trim() || '';
                        
                        // detail 区域
                        const detail = item.querySelector('.video-item__detail');
                        const rows = detail?.querySelectorAll('.video-item__detail__row') || [];
                        
                        // 标题（第一个 row）
                        const title = rows[0]?.textContent?.trim() || '';
                        
                        // 状态 + 日期（第二个 row）
                        const statusRow = rows[1]?.textContent?.trim() || '';
                        const dateMatch = statusRow.match(/(\\d{4}-\\d{1,2}-\\d{1,2})\\s+(\\d{1,2}:\\d{2})/);
                        const publishTime = dateMatch ? `${dateMatch[1]} ${dateMatch[2]}` : statusRow;
                        
                    // 封面图片 — 从 URL 提取 photoId 和完整封面URL
                    const coverImg = item.querySelector('.video-item__cover__img');
                    const coverSrc = coverImg?.getAttribute('src') || '';
                    const coverRealSrc = coverImg?.getAttribute('data-src') || coverSrc;
                    const cacheMatch = coverSrc.match(/clientCacheKey=([^&.]+)/);
                    const photoId = cacheMatch ? cacheMatch[1] : '';

                    // 统计数据 — 找最后一个包含 label 的 row（跳过流量助推等额外行）
                    let statsRow = null;
                    for (let i = rows.length - 1; i >= 0; i--) {
                        if (rows[i].querySelector('.video-item__detail__row__label')) {
                            statsRow = rows[i];
                            break;
                        }
                    }
                    const labels = statsRow?.querySelectorAll('.video-item__detail__row__label') || [];
                    const views = labels[0]?.textContent?.trim() || '0';
                    const likes = labels[1]?.textContent?.trim() || '0';
                    const comments = labels[2]?.textContent?.trim() || '0';

                    return {
                        title: title.slice(0, 200),
                        duration: duration,
                        publish_time: publishTime,
                        photo_id: photoId,
                        cover_url: coverRealSrc,
                        view_count: views,
                        like_count: likes,
                        comment_count: comments,
                    };
                    });
                }
            """)

            # 提取昵称
            nickname = ''
            header = await page.evaluate("() => document.querySelector('.header-info-card')?.textContent || ''")
            m = re.search(r'(\S+)', header)
            if m: nickname = m.group(1)

            out_data = {'videos': videos, 'nickname': nickname}
            out_path = TMP_DIR / f'kuaishou_{account_name}.json'
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)
            print(f"OK: {len(videos)} videos", flush=True)

            # 调试输出（可能因 GBK 编码崩溃，不影响数据写入）
            print(f"Total: {len(videos)} videos, nickname={nickname}", flush=True)
            for v in videos[:5]:
                try:
                    print(f"  {v['publish_time']} 播放={v['view_count']:>6} 赞={v['like_count']:>4} 评={v['comment_count']:>4} | {v['title'][:40]}", flush=True)
                except:
                    pass

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(collect())
