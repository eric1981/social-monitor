#!/usr/bin/env python3
"""视频号扫码登录脚本"""
import asyncio, sys
sys.path.insert(0, '/home/eric/social-monitor/social-auto-upload')

async def main():
    account_name = sys.argv[1] if len(sys.argv) > 1 else 'sph1'
    from uploader.tencent_uploader.main import tencent_setup, tencent_cookie_gen
    from pathlib import Path

    account_file = str(Path('/home/eric/social-monitor/social-auto-upload/cookies/tencent_uploader') / account_name)
    print(f"登录账号: {account_name}")
    print(f"cookie路径: {account_file}")
    print()

    result = await tencent_cookie_gen(account_file, headless=False)
    if result['success']:
        print(f"\n登录完成！cookie已保存")
    else:
        print(f"\n登录失败: {result.get('message', '未知错误')}")

asyncio.run(main())
