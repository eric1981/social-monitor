#!/usr/bin/env python3
"""
Windows 侧视频号采集脚本 — API 直调
"""
import json, os, sys, asyncio

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright

USERPROFILE = os.environ['USERPROFILE']

async def collect():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'sph1'
    cookie_file = os.path.join(USERPROFILE, 'Desktop', 'social-monitor',
        'social-auto-upload', 'cookies', 'tencent_uploader', account_name)

    if not os.path.exists(cookie_file):
        print(f"ERROR: Cookie not found"); sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=cookie_file,
                viewport={'width': 1400, 'height': 900})
            page = await context.new_page()

            # 先访问主页建立 session
            await page.goto("https://channels.weixin.qq.com/platform",
                wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # 获取昵称
            nickname = await page.evaluate("""() => {
                // 先尝试昵称元素，再 fallback 到品牌名
                const nick = document.querySelector('[class*="nick"]');
                if (nick) return nick.textContent?.trim()?.slice(0, 30) || '';
                const acct = document.querySelector('[class*="account"]');
                if (acct) {
                    const text = acct.textContent?.trim() || '';
                    // "[class*=\"account\"]" 里可能包含 "切换视频号" 等文本，取第一段
                    const parts = text.split(/\\s+/);
                    return parts[0]?.slice(0, 30) || '';
                }
                const brand = document.querySelector('.brand-name, [class*="brand"], [class*="user"]');
                return brand?.textContent?.trim()?.slice(0, 30) || '';
            }""")
            nickname = nickname.replace('\n', '').strip()

            # 调 post_list API（翻页）
            all_posts = []
            page_num = 1
            has_more = True

            while has_more:
                result = await page.evaluate(f"""
                    async () => {{
                        const r = await fetch(
                            '/micro/content/cgi-bin/mmfinderassistant-bin/post/post_list',
                            {{
                                method: 'POST',
                                credentials: 'include',
                                headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify({{
                                    page: {page_num},
                                    pageSize: 20,
                                    postType: 0
                                }})
                            }}
                        );
                        const j = await r.json();
                        return JSON.stringify(j);
                    }}
                """)
                data = json.loads(result)
                post_list = (data.get('data') or {}).get('list', [])
                if not post_list:
                    break

                # 去重
                existing_ids = {p.get('objectId', '') for p in all_posts}
                new_posts = [p for p in post_list if p.get('objectId', '') not in existing_ids]
                if not new_posts:
                    break

                all_posts.extend(new_posts)
                has_more = len(post_list) >= 20
                page_num += 1
                await page.wait_for_timeout(300)

            # 格式化
            import datetime
            now_ts = int(datetime.datetime.now().timestamp())

            cleaned = []
            for p in all_posts:
                desc = p.get('desc', {}) or {}
                media = (desc.get('media') or [{}])[0]
                create_time = p.get('createTime', 0)

                # 跳过定时发布的视频：createTime 是实际发布时间，
                # 如果当前时间早于 createTime，说明还没到发布时间（定时发布状态）
                if create_time and create_time > now_ts:
                    print(f"  ⏭ 跳过定时发布: objectId={str(p.get('objectId',''))[:30]}... "
                          f"scheduled_at={datetime.datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M')}",
                          flush=True)
                    continue

                time_str = datetime.datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M:%S') if create_time else ''

                # 标题优先取 description（用户在发布页面填的"描述"栏），
                # 没有则取 shortTitle，都没有留空
                title = desc.get('description', '') or desc.get('shortTitle', '') or ''

                cleaned.append({
                    'object_id': p.get('objectId', ''),
                    'title': title,
                    'create_time': time_str,
                    'read_count': p.get('readCount', 0),
                    'like_count': p.get('likeCount', 0),
                    'comment_count': p.get('commentCount', 0),
                    'forward_count': p.get('forwardCount', 0),
                    'fav_count': p.get('favCount', 0),
                    'cover_url': media.get('coverUrl', media.get('thumbUrl', '')),
                    'duration': media.get('videoPlayLen', 0),
                })

            out_data = {'videos': cleaned, 'nickname': nickname}
            out_path = os.path.join(USERPROFILE, 'Desktop', 'social-monitor', 'tmp', f'shipinhao_{account_name}.json')
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False)

            print(f"OK: {len(cleaned)} posts, nickname={nickname}", flush=True)
            for v in cleaned[:3]:
                print(f"  reads={v['read_count']:>6} likes={v['like_count']:>4} | {v['title'][:40]}", flush=True)

        finally:
            await browser.close()

asyncio.run(collect())
