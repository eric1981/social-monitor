#!/usr/bin/env python3
"""
Windows 侧采集账号统计数据（粉丝数、总获赞数等）
各平台从创作者后台获取账号级数据。

用法: python win_collect_stats.py <platform> <account_name>

输出到桌面 social-monitor/tmp/stats_<platform>_<account_name>.json
格式: {"follower_count": N, "total_digg_count": N, "total_play_count": N, ...}
"""

import json, os, sys, asyncio

try:
    from patchright.async_api import async_playwright
except ImportError:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Need playwright or patchright"); sys.exit(1)

USERPROFILE = os.environ['USERPROFILE']


def find_cookie(platform, account_name):
    cookie_map = {
        'douyin': f'douyin_{account_name}.json',
        'kuaishou': f'kuaishou_{account_name}.json',
        'xiaohongshu': f'xiaohongshu_{account_name}.json',
        'shipinhao': None,
    }
    filename = cookie_map.get(platform)
    if filename:
        candidates = [
            os.path.join(USERPROFILE, 'Desktop', 'social-monitor', 'social-auto-upload', 'cookies', filename),
            os.path.join(USERPROFILE, 'Desktop', 'social-auto-upload', 'cookies', filename),
            os.path.join(USERPROFILE, 'social-auto-upload', 'cookies', filename),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
    elif platform == 'shipinhao':
        p = os.path.join(USERPROFILE, 'Desktop', 'social-monitor',
            'social-auto-upload', 'cookies', 'tencent_uploader', account_name)
        if os.path.exists(p):
            return p
    return None


async def collect_douyin(page):
    """
    从抖音创作者后台提取账号统计
    策略：拦截创作者后台 API 响应，从结构化数据提取
    """
    result = {
        'follower_count': 0, 'total_digg_count': 0, 'total_play_count': 0,
        'total_following_count': 0, 'profile_bio': '', 'profile_douyin_id': '',
        'profile_avatar_url': '', 'profile_like_count': 0, 'nickname': '',
    }

    api_data = {}

    async def handle_response(response):
        url = response.url
        # 抖音创作者后台统计数据 API
        if '/aweme/v1/creator/user/info' in url or '/creator-micro/setting' in url:
            try:
                body = await response.json()
                api_data[url] = body
                d = json.dumps(body, ensure_ascii=False)
                print(f"  [API] {url.split('?')[0][:80]} -> {d[:300]}", flush=True)
            except:
                pass

    page.on('response', handle_response)

    # 访问首页触发 user/info API
    await page.goto("https://creator.douyin.com/creator-micro/home",
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    # 从拦截的 API 数据提取
    for url, data in api_data.items():
        if '/aweme/v1/creator/user/info' in url:
            info = data.get('douyin_user_verify_info', {})
            if info:
                result['follower_count'] = int(info.get('follower_count', 0) or 0)
                result['total_digg_count'] = int(info.get('total_favorited', 0) or 0)
                result['total_following_count'] = int(info.get('following_count', 0) or 0)
                result['nickname'] = info.get('nick_name', '')
                result['profile_avatar_url'] = info.get('avatar_url', '')
                result['profile_douyin_id'] = info.get('douyin_unique_id', '')
                print(f"  [user/info] 粉丝={result['follower_count']}, 获赞={result['total_digg_count']}, 昵称={result['nickname']}", flush=True)

    # 再访问设置页面获取个人简介和头像
    # 注意清空 api_data 避免旧响应干扰
    api_data.clear()
    try:
        await page.goto("https://creator.douyin.com/creator-micro/setting",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        for url, data in api_data.items():
            if '/creator-micro/setting' in url:
                print(f"  [setting API] {json.dumps(data, ensure_ascii=False)[:300]}", flush=True)

        # 从页面 DOM 提取简介（API 没有返回设置页内容）
        profile = await page.evaluate("""() => {
            const body = document.body?.innerText || '';
            const lines = body.split('\\n').map(l => l.trim()).filter(l => l);

            let bio = '', douyinId = '', avatarUrl = '';

            // 找个人简介
            for (let i = 0; i < lines.length; i++) {
                if (lines[i].includes('个人简介')) {
                    if (i + 1 < lines.length) {
                        bio = lines[i+1].trim();
                        if (bio.includes('个人简介') || bio.length > 200) bio = '';
                    }
                    break;
                }
            }

            // 找头像 — 找设置页的头像 img
            const avatars = document.querySelectorAll('img[class*=\"avatar\"], img[class*=\"Avatar\"]');
            for (const img of avatars) {
                const src = img.getAttribute('src') || '';
                if (src.startsWith('http')) { avatarUrl = src; break; }
            }

            return JSON.stringify({bio, douyinId, avatarUrl});
        }""")
        p = json.loads(profile)
        if p.get('bio'):
            result['profile_bio'] = p['bio']
        if p.get('avatarUrl'):
            result['profile_avatar_url'] = p['avatarUrl']
    except Exception as e:
        print(f"  [抖音 profile] 获取个人信息失败: {e}", flush=True)

    return result


async def collect_kuaishou(page):
    """从快手创作者后台提取账号统计"""
    api_data = {}

    async def handle_response(response):
        url = response.url
        if '/rest/wd/visitor/home' in url or '/rest/wd/status/card' in url:
            try:
                body = await response.json()
                api_data[url] = body
                d = json.dumps(body, ensure_ascii=False)
                print(f"  [API] {url.split('?')[0][:80]} -> {d[:300]}", flush=True)
            except:
                pass

    page.on('response', handle_response)

    await page.goto("https://cp.kuaishou.com/", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    follower = 0
    totalDigg = 0

    for url, data in api_data.items():
        print(f"  [快手 API 分析] {url}: {json.dumps(data, ensure_ascii=False)[:400]}", flush=True)

    # 降级：从页面文本提取
    stats = await page.evaluate("""() => {
        const body = document.body?.innerText || '';
        const lines = body.split('\\n').map(l => l.trim()).filter(l => l);
        // dump 前 60 行
        const dump = lines.slice(0, 60);
        dump.forEach((l, i) => console.log(i + ': ' + l));

        let follower = 0, totalDigg = 0;

        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('粉丝')) {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        follower = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
            if (lines[i].includes('获赞')) {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        totalDigg = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
        }
        return JSON.stringify({follower_count: follower, total_digg_count: totalDigg,
                               total_play_count: 0, total_following_count: 0});
    }""")
    return json.loads(stats)


async def collect_xiaohongshu(page):
    """从小红书创作者后台提取账号统计"""
    api_data = {}

    async def handle_response(response):
        url = response.url
        if '/api/sns/web/v1/user/me' in url or '/api/sns/web/v1/user/other' in url:
            try:
                body = await response.json()
                api_data[url] = body
                d = json.dumps(body, ensure_ascii=False)
                print(f"  [API] {url.split('?')[0][:80]} -> {d[:300]}", flush=True)
            except:
                pass

    page.on('response', handle_response)

    await page.goto("https://creator.xiaohongshu.com/", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    for url, data in api_data.items():
        print(f"  [小红书 API] {url}: {json.dumps(data, ensure_ascii=False)[:400]}", flush=True)

    stats = await page.evaluate("""() => {
        const body = document.body?.innerText || '';
        const lines = body.split('\\n').map(l => l.trim()).filter(l => l);
        const dump = lines.slice(0, 60);
        dump.forEach((l, i) => console.log(i + ': ' + l));

        let follower = 0, totalDigg = 0;

        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('粉丝') || lines[i] === '粉') {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        follower = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
            if (lines[i].includes('获赞') || lines[i] === '赞' && !lines[i].includes('点')) {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        totalDigg = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
        }
        return JSON.stringify({follower_count: follower, total_digg_count: totalDigg,
                               total_play_count: 0, total_following_count: 0});
    }""")
    return json.loads(stats)


async def collect_shipinhao(page):
    """从视频号平台提取账号统计"""
    await page.goto("https://channels.weixin.qq.com/platform",
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)

    stats = await page.evaluate("""() => {
        const body = document.body?.innerText || '';
        const lines = body.split('\\n').map(l => l.trim()).filter(l => l);
        const dump = lines.slice(0, 60);
        dump.forEach((l, i) => console.log(i + ': ' + l));

        let follower = 0, totalPlay = 0;

        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('关注') || lines[i].includes('粉丝')) {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        follower = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
            if (lines[i].includes('播放') || lines[i].includes('阅读')) {
                for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
                    const n = parseFloat(lines[j].replace(/,/g, '').replace(/\\s/g, ''));
                    if (!isNaN(n) && n > 0) {
                        totalPlay = lines[j].includes('万') ? Math.round(n * 10000) : Math.round(n);
                        break;
                    }
                }
            }
        }
        return JSON.stringify({follower_count: follower, total_digg_count: 0,
                               total_play_count: totalPlay, total_following_count: 0});
    }""")
    return json.loads(stats)


async def main():
    platform = sys.argv[1] if len(sys.argv) > 1 else 'douyin'
    account_name = sys.argv[2] if len(sys.argv) > 2 else 'benxian1'

    cookie_file = find_cookie(platform, account_name)
    if not cookie_file:
        print(f"ERROR: Cookie not found for {platform}/{account_name}", flush=True)
        print(f"Searched in: {USERPROFILE}\\Desktop\\social-monitor\\social-auto-upload\\cookies\\", flush=True)
        sys.exit(1)

    print(f"Cookie: {cookie_file}", flush=True)

    collectors = {
        'douyin': collect_douyin,
        'kuaishou': collect_kuaishou,
        'xiaohongshu': collect_xiaohongshu,
        'shipinhao': collect_shipinhao,
    }

    collector = collectors.get(platform)
    if not collector:
        print(f"ERROR: Unknown platform: {platform}", flush=True)
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                storage_state=cookie_file,
                viewport={'width': 1400, 'height': 900}
            )
            page = await context.new_page()

            result = await collector(page)
            print(f"\n  [结果] {platform}/{account_name}: {json.dumps(result, ensure_ascii=False)}", flush=True)

            # 写入输出文件
            out_file = f"stats_{platform}_{account_name}.json"
            out_path = os.path.join(USERPROFILE, 'Desktop', 'social-monitor', 'tmp', out_file)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False)

            print(f"\nOK: {out_path}", flush=True)

        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
