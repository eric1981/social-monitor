#!/usr/bin/env python3
"""
Windows 侧通用扫码登录脚本 — 支持反检测
接收平台和账号名参数，弹出浏览器窗口扫码登录。
用法: python win_login.py <platform> <account_name>

反检测措施:
- 使用系统 Chrome (channel: chrome) 而非内置 Chromium
- 覆盖 navigator.webdriver / chrome / plugins / languages
- 添加自动化检测绕过参数
"""

import json, os, sys, asyncio

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright

USERPROFILE = os.environ['USERPROFILE']

PLATFORM_CONFIG = {
    'douyin': {
        'cookie_dir': 'douyin_uploader',
        'login_url': 'https://creator.douyin.com/creator-micro/content/upload',
        'cookie_suffix': '',
    },
    'kuaishou': {
        'cookie_dir': 'kuaishou_uploader',
        'login_url': 'https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api',
        'cookie_suffix': '',
    },
    'xiaohongshu': {
        'cookie_dir': 'xiaohongshu_uploader',
        'login_url': 'https://creator.xiaohongshu.com/login',
        'cookie_suffix': '',
    },
    'shipinhao': {
        'cookie_dir': 'tencent_uploader',
        'login_url': 'https://channels.weixin.qq.com/platform/post/create',
        'cookie_suffix': '',
    },
}

# 反检测 — 使用 puppeteer-extra 完整 stealth 脚本（180KB，覆盖所有检测向量）
STEALTH_JS_PATH = os.path.join(USERPROFILE, 'Desktop', 'social-monitor',
    'social-auto-upload', 'utils', 'stealth.min.js')


async def login(platform, account_name):
    config = PLATFORM_CONFIG.get(platform)
    if not config:
        print(f"ERROR: Unknown platform: {platform}")
        sys.exit(1)

    # cookie 路径 — 保存到 cookies/{platform}_uploader/ 下
    cookie_base = os.path.join(USERPROFILE, 'Desktop', 'social-monitor',
        'social-auto-upload', 'cookies')
    if platform == 'shipinhao':
        cookie_dir = os.path.join(cookie_base, 'tencent_uploader')
    else:
        cookie_dir = os.path.join(cookie_base, f'{platform}_uploader')
    os.makedirs(cookie_dir, exist_ok=True)
    cookie_file = os.path.join(cookie_dir, account_name)

    async with async_playwright() as p:
        # 优先使用系统 Chrome（真实浏览器，不被检测）
        # 如果没装 Chrome，回退到 Chromium + 反检测
        use_chrome = False
        try:
            # 检查系统是否有 Chrome
            import shutil
            chrome_path = shutil.which('chrome') or shutil.which('google-chrome')
            if not chrome_path:
                chrome_path = os.path.expandvars(r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe')
                if os.path.exists(chrome_path):
                    use_chrome = True
                chrome_path = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe')
                if os.path.exists(chrome_path):
                    use_chrome = True
        except:
            pass

        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-infobars',
            '--start-maximized',
        ]

        if use_chrome:
            print("检测到系统 Chrome，使用系统浏览器...", flush=True)
            browser = await p.chromium.launch(
                headless=False,
                channel='chrome',
                args=launch_args,
            )
        else:
            print("未检测到系统 Chrome，使用内置 Chromium + 反检测...", flush=True)
            browser = await p.chromium.launch(
                headless=False,
                args=launch_args,
            )

        # 创建上下文并注入反检测脚本
        # 注意：不覆盖 user_agent，让 Chrome 用真实的（避免版本不匹配被检测）
        context = await browser.new_context(
            viewport={'width': 1400, 'height': 900},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )

        # 注入 stealth 反检测（所有浏览器都需要，Playwright CDP 连接会留痕）
        await context.add_init_script(path=STEALTH_JS_PATH)

        page = await context.new_page()

        # ── 快手: 用 page.on('response') 监听 qr/callback ──
        # 诊断发现: 服务端全部返回成功，但页面 JS 不跳转（stsUrl/followUrl 为空）
        # 所以我们在 Playwright 层拦截 callback 响应，手动导航到 cp 后台
        ks_login_done = False

        if platform == 'kuaishou':
            async def on_response(resp):
                nonlocal ks_login_done
                if 'qr/callback' in resp.url and not ks_login_done:
                    try:
                        body = await resp.text()
                        data = json.loads(body)
                        if data.get('result') == 1:
                            print(f"  [KS] qr/callback result=1, 手动跳转到 cp.kuaishou.com", flush=True)
                            ks_login_done = True
                    except:
                        pass

            page.on('response', on_response)

        print(f"正在打开 {platform} 登录页面，请扫码...", flush=True)
        print(f"如果页面没有自动弹出二维码，请刷新页面", flush=True)

        await page.goto(config['login_url'], wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        # 等待扫码完成
        success = False
        for i in range(180):  # 最多等 3 分钟
            await page.wait_for_timeout(1000)
            current_url = page.url

            # 视频号特殊处理
            if platform == 'shipinhao':
                if 'login' not in current_url.lower() and ('post' in current_url.lower() or 'platform' in current_url.lower()):
                    print(f"登录成功！", flush=True)
                    success = True
                    break
            else:
                if 'login' not in current_url.lower():
                    print(f"登录成功！跳转到: {current_url[:60]}", flush=True)
                    success = True
                    break

            # 快手: 检测到 qr/callback 成功 → 手动跳转到创作者后台
            if platform == 'kuaishou' and ks_login_done:
                print(f"callback 已确认，手动跳转到快手创作者后台...", flush=True)
                await page.goto(
                    "https://cp.kuaishou.com/article/manage/video?status=2",
                    wait_until="domcontentloaded"
                )
                await page.wait_for_timeout(5000)
                success = True
                break

            if i % 10 == 0 and i > 0:
                print(f"等待扫码中... ({i}s)", flush=True)
            if i == 30:
                print(f"提示：请在手机 App 中确认登录，页面会自动跳转", flush=True)
            if i == 60:
                print(f"如果长时间无反应，尝试：1) 刷新二维码 2) 检查手机网络 3) 重试登录", flush=True)

        if not success:
            print("登录超时或失败，请重试", flush=True)
            await browser.close()
            sys.exit(1)

        # 等待页面稳定，再保存 cookie
        await page.wait_for_timeout(3000)

        # 保存 cookie
        await context.storage_state(path=cookie_file)
        print(f"cookie 已保存: {cookie_file}", flush=True)

        await page.wait_for_timeout(1000)
        await browser.close()

    # 同步到 WSL 侧的对应目录
    if platform == 'shipinhao':
        wsl_dest = f"/home/eric/social-monitor/social-auto-upload/cookies/tencent_uploader/{account_name}"
    else:
        wsl_dest = f"/home/eric/social-monitor/social-auto-upload/cookies/{platform}_uploader/{account_name}"

    # 同时也同步一份到 cookies/ 根目录（方便 win_collect_stats.py 查找）
    if platform != 'shipinhao':
        wsl_root = f"/home/eric/social-monitor/social-auto-upload/cookies/{platform}_{account_name}.json"
        os.system(f'wsl cp "{cookie_file}" {wsl_root} 2>/dev/null || true')

    os.system(f'wsl cp "{cookie_file}" {wsl_dest} 2>/dev/null || true')
    print(f"已同步到 WSL", flush=True)

    # 更新数据库 cookie_status（登录成功 → ok）
    status_script = '/mnt/c/Users/NINGMEI/Desktop/social-monitor/update_cookie_status.py'
    os.system(f'wsl python3 {status_script} {platform} {account_name} 2>/dev/null || true')
    print(f"OK", flush=True)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python win_login.py <platform> <account_name>")
        print("platform: douyin, kuaishou, xiaohongshu, shipinhao")
        sys.exit(1)
    asyncio.run(login(sys.argv[1], sys.argv[2]))
