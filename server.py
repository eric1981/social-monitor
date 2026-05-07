#!/usr/bin/env python3
"""
Social Monitor — 轻量 API 服务
为前端提供数据接口，监听 localhost:5408
"""

import json
import sqlite3
import subprocess
import sys
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
    # 计算昨日和前天的日期边界，取当天最后一次采集时间
    now = datetime.now()
    yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_before_start = yesterday_start - timedelta(days=1)

    def get_day_latest(conn, start, end):
        row = conn.execute(
            'SELECT MAX(collected_at) as t FROM snapshots WHERE collected_at >= ? AND collected_at < ?',
            (start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S'))
        ).fetchone()
        return row['t'] if row and row['t'] else None

    yesterday_ts = get_day_latest(conn, yesterday_start, yesterday_end)
    day_before_ts = get_day_latest(conn, day_before_start, yesterday_start)

    # 预加载昨日和前天的快照数据：{video_id: play_count}
    yesterday_plays = {}
    day_before_plays = {}
    if yesterday_ts:
        for r in conn.execute('SELECT video_id, play_count FROM snapshots WHERE collected_at=?', (yesterday_ts,)):
            yesterday_plays[r['video_id']] = r['play_count']
    if day_before_ts:
        for r in conn.execute('SELECT video_id, play_count FROM snapshots WHERE collected_at=?', (day_before_ts,)):
            day_before_plays[r['video_id']] = r['play_count']

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
                parts = raw.replace('年', '-').replace('月', '-').replace('日', '').split(' ')
                dparts = parts[0].split('-')
                if len(dparts) == 3:
                    v['first_seen'] = f"{dparts[0].strip()}-{dparts[1].strip().zfill(2)}-{dparts[2].strip().zfill(2)} {parts[1].strip() if len(parts) > 1 else '00:00'}:00"
            except:
                pass
        # 昨日播放增量：昨天最后采集的播放量 - 前天最后采集的播放量
        today_play = v['play_count']
        yesterday_play = yesterday_plays.get(v['id'], 0)
        day_before_play = day_before_plays.get(v['id'], 0)
        v['yesterday_views'] = yesterday_play - day_before_play  # 单日新增
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
                    'SELECT id, platform, account_name, nickname, is_active FROM accounts ORDER BY platform, id'
                )
            ]
            conn.close()
            json_response(self, {'accounts': accounts})

        else:
            filepath = FRONTEND_DIR / parsed.path.lstrip('/')
            if not filepath.exists() or not filepath.is_file():
                filepath = FRONTEND_DIR / 'index.html'

            ct_map = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css'}
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
                subprocess.Popen(
                    [sys.executable or 'python3', str(COLLECTOR)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=str(MONITOR_DIR)
                )
                json_response(self, {'status': 'ok', 'message': '采集已启动'})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

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
