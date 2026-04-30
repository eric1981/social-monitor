#!/usr/bin/env python3
"""
Social Monitor — 轻量 API 服务
为前端提供数据接口，监听 localhost:5408
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

MONITOR_DIR = Path(__file__).parent
DB_PATH = MONITOR_DIR / "monitor.db"
FRONTEND_DIR = MONITOR_DIR / "frontend"
COLLECTOR = MONITOR_DIR / "collector.py"
PORT = 5408


def query_data():
    """从数据库读取数据，返回前端需要的格式"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 账号列表 + nickname map
    accounts = [
        dict(r) for r in conn.execute(
            'SELECT id, platform, account_name, nickname, is_active FROM accounts WHERE is_active=1'
        )
    ]
    nickname_map = {a['account_name']: (a['nickname'] or a['account_name']) for a in accounts}

    # 视频 + 最新快照（每个视频的最新一条）
    videos = []
    cur = conn.execute('''
        SELECT v.platform, v.account_name, v.aweme_id, v.title,
               v.first_seen,
               s.collected_at, s.play_count, s.digg_count,
               s.comment_count, s.share_count, s.collect_count
        FROM videos v
        JOIN snapshots s ON s.video_id = v.id
        WHERE s.collected_at = (
            SELECT MAX(s2.collected_at) FROM snapshots s2 WHERE s2.video_id = s.video_id
        )
        ORDER BY s.play_count DESC
    ''')
    for r in cur:
        v = dict(r)
        v['nickname'] = nickname_map.get(v['account_name'], v['account_name'])
        videos.append(v)

    conn.close()
    return {'accounts': accounts, 'videos': videos}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/data':
            try:
                data = query_data()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        elif parsed.path == '/api/collect':
            # 触发采集
            import subprocess
            try:
                result = subprocess.run(
                    ['python3', str(COLLECTOR), '--platform', 'douyin'],
                    capture_output=True, text=False, timeout=300
                )
                out = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
                err = result.stderr.decode('gbk', errors='replace') if result.stderr else ''
                status = 'ok' if result.returncode == 0 else 'error'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': status, 'output': out[-1000:], 'error': err[-500:]
                }, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

        else:
            # 静态文件
            filepath = FRONTEND_DIR / parsed.path.lstrip('/')
            if not filepath.exists() or not filepath.is_file():
                filepath = FRONTEND_DIR / 'index.html'

            if filepath.suffix == '.html':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
            elif filepath.suffix == '.js':
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
            elif filepath.suffix == '.css':
                self.send_response(200)
                self.send_header('Content-Type', 'text/css')
            else:
                self.send_response(200)

            self.end_headers()
            with open(str(filepath), 'rb') as f:
                self.wfile.write(f.read())

    def log_message(self, format, *args):
        # 静默日志
        pass


if __name__ == '__main__':
    print(f"📡 Social Monitor API — http://localhost:{PORT}")
    print(f"   前端页面: http://localhost:{PORT}")
    print(f"   API接口:  http://localhost:{PORT}/api/data")
    print(f"   触发采集: http://localhost:{PORT}/api/collect")
    print()

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()
