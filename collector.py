#!/usr/bin/env python3
"""
Social Monitor — 跨平台采集器
直接调用 Playwright 脚本采集创作者后台数据（Windows / macOS / Linux 通用）。

用法：
  python3 collector.py                              # 采集所有活跃账号
  python3 collector.py --platform douyin             # 只采抖音
  python3 collector.py --account benxian1            # 只采某个账号
  python3 collector.py --dry-run                     # 预览不写入
  python3 collector.py --stats-only                  # 仅采集账号统计
"""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config

MONITOR_DIR = Path(__file__).parent
DB_PATH = MONITOR_DIR / "monitor.db"
COOKIES_DIR = MONITOR_DIR / "social-auto-upload" / "cookies"
SOCIAL_AUTO_UPLOAD_DIR = MONITOR_DIR / "social-auto-upload"
TMP_DIR = MONITOR_DIR / "tmp"

# 脚本名称映射（项目根目录下的脚本）
COLLECTOR_SCRIPTS = {
    "douyin": "win_collector.py",
    "kuaishou": "win_kuaishou.py",
    "xiaohongshu": "win_xiaohongshu.py",
    "shipinhao": "win_shipinhao.py",
    "stats": "win_collect_stats.py",
}


def run_script(platform_key: str, *args) -> subprocess.CompletedProcess:
    """调用项目根目录下的采集脚本（跨平台）。"""
    script = COLLECTOR_SCRIPTS.get(platform_key)
    if not script:
        raise ValueError(f"未知平台: {platform_key}")
    script_path = MONITOR_DIR / script
    cmd = [sys.executable, str(script_path)] + list(args)
    return subprocess.run(cmd, capture_output=True, timeout=config.collect_timeout())


# ── 数据库 ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_active_accounts(conn, platform=None, account_name=None):
    parts = ["SELECT * FROM accounts WHERE is_active=1"]
    params = []
    if platform:
        parts.append("AND platform=?")
        params.append(platform)
    if account_name:
        parts.append("AND account_name=?")
        params.append(account_name)
    return conn.execute(" ".join(parts), params).fetchall()


def ensure_video(conn, account_id, platform, account_name, aweme_id, title,
                 duration=0, url="", create_time=None, cover_url=""):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur = conn.execute(
        'SELECT id, title, cover_url FROM videos WHERE platform=? AND aweme_id=?',
        (platform, aweme_id)
    )
    row = cur.fetchone()
    if row:
        if title and title != row['title']:
            conn.execute('UPDATE videos SET title=? WHERE id=?', (title, row['id']))
        if url:
            conn.execute('UPDATE videos SET url=? WHERE id=? AND url=""', (url, row['id']))
        if cover_url:
            conn.execute('UPDATE videos SET cover_url=? WHERE id=?', (cover_url, row['id']))
        return row['id'], False
    else:
        conn.execute(
            """INSERT INTO videos
               (account_id, platform, account_name, aweme_id, title, duration, url, first_seen, cover_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, platform, account_name, aweme_id, title, duration,
             url, create_time or now, cover_url)
        )
        vid = conn.execute(
            'SELECT id FROM videos WHERE platform=? AND aweme_id=?',
            (platform, aweme_id)
        ).fetchone()['id']
        return vid, True


def add_snapshot(conn, video_id, collected_at, play_count=0, digg_count=0,
                 comment_count=0, share_count=0, collect_count=0):
    cur = conn.execute(
        'SELECT id FROM snapshots WHERE video_id=? AND collected_at=?',
        (video_id, collected_at)
    )
    if cur.fetchone():
        return False
    conn.execute(
        """INSERT INTO snapshots
           (video_id, collected_at, play_count, digg_count,
            comment_count, share_count, collect_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (video_id, collected_at, play_count, digg_count,
         comment_count, share_count, collect_count)
    )
    return True


def _stderr_str(result):
    """跨平台安全获取 stderr 文本。"""
    try:
        return result.stderr.decode('utf-8', errors='replace')[:500]
    except Exception:
        return str(result.stderr)[:500]


# ── 抖音采集器 ─────────────────────────────────────────

def collect_douyin(conn, account):
    account_name = account['account_name']
    account_id = account['id']

    print(f"  [抖音] {account_name} — 开始采集...", flush=True)

    result = run_script("douyin", account_name)
    if result.returncode != 0:
        print(f"  [抖音] {account_name} — 采集失败: {_stderr_str(result)}", flush=True)
        return

    tmp_file = TMP_DIR / f"{account_name}.json"
    if not tmp_file.exists():
        print(f"  [抖音] {account_name} — 未生成结果文件", flush=True)
        return

    with open(str(tmp_file), 'r', encoding='utf-8') as f:
        result_data = json.load(f)

    if isinstance(result_data, dict):
        videos = result_data.get('videos', [])
        nickname = result_data.get('nickname', '')
    else:
        videos = result_data
        nickname = ''

    if not videos:
        print(f"  [抖音] {account_name} — 无视频数据", flush=True)
        raise Exception("无视频数据，可能cookie失效")

    if nickname and nickname != account['nickname']:
        conn.execute('UPDATE accounts SET nickname=? WHERE id=?', (nickname, account_id))
        print(f"  [抖音] {account_name} — 更新昵称: {nickname}", flush=True)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:00')
    new_count = 0
    snap_count = 0

    for v in videos:
        aweme_id = v.get('aweme_id', '')
        if not aweme_id:
            continue
        title = v.get('desc', '')
        duration = v.get('duration', 0)
        if isinstance(duration, (int, float)) and duration > 0:
            duration = round(duration / 1000)
        create_time = v.get('create_time', 0)
        if create_time:
            try:
                create_time = datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M:%S')
            except (OSError, ValueError):
                create_time = None
        video_id, is_new = ensure_video(
            conn, account_id, 'douyin', account_name,
            aweme_id, title, duration,
            v.get('share_url', '') or f'https://www.douyin.com/video/{aweme_id}',
            create_time, v.get('cover_url', '')
        )
        if is_new:
            new_count += 1
        added = add_snapshot(
            conn, video_id, now,
            play_count=v.get('play_count', 0),
            digg_count=v.get('digg_count', 0),
            comment_count=v.get('comment_count', 0),
            share_count=v.get('share_count', 0),
            collect_count=v.get('collect_count', 0),
        )
        if added:
            snap_count += 1

    conn.commit()
    print(f"  [抖音] {account_name} — 共 {len(videos)} 个视频, "
          f"新增 {new_count}, 快照 {snap_count}", flush=True)


# ── 快手采集器 ─────────────────────────────────────────

def collect_kuaishou(conn, account):
    account_name = account['account_name']
    account_id = account['id']

    print(f"  [快手] {account_name} — 开始采集...", flush=True)

    result = run_script("kuaishou", account_name)
    if result.returncode != 0:
        print(f"  [快手] {account_name} — 采集失败: {_stderr_str(result)}", flush=True)
        return

    tmp_file = TMP_DIR / f"kuaishou_{account_name}.json"
    if not tmp_file.exists():
        print(f"  [快手] {account_name} — 未生成结果文件", flush=True)
        return

    with open(str(tmp_file), 'r', encoding='utf-8') as f:
        result_data = json.load(f)

    if isinstance(result_data, dict):
        videos = result_data.get('videos', [])
        nickname = result_data.get('nickname', '')
    else:
        videos = result_data
        nickname = ''

    if not videos:
        print(f"  [快手] {account_name} — 无视频数据", flush=True)
        raise Exception("无视频数据，可能cookie失效")

    if nickname and nickname != account['nickname']:
        conn.execute('UPDATE accounts SET nickname=? WHERE id=?', (nickname, account_id))
        print(f"  [快手] {account_name} — 更新昵称: {nickname}", flush=True)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:00')
    new_count = 0
    snap_count = 0

    for v in videos:
        photo_id = v.get('photo_id', '') or v.get('aweme_id', '')
        if photo_id:
            aweme_id = f"ks_{photo_id}"
        else:
            dedup_key = f"{v.get('title','')}_{v.get('publish_time','')}"
            aweme_id = f"ks_{hashlib.md5(dedup_key.encode()).hexdigest()[:12]}"

        title = v.get('title', v.get('caption', ''))
        create_time = v.get('publish_time') or v.get('timestamp', 0)
        view_count = int(str(v.get('view_count', 0) or 0).replace(',', ''))
        like_count = int(str(v.get('like_count', 0) or 0).replace(',', ''))
        comment_count = int(str(v.get('comment_count', 0) or 0).replace(',', ''))

        video_id, is_new = ensure_video(
            conn, account_id, 'kuaishou', account_name,
            aweme_id, title, 0,
            f'https://www.kuaishou.com/short-video/{photo_id}' if photo_id else '',
            str(create_time) if create_time else None,
            v.get('cover_url', '')
        )
        if is_new:
            new_count += 1
        added = add_snapshot(
            conn, video_id, now,
            play_count=view_count,
            digg_count=like_count,
            comment_count=comment_count,
        )
        if added:
            snap_count += 1

    conn.commit()
    print(f"  [快手] {account_name} — 共 {len(videos)} 个视频, "
          f"新增 {new_count}, 快照 {snap_count}", flush=True)


# ── 小红书采集器 ──────────────────────────────────────

def collect_xiaohongshu(conn, account):
    account_name = account['account_name']
    account_id = account['id']

    print(f"  [小红书] {account_name} — 开始采集...", flush=True)

    result = run_script("xiaohongshu", account_name)
    if result.returncode != 0:
        print(f"  [小红书] {account_name} — 采集失败: {_stderr_str(result)}", flush=True)
        return

    tmp_file = TMP_DIR / f"xiaohongshu_{account_name}.json"
    if not tmp_file.exists():
        print(f"  [小红书] {account_name} — 未生成结果文件", flush=True)
        return

    with open(str(tmp_file), 'r', encoding='utf-8') as f:
        result_data = json.load(f)

    if isinstance(result_data, dict):
        videos = result_data.get('videos', [])
        nickname = result_data.get('nickname', '')
    else:
        videos = result_data
        nickname = ''

    if not videos:
        print(f"  [小红书] {account_name} — 无视频数据", flush=True)
        raise Exception("无视频数据，可能cookie失效")

    if nickname and nickname != account['nickname']:
        conn.execute('UPDATE accounts SET nickname=? WHERE id=?', (nickname, account_id))
        print(f"  [小红书] {account_name} — 更新昵称: {nickname}", flush=True)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:00')
    new_count = 0
    snap_count = 0

    for v in videos:
        note_id = v.get('id', '')
        if not note_id:
            continue
        aweme_id = f"xhs_{note_id}"
        title = v.get('title', '')
        create_time = v.get('date', '')
        views = int(v.get('views', 0) or 0)
        likes = int(v.get('likes', 0) or 0)
        collects = int(v.get('collects', 0) or 0)
        comments = int(v.get('comments', 0) or 0)

        video_id, is_new = ensure_video(
            conn, account_id, 'xiaohongshu', account_name,
            aweme_id, title, 0,
            f'https://www.xiaohongshu.com/discovery/item/{note_id}',
            str(create_time) if create_time else None,
            v.get('cover_url', '')
        )
        if is_new:
            new_count += 1
        added = add_snapshot(
            conn, video_id, now,
            play_count=views, digg_count=likes,
            comment_count=comments, collect_count=collects,
        )
        if added:
            snap_count += 1

    conn.commit()
    print(f"  [小红书] {account_name} — 共 {len(videos)} 个笔记, "
          f"新增 {new_count}, 快照 {snap_count}", flush=True)


# ── 视频号采集器 ─────────────────────────────────────

def collect_shipinhao(conn, account):
    account_name = account['account_name']
    account_id = account['id']

    print(f"  [视频号] {account_name} — 开始采集...", flush=True)

    result = run_script("shipinhao", account_name)
    if result.returncode != 0:
        print(f"  [视频号] {account_name} — 采集失败: {_stderr_str(result)}", flush=True)
        return

    tmp_file = TMP_DIR / f"shipinhao_{account_name}.json"
    if not tmp_file.exists():
        print(f"  [视频号] {account_name} — 未生成结果文件", flush=True)
        return

    with open(str(tmp_file), 'r', encoding='utf-8') as f:
        result_data = json.load(f)

    if isinstance(result_data, dict):
        videos = result_data.get('videos', [])
        nickname = result_data.get('nickname', '')
    else:
        videos = result_data
        nickname = ''

    if not videos:
        print(f"  [视频号] {account_name} — 无视频数据", flush=True)
        raise Exception("无视频数据，可能cookie失效")

    if nickname:
        nick_clean = nickname.replace('\n', '').strip()
        if nick_clean and nick_clean != account['nickname']:
            conn.execute('UPDATE accounts SET nickname=? WHERE id=?', (nick_clean[:30], account_id))
            print(f"  [视频号] {account_name} — 更新昵称: {nick_clean}", flush=True)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:00')
    new_count = 0
    snap_count = 0

    for v in videos:
        object_id = v.get('object_id', '')
        if not object_id:
            continue
        aweme_id = f"sph_{object_id.split('/')[-1][:20]}" if '/' in object_id else f"sph_{object_id[:20]}"
        real_id = object_id.split('/')[-1] if '/' in object_id else object_id

        title = v.get('title', '')
        create_time = v.get('create_time', '')

        video_id, is_new = ensure_video(
            conn, account_id, 'shipinhao', account_name,
            aweme_id, title, v.get('duration', 0),
            f'https://channels.weixin.qq.com/post/{real_id}',
            str(create_time) if create_time else None,
            v.get('cover_url', '')
        )
        if is_new:
            new_count += 1
        added = add_snapshot(
            conn, video_id, now,
            play_count=v.get('read_count', 0),
            digg_count=v.get('like_count', 0),
            comment_count=v.get('comment_count', 0),
            share_count=v.get('forward_count', 0),
            collect_count=v.get('fav_count', 0),
        )
        if added:
            snap_count += 1

    conn.commit()
    print(f"  [视频号] {account_name} — 共 {len(videos)} 个视频, "
          f"新增 {new_count}, 快照 {snap_count}", flush=True)


# ── 主入口 ──────────────────────────────────────────────

_COLLECT_RESULTS = []


def collect_platform(conn, platform: str, accounts):
    print(f"\n{'='*50}")
    print(f"平台: {platform} | 账号数: {len(accounts)}")
    print(f"{'='*50}")

    collectors = {
        'douyin': collect_douyin,
        'kuaishou': collect_kuaishou,
        'xiaohongshu': collect_xiaohongshu,
        'shipinhao': collect_shipinhao,
    }
    collector = collectors.get(platform)
    if not collector:
        print(f"  [跳过] {platform} 采集器未实现")
        return

    for acct in accounts:
        nick = acct['nickname'] or acct['account_name']

        # Cookie 文件预检
        if platform in ('douyin', 'kuaishou', 'xiaohongshu'):
            cookie_path = COOKIES_DIR / f"{platform}_{acct['account_name']}.json"
            if cookie_path.exists():
                age_days = (datetime.now().timestamp() - cookie_path.stat().st_mtime) / 86400
                if age_days > config.collect_cookie_max_age_days():
                    print(f"  [跳过] {nick} — cookie 文件 {age_days:.0f} 天未更新，可能已失效", flush=True)
                    conn.execute('UPDATE accounts SET cookie_status=? WHERE id=?', ('failed', acct['id']))
                    conn.commit()
                    _COLLECT_RESULTS.append({
                        'platform': platform, 'account': acct['account_name'], 'nickname': nick,
                        'status': 'error', 'message': f'cookie 文件 {age_days:.0f} 天未更新'
                    })
                    continue

        try:
            collector(conn, acct)
            _COLLECT_RESULTS.append({'platform': platform, 'account': acct['account_name'], 'nickname': nick, 'status': 'ok'})
            conn.execute('UPDATE accounts SET cookie_status=? WHERE id=?', ('ok', acct['id']))
            conn.commit()
        except Exception as e:
            delay = config.collect_retry_delay()
            print(f"  [重试] {nick} — 失败: {str(e)[:60]}，{delay}秒后重试...", flush=True)
            time.sleep(delay)
            try:
                collector(conn, acct)
                _COLLECT_RESULTS.append({'platform': platform, 'account': acct['account_name'], 'nickname': nick, 'status': 'ok'})
                conn.execute('UPDATE accounts SET cookie_status=? WHERE id=?', ('ok', acct['id']))
                conn.commit()
                print(f"  [重试] {nick} — 重试成功", flush=True)
            except Exception as e2:
                err_msg = str(e2)[:100]
                _COLLECT_RESULTS.append({'platform': platform, 'account': acct['account_name'], 'nickname': nick, 'status': 'error', 'message': err_msg})
                conn.execute('UPDATE accounts SET cookie_status=? WHERE id=?', ('failed', acct['id']))
                conn.commit()
                print(f"  [错误] {platform}/{acct['account_name']}: {e2}", flush=True)


def write_status(status, progress='', done=0, total=0, results=None):
    status_path = MONITOR_DIR / 'collect_status.json'
    try:
        with open(status_path, 'r') as f:
            existing = json.load(f)
    except Exception:
        existing = {'status': 'running', 'lines': [], 'results': []}
    existing['status'] = status
    existing['progress'] = progress
    existing['done'] = done
    existing['total'] = total
    if progress and progress not in existing.get('lines', []):
        existing.setdefault('lines', []).append(progress)
    if results:
        existing['results'] = results
    try:
        with open(status_path, 'w') as f:
            json.dump(existing, f, ensure_ascii=False)
    except Exception:
        pass


def collect_account_stats(conn, platform, accounts):
    for account in accounts:
        account_name = account['account_name']
        account_id = account['id']
        print(f"  [账号统计] {platform}/{account_name} — 开始采集...", flush=True)

        result = run_script("stats", platform, account_name)
        if result.returncode != 0:
            print(f"  [账号统计] {platform}/{account_name} — 失败: {_stderr_str(result)}", flush=True)
            _COLLECT_RESULTS.append({
                'platform': platform, 'account': account_name,
                'nickname': account['nickname'] or account_name,
                'status': 'error', 'message': f'账号统计采集失败: {_stderr_str(result)}'
            })
            continue

        tmp_file = TMP_DIR / f"stats_{platform}_{account_name}.json"
        if not tmp_file.exists():
            print(f"  [账号统计] {platform}/{account_name} — 未生成结果文件", flush=True)
            _COLLECT_RESULTS.append({
                'platform': platform, 'account': account_name,
                'nickname': account['nickname'] or account_name,
                'status': 'error', 'message': '账号统计: 未生成结果文件'
            })
            continue

        with open(str(tmp_file), 'r', encoding='utf-8') as f:
            stats = json.load(f)

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            '''UPDATE accounts SET
               follower_count=?, total_digg_count=?, total_play_count=?,
               total_following_count=?, profile_bio=?, profile_douyin_id=?,
               profile_avatar_url=?, profile_like_count=?, account_stats_updated=?
               WHERE id=?''',
            (stats.get('follower_count', 0),
             stats.get('total_digg_count', 0),
             stats.get('total_play_count', 0),
             stats.get('total_following_count', 0),
             stats.get('profile_bio', ''),
             stats.get('profile_douyin_id', ''),
             stats.get('profile_avatar_url', ''),
             stats.get('profile_like_count', 0),
             now, account_id)
        )
        conn.commit()
        msg = f'粉丝={stats.get("follower_count",0)}, 获赞={stats.get("total_digg_count",0)}'
        print(f"  [账号统计] {platform}/{account_name} — {msg}", flush=True)
        _COLLECT_RESULTS.append({
            'platform': platform, 'account': account_name,
            'nickname': account['nickname'] or account_name,
            'status': 'ok', 'message': msg
        })
        try:
            tmp_file.unlink()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='Social Monitor Collector')
    parser.add_argument('--platform', choices=['douyin', 'kuaishou', 'xiaohongshu', 'shipinhao'])
    parser.add_argument('--account')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--stats-only', action='store_true',
                        help='仅采集账号统计数据（粉丝数等），不采集视频数据')
    args = parser.parse_args()

    # 确保 tmp 目录存在
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db()
    accounts = get_active_accounts(conn, args.platform, args.account)

    if not accounts:
        print("没有找到需要采集的账号")
        sys.exit(0)

    print(f"📡 Social Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if config.is_wsl():
        print(f"   运行环境: WSL")
    else:
        print(f"   运行环境: {config._SYSTEM}")

    write_status('running', '启动...', 0, len(accounts))

    platforms = {}
    for acct in accounts:
        platforms.setdefault(acct['platform'], []).append(acct)

    total = len(accounts)
    done = 0
    for platform, accts in platforms.items():
        if args.dry_run:
            print(f"\n  [DRY-RUN] {platform}: {len(accts)} 个账号")
            for a in accts:
                names = []
                if a['nickname']:
                    names.append(f"nick={a['nickname']}")
                extra = f" ({', '.join(names)})" if names else ""
                print(f"    - {a['account_name']}{extra}")
        elif args.stats_only:
            collect_account_stats(conn, platform, accts)
            done += len(accts)
            write_status('running', f'{platform} 账号统计完成', done, total)
        else:
            collect_platform(conn, platform, accts)
            done += len(accts)
            write_status('running', f'{platform} 完成', done, total)

    conn.close()
    write_status('success', '全部完成', total, total)

    try:
        status_path = MONITOR_DIR / 'collect_status.json'
        with open(status_path, 'r') as f:
            existing = json.load(f)
        existing['results'] = _COLLECT_RESULTS
        with open(status_path, 'w') as f:
            json.dump(existing, f, ensure_ascii=False)
    except Exception:
        pass

    print(f"\n✅ 完成 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
