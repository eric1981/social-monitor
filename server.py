#!/usr/bin/env python3
"""
Social Monitor — 轻量 API 服务
为前端提供数据接口，监听 localhost:5408
"""

import json
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

MONITOR_DIR = Path(__file__).parent
DB_PATH = MONITOR_DIR / "monitor.db"
FRONTEND_DIR = MONITOR_DIR / "frontend"
COLLECTOR = MONITOR_DIR / "collector.py"
PORT = 5408


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def query_data():
    conn = get_db()
    accounts = [
        dict(r) for r in conn.execute(
            'SELECT id, platform, account_name, nickname, is_active FROM accounts WHERE is_active=1'
        )
    ]
    nickname_map = {a['account_name']: (a['nickname'] or a['account_name']) for a in accounts}

    def build_url(v):
        p = v['platform']
        vid = v['aweme_id']
        if p == 'douyin':
            return f'https://www.douyin.com/video/{vid}'
        elif p == 'kuaishou':
            return f'https://www.kuaishou.com/short-video/{vid.replace("ks_", "")}' if vid.startswith('ks_') else ''
        elif p == 'xiaohongshu':
            return f'https://www.xiaohongshu.com/discovery/item/{vid.replace("xhs_", "")}' if vid.startswith('xhs_') else ''
        elif p == 'shipinhao':
            return f'https://channels.weixin.qq.com/post/{vid.replace("sph_", "")}' if vid.startswith('sph_') else ''
        return ''

    videos = []
    # 计算昨日和前天的日期边界
    now = datetime.now()
    yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_before_start = yesterday_start - timedelta(days=1)

    # 预加载所有视频在昨天和前天的快照（按 video_id 分别取最后一条）
    def day_snapshot_map(conn, day_start, day_end):
        rows = conn.execute('''
            SELECT s.video_id, s.play_count
            FROM snapshots s
            INNER JOIN (
                SELECT video_id, MAX(collected_at) as max_ts
                FROM snapshots
                WHERE collected_at >= ? AND collected_at < ?
                GROUP BY video_id
            ) latest ON s.video_id = latest.video_id AND s.collected_at = latest.max_ts
        ''', (day_start, day_end)).fetchall()
        return {r['video_id']: r['play_count'] for r in rows}

    yesterday_plays = day_snapshot_map(conn, yesterday_start.strftime('%Y-%m-%d %H:%M:%S'), yesterday_end.strftime('%Y-%m-%d %H:%M:%S'))
    day_before_plays = day_snapshot_map(conn, day_before_start.strftime('%Y-%m-%d %H:%M:%S'), yesterday_start.strftime('%Y-%m-%d %H:%M:%S'))

    cur = conn.execute('''
        SELECT v.id, v.platform, v.account_name, v.aweme_id, v.title,
               v.first_seen, v.url, v.cover_url,
               s.collected_at, s.play_count, s.digg_count,
               s.comment_count, s.share_count, s.collect_count
        FROM videos v
        JOIN snapshots s ON s.video_id = v.id
        WHERE s.collected_at = (
            SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id = s.video_id
        )
    ''')
    for r in cur:
        v = dict(r)
        # 标准化 first_seen 格式：统一为 "YYYY-MM-DD HH:MM:SS"
        raw = v.get('first_seen', '') or ''
        if '年' in raw:
            try:
                # 先去掉 "定时发布 "、"发布于 " 等前缀
                clean = raw.replace('定时发布 ', '').replace('发布于 ', '')
                parts = clean.replace('年', '-').replace('月', '-').replace('日', '').split(' ')
                dparts = parts[0].split('-')
                if len(dparts) == 3:
                    v['first_seen'] = f"{dparts[0].strip()}-{dparts[1].strip().zfill(2)}-{dparts[2].strip().zfill(2)} {parts[1].strip() if len(parts) > 1 else '00:00'}:00"
            except:
                pass
        # 昨日播放增量：昨天最后采集的播放量 - 前天最后采集的播放量
        today_play = v['play_count']
        yesterday_play = yesterday_plays.get(v['id'], None)
        day_before_play = day_before_plays.get(v['id'], None)
        if yesterday_play is not None and day_before_play is not None:
            v['yesterday_views'] = yesterday_play - day_before_play
        elif yesterday_play is not None:
            v['yesterday_views'] = yesterday_play
        else:
            v['yesterday_views'] = 0
        # 今日增量 = 最新播放 - 昨日最后播放
        if yesterday_play is not None:
            v['play_delta'] = today_play - yesterday_play
        else:
            v['play_delta'] = 0
        v['nickname'] = nickname_map.get(v['account_name'], v['account_name'])
        v['url'] = v.get('url') or build_url(v)
        videos.append(v)

    conn.close()
    return {'accounts': accounts, 'videos': videos}


def json_response(handler, data, status=200):
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def read_body(handler):
    length = int(handler.headers.get('Content-Length', 0))
    if length:
        return handler.rfile.read(length).decode('utf-8')
    return ''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/data':
            try:
                json_response(self, query_data())
            except Exception as e:
                json_response(self, {'error': str(e)}, 500)

        elif parsed.path == '/api/accounts':
            conn = get_db()
            accounts = [
                dict(r) for r in conn.execute(
                    'SELECT id, platform, account_name, nickname, is_active, follower_count, total_digg_count, total_play_count, total_following_count, profile_bio, profile_douyin_id, profile_avatar_url, profile_like_count, cookie_status FROM accounts ORDER BY platform, id'
                )
            ]
            conn.close()
            json_response(self, {'accounts': accounts})

        elif parsed.path == '/api/health':
            conn = get_db()
            rows = conn.execute(
                "SELECT platform, COUNT(*) as total, SUM(CASE WHEN cookie_status='ok' THEN 1 ELSE 0 END) as ok "
                "FROM accounts WHERE is_active=1 GROUP BY platform"
            ).fetchall()
            # 数据断档检测：每个平台最近一次快照时间
            stale = conn.execute("""
                SELECT v.platform, MAX(s.collected_at) as last_snap,
                       CAST(julianday('now') - julianday(MAX(s.collected_at)) AS INTEGER) as days_stale
                FROM snapshots s JOIN videos v ON s.video_id=v.id
                WHERE v.platform IN ('douyin','kuaishou','xiaohongshu','shipinhao')
                GROUP BY v.platform
            """).fetchall()
            conn.close()
            health = {}
            for r in rows:
                health[r['platform']] = {'total': r['total'], 'ok': r['ok'], 'failed': r['total'] - r['ok']}
            for r in stale:
                if r['platform'] in health:
                    health[r['platform']]['last_snap'] = r['last_snap']
                    health[r['platform']]['days_stale'] = r['days_stale']
            json_response(self, health)

        elif parsed.path == '/api/compare':
            conn = get_db()
            rows = conn.execute("""
                SELECT account_name, platform, nickname, cookie_status,
                       follower_count, total_digg_count, total_play_count
                FROM accounts WHERE is_active=1
                ORDER BY account_name, platform
            """).fetchall()
            conn.close()
            groups = {}
            for r in rows:
                name = r['account_name']
                if name not in groups:
                    groups[name] = {'account_name': name, 'platforms': {}}
                groups[name]['platforms'][r['platform']] = {
                    'nickname': r['nickname'], 'cookie_status': r['cookie_status'],
                    'followers': r['follower_count'], 'diggs': r['total_digg_count'],
                    'plays': r['total_play_count']
                }
            json_response(self, {'groups': list(groups.values())})

        elif parsed.path == '/api/collect/stats':
            # 触发采集账号统计数据
            try:
                subprocess.Popen(
                    [sys.executable or 'python3', str(COLLECTOR), '--stats-only'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=str(MONITOR_DIR)
                )
                json_response(self, {'status': 'ok'})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

        elif parsed.path.startswith('/api/account/'):
            try:
                parts = parsed.path.split('/')
                account_id = parts[3] if len(parts) >= 4 else ''
                platform_filter = parts[4] if len(parts) >= 5 else None

                # /api/account/<id>/growth — 账号播放/点赞增长曲线
                if platform_filter == 'growth':
                    conn = get_db()
                    account = conn.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
                    if not account:
                        json_response(self, {'error': '账号不存在'}, 404)
                        conn.close()
                        return
                    related = conn.execute(
                        'SELECT id FROM accounts WHERE account_name=?',
                        (account['account_name'],)
                    ).fetchall()
                    related_ids = [r['id'] for r in related]
                    placeholders = ','.join('?' * len(related_ids))
                    rows = conn.execute(f"""
                        SELECT DATE(s.collected_at) as d,
                               SUM(s.play_count) as total_play, SUM(s.digg_count) as total_digg,
                               SUM(s.comment_count) as total_comment
                        FROM snapshots s JOIN videos v ON s.video_id=v.id
                        WHERE v.account_id IN ({placeholders})
                        GROUP BY DATE(s.collected_at) ORDER BY d
                    """, related_ids).fetchall()
                    conn.close()
                    points = [{'date': r['d'], 'play': r['total_play'], 'digg': r['total_digg'],
                               'comment': r['total_comment']} for r in rows]
                    json_response(self, {'points': points})
                    return

                conn = get_db()

                # 账号信息
                account = conn.execute(
                    'SELECT * FROM accounts WHERE id=?', (account_id,)
                ).fetchone()
                if not account:
                    json_response(self, {'error': '账号不存在'}, 404)
                    conn.close()
                    return

                account = dict(account)

                # 查询此 account_name 在所有平台上的数据
                # 该账号可能在不同平台有不同记录，通过 account_name 关联
                related_accounts = conn.execute(
                    'SELECT * FROM accounts WHERE account_name=? ORDER BY platform',
                    (account['account_name'],)
                ).fetchall()

                # 汇总信息
                total_followers = sum(r['follower_count'] or 0 for r in related_accounts)
                total_digg = sum(r['total_digg_count'] or 0 for r in related_accounts)
                total_play = sum(r['total_play_count'] or 0 for r in related_accounts)

                by_platform = {}
                all_videos = []

                for ra in related_accounts:
                    p = ra['platform']
                    # 获取该平台下的视频
                    video_rows = conn.execute('''
                        SELECT v.id, v.platform, v.account_name, v.aweme_id, v.title,
                               v.first_seen, v.url, v.cover_url,
                               s.collected_at, s.play_count, s.digg_count,
                               s.comment_count, s.share_count, s.collect_count
                        FROM videos v
                        JOIN snapshots s ON s.video_id = v.id
                        WHERE v.account_id = ?
                          AND s.collected_at = (
                              SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id = s.video_id
                          )
                        ORDER BY s.collected_at DESC
                    ''', (ra['id'],)).fetchall()

                    videos = [dict(r) for r in video_rows]
                    platform_videos = videos
                    all_videos.extend(videos)

                    total_video_play = sum(v.get('play_count', 0) or 0 for v in videos)
                    total_video_digg = sum(v.get('digg_count', 0) or 0 for v in videos)

                    by_platform[p] = {
                        'account': dict(ra),
                        'videos': platform_videos if not platform_filter or p == platform_filter else [],
                        'video_count': len(videos),
                        'total_play': total_video_play,
                        'total_digg': total_video_digg,
                    }

                if platform_filter:
                    all_videos = by_platform.get(platform_filter, {}).get('videos', [])

                result = {
                    'account': account,
                    'related_accounts': [dict(r) for r in related_accounts],
                    'summary': {
                        'total_followers': total_followers,
                        'total_digg': total_digg,
                        'total_play': total_play,
                        'total_videos': len(all_videos),
                        'platforms': list(by_platform.keys()),
                        'stats_updated': account.get('account_stats_updated', ''),
                    },
                    'by_platform': by_platform,
                    'videos': all_videos,
                }

                conn.close()
                json_response(self, result)
            except Exception as e:
                json_response(self, {'error': str(e)}, 500)

        elif parsed.path == '/api/collect/log':
            log_path = MONITOR_DIR / 'collect_status.json'
            if log_path.exists():
                try:
                    with open(log_path) as f:
                        st = json.load(f)
                    json_response(self, st)
                except:
                    json_response(self, {'status': 'idle', 'lines': []})
            else:
                json_response(self, {'status': 'idle', 'lines': []})

        elif parsed.path == '/api/trend':
            try:
                conn = get_db()
                from urllib.parse import parse_qs
                qs = parse_qs(parsed.query)
                video_id = qs.get('video_id', [None])[0]
                if not video_id:
                    json_response(self, {'error': '缺少 video_id'}, 400)
                    return
                rows = conn.execute('''
                    SELECT s.collected_at, s.play_count, s.digg_count,
                           s.comment_count, s.share_count, s.collect_count,
                           v.title, v.platform, v.account_name
                    FROM snapshots s
                    JOIN videos v ON v.id = s.video_id
                    WHERE s.video_id = ?
                    ORDER BY s.collected_at
                ''', (video_id,)).fetchall()
                conn.close()
                points = [{
                    'collected_at': r['collected_at'][:16],
                    'play': r['play_count'],
                    'digg': r['digg_count'],
                    'comment': r['comment_count'],
                    'share': r['share_count'],
                    'collect': r['collect_count'],
                } for r in rows]
                meta = {'title': rows[0]['title'] if rows else '', 'platform': rows[0]['platform'] if rows else '', 'account': rows[0]['account_name'] if rows else ''}
                json_response(self, {'meta': meta, 'points': points})
            except Exception as e:
                json_response(self, {'error': str(e)}, 500)

        elif parsed.path == '/api/export/accounts':
            conn = get_db()
            rows = conn.execute("""SELECT platform, account_name, nickname, cookie_status,
                follower_count, total_digg_count, total_play_count, account_stats_updated
                FROM accounts WHERE is_active=1 ORDER BY platform, id""").fetchall()
            conn.close()
            csv = '平台,账号名,昵称,Cookie状态,粉丝,获赞,播放,统计更新时间\n'
            for r in rows:
                csv += f'{r["platform"]},{r["account_name"]},{r["nickname"] or ""},{r["cookie_status"]},{r["follower_count"] or 0},{r["total_digg_count"] or 0},{r["total_play_count"] or 0},{r["account_stats_updated"] or ""}\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename=social-monitor-accounts.csv')
            self.end_headers()
            self.wfile.write(csv.encode('utf-8-sig'))

        elif parsed.path == '/api/export/videos':
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query)
            account_id = qs.get('account_id', [None])[0]
            conn = get_db()
            if account_id:
                rows = conn.execute("""SELECT v.platform, v.account_name, v.title, v.aweme_id, v.first_seen,
                    s.play_count, s.digg_count, s.comment_count, s.share_count, s.collect_count, s.collected_at
                    FROM videos v JOIN snapshots s ON s.video_id=v.id
                    WHERE v.account_id=? AND s.collected_at=(SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id=v.id)
                    ORDER BY s.play_count DESC""", (account_id,)).fetchall()
            else:
                rows = conn.execute("""SELECT v.platform, v.account_name, v.title, v.aweme_id, v.first_seen,
                    s.play_count, s.digg_count, s.comment_count, s.share_count, s.collect_count, s.collected_at
                    FROM videos v JOIN snapshots s ON s.video_id=v.id
                    WHERE s.collected_at=(SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id=v.id)
                    ORDER BY v.platform, s.play_count DESC""").fetchall()
            conn.close()
            csv = '平台,账号,标题,视频ID,发布时间,播放,点赞,评论,分享,收藏,采集时间\n'
            for r in rows:
                title = (r['title'] or '').replace(',', '，').replace('\n', ' ')
                csv += f'{r["platform"]},{r["account_name"]},{title},{r["aweme_id"]},{r["first_seen"] or ""},{r["play_count"]},{r["digg_count"]},{r["comment_count"]},{r["share_count"]},{r["collect_count"]},{r["collected_at"]}\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8-sig')
            self.send_header('Content-Disposition', 'attachment; filename=social-monitor-videos.csv')
            self.end_headers()
            self.wfile.write(csv.encode('utf-8-sig'))

        elif parsed.path.startswith('/proxy/image'):
            from urllib.parse import parse_qs, unquote
            qs = parse_qs(parsed.query)
            url = qs.get('url', [''])[0]
            if not url:
                self.send_error(400, 'Missing url')
                return
            try:
                req = urllib.request.Request(url, headers={
                    'Referer': 'https://www.kuaishou.com/',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'Sec-Fetch-Dest': 'image',
                    'Sec-Fetch-Mode': 'no-cors',
                    'Sec-Fetch-Site': 'cross-site',
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    ct = resp.headers.get('Content-Type', 'image/jpeg')
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                # 返回透明占位图，让前端 @error 能正常处理
                placeholder = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xe2\xe2\x00\x00\x00\x00IEND\xaeB`\x82'
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(placeholder)

        else:
            filepath = FRONTEND_DIR / parsed.path.lstrip('/')
            if not filepath.exists() or not filepath.is_file():
                filepath = FRONTEND_DIR / 'index.html'

            ct_map = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml'}
            ct = ct_map.get(filepath.suffix, 'application/octet-stream')

            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(str(filepath), 'rb') as f:
                self.wfile.write(f.read())

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/login':
            body = json.loads(read_body(self))
            platform = body.get('platform', '')
            account_name = body.get('account_name', '')

            if not platform or not account_name:
                json_response(self, {'error': '缺少 platform 或 account_name'}, 400)
                return

            conn = get_db()
            dup = conn.execute(
                'SELECT id FROM accounts WHERE platform=? AND account_name=?',
                (platform, account_name)
            ).fetchone()
            if not dup:
                conn.execute(
                    'INSERT OR IGNORE INTO accounts (platform, account_name, is_active) VALUES (?, ?, 0)',
                    (platform, account_name)
                )
                conn.commit()
            conn.close()

            subprocess.Popen(
                ['cmd.exe', '/c', 'python',
                 r'C:\Users\NINGMEI\Desktop\social-monitor\win_login.py',
                 platform, account_name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            json_response(self, {
                'status': 'ok',
                'message': f'扫码窗口已打开，请在 Windows 上扫码登录 {platform}',
            })

        elif parsed.path == '/api/account/toggle':
            body = json.loads(read_body(self))
            account_id = body.get('id')
            is_active = body.get('is_active', 1)
            conn = get_db()
            conn.execute('UPDATE accounts SET is_active=? WHERE id=?', (is_active, account_id))
            conn.commit()
            conn.close()
            json_response(self, {'status': 'ok'})

        elif parsed.path == '/api/collect':
            # 后台触发一次全平台采集
            try:
                log_path = MONITOR_DIR / 'collect_status.json'
                with open(log_path, 'w') as f:
                    json.dump({'status': 'running', 'lines': []}, f)
                subprocess.Popen(
                    [sys.executable or 'python3', str(COLLECTOR)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=str(MONITOR_DIR)
                )
                json_response(self, {'status': 'ok'})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

        elif parsed.path == '/api/collect/log':
            log_path = MONITOR_DIR / 'collect_status.json'
            if log_path.exists():
                try:
                    with open(log_path) as f:
                        st = json.load(f)
                    json_response(self, st)
                except:
                    json_response(self, {'status': 'idle', 'lines': []})
            else:
                json_response(self, {'status': 'idle', 'lines': []})

        elif parsed.path.startswith('/api/relogin'):
            if parsed.path == '/api/relogin/status':
                """查询扫码登录状态（GET）"""
                status_path = MONITOR_DIR / 'relogin_status.json'
                if status_path.exists():
                    try:
                        with open(status_path) as f:
                            st = json.load(f)
                        account_name = st.get('account_name', '')
                        platform = st.get('platform', '')
                        done_file = Path("/mnt/c/Users/NINGMEI/Desktop/social-monitor/social-auto-upload/cookies") / f'.{platform}_{account_name}_done'
                        if done_file.exists():
                            win_cookies = Path("/mnt/c/Users/NINGMEI/Desktop/social-monitor/social-auto-upload/cookies")
                            src_file = win_cookies / f'{platform}_{account_name}.json'
                            dst = MONITOR_DIR / 'social-auto-upload' / 'cookies' / f'{platform}_{account_name}.json'
                            if src_file.exists():
                                import shutil
                                shutil.copy2(str(src_file), str(dst))
                            done_file.unlink(missing_ok=True)
                            st['status'] = 'success'
                            st['message'] = '扫码登录成功'
                            with open(status_path, 'w') as f:
                                json.dump(st, f, ensure_ascii=False)
                        json_response(self, st)
                    except:
                        json_response(self, {'status': 'idle', 'message': '无扫码登录任务'})
                else:
                    json_response(self, {'status': 'idle', 'message': '无扫码登录任务'})
            else:
                """POST /api/relogin/douyin/benxian-app — 后台启动扫码"""
                parts = parsed.path.split('/')
                if len(parts) >= 5:
                    platform = parts[3]
                    account_name = parts[4]
                    try:
                        import shutil
                        src = MONITOR_DIR / 'social-auto-upload' / 'cookies' / f'{platform}_{account_name}.json'
                        win_cookies = Path("/mnt/c/Users/NINGMEI/Desktop/social-monitor/social-auto-upload/cookies")
                        win_cookies.mkdir(parents=True, exist_ok=True)
                        if src.exists():
                            shutil.copy2(str(src), str(win_cookies / f'{platform}_{account_name}.json'))

                        log_path = MONITOR_DIR / 'relogin_status.json'
                        with open(log_path, 'w') as f:
                            json.dump({'status': 'running', 'platform': platform, 'account_name': account_name,
                                       'message': f'正在打开浏览器扫码登录 {platform}/{account_name}...'}, f)

                        win_relogin = r'C:\Users\NINGMEI\Desktop\social-monitor\win_relogin.py'
                        subprocess.Popen(
                            ['cmd.exe', '/c', 'start', '/wait', 'python', win_relogin, platform, account_name,
                             '&&', 'echo', 'DONE', '>', str(win_cookies / f'.{platform}_{account_name}_done')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        json_response(self, {'status': 'ok', 'message': '扫码登录已启动，请查看浏览器窗口'})
                    except Exception as e:
                        json_response(self, {'status': 'error', 'message': str(e)}, 500)
                else:
                    json_response(self, {'status': 'error', 'message': '参数不足: /api/relogin/{platform}/{account}'}, 400)

        else:
            json_response(self, {'error': 'not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    print(f"📡 Social Monitor API — http://localhost:{PORT}")
    print(f"   前端页面: http://localhost:{PORT}")
    print(f"   API接口:  http://localhost:{PORT}/api/data")
    print(f"   新增账号: POST http://localhost:{PORT}/api/login")
    print()

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()
