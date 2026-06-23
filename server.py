#!/usr/bin/env python3
"""
Social Monitor — 轻量 API 服务
为前端提供数据接口，监听 localhost:5408
"""

import json
import os
import sqlite3
import subprocess
import sys
import uuid
import ipaddress
import socket
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import config
import db
from db import get_db, migrate as db_migrate
from utils import (
    json_response,
    read_body,
    spawn_script,
    validate_str,
    validate_int,
    validate_platform,
    csv_quote,
    is_safe_image_url,
    MAX_KEYWORD_LEN,
)

# API module registry — order matters: first match wins
from api import health, accounts, groups, data, collect, config as api_config, keywords, relogin
API_MODULES = [data, health, accounts, groups, collect, api_config, keywords, relogin]


MONITOR_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get('SM_DATA_DIR', str(MONITOR_DIR)))
DB_PATH = DATA_DIR / "monitor.db"
FRONTEND_DIR = MONITOR_DIR / "frontend"
COLLECTOR = MONITOR_DIR / "collector.py"


def spawn_script(*args):
    """Spawn a Python script using the correct interpreter.
    Under WSL, uses the configured Windows Python so Playwright works.
    """
    if config.is_wsl():
        # Convert Windows path to WSL-mountable path
        # C:\Users\... -> /mnt/c/Users/...
        win_path = config.windows_python_path()
        exe = win_path.replace('C:\\', '/mnt/c/').replace('\\', '/')
    else:
        exe = sys.executable
    return subprocess.Popen([exe, *args], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=str(MONITOR_DIR))


def is_safe_image_url(raw_url: str) -> bool:
    """检查图片代理 URL 是否安全（防 SSRF）"""
    try:
        u = urlparse(raw_url)
    except Exception:
        return False

    # 仅允许 http/https
    if u.scheme not in ('http', 'https'):
        return False
    if not u.hostname:
        return False

    # 阻止裸 IP 和内网地址
    hostname = u.hostname.strip('[]')
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # 是域名，通过 DNS 进一步检查
    else:
        if addr.is_loopback or addr.is_private or addr.is_link_local:
            return False

    # DNS 解析后再次检查（防 DNS rebinding 绕过 hostname 检查）
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in resolved:
            ip = sockaddr[0]
            try:
                a = ipaddress.ip_address(ip)
                if a.is_loopback or a.is_private or a.is_link_local:
                    return False
            except ValueError:
                continue
    except socket.gaierror:
        return False

    # 域名白名单（来自配置文件）
    for pat in config.image_proxy_allowed_patterns():
        if pat.match(hostname):
            return True
    return False


def csv_quote(val):
    """将值转为 CSV 安全格式：必要时加双引号包裹，内嵌引号转义"""
    s = str(val or '')
    if ',' in s or '"' in s or '\n' in s or '\r' in s:
        s = s.replace('"', '""')
        return f'"{s}"'
    return s


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def migrate_db():
    """Auto-migrate: add new tables if missing (non-destructive)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS keywords (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword     TEXT NOT NULL,
            platform    TEXT,           -- NULL = all platforms
            account_id  INTEGER,        -- NULL = all accounts
            color       TEXT DEFAULT 'blue',  -- tag color hint
            is_active   INTEGER DEFAULT 1,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS comments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id     INTEGER NOT NULL REFERENCES videos(id),
            platform     TEXT NOT NULL,
            comment_id   TEXT NOT NULL,
            author_name  TEXT,
            content      TEXT NOT NULL,
            digg_count   INTEGER DEFAULT 0,
            create_time  DATETIME,
            collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            matched_kw   TEXT DEFAULT '',   -- comma-separated matched keywords
            UNIQUE(platform, comment_id)
        );
        CREATE INDEX IF NOT EXISTS idx_comments_matched
            ON comments(matched_kw);
        CREATE INDEX IF NOT EXISTS idx_comments_video
            ON comments(video_id);
    """)
    conn.commit()
    # 添加 consecutive_failures 列（如果不存在）
    try:
        conn.execute('ALTER TABLE accounts ADD COLUMN consecutive_failures INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 列已存在
    conn.close()


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


MAX_BODY_LEN = 1024 * 100  # 100KB max POST body

def read_body(handler):
    length = int(handler.headers.get('Content-Length', 0))
    if length > MAX_BODY_LEN:
        return ''  # reject oversized body
    if length:
        return handler.rfile.read(length).decode('utf-8')
    return ''


# ── Input Validation ──────────────────────────────────
MAX_STR_LEN = 256
MAX_KEYWORD_LEN = 100
VALID_PLATFORMS = {'douyin', 'kuaishou', 'xiaohongshu', 'shipinhao'}

def validate_str(val, name='参数', max_len=MAX_STR_LEN, allow_empty=False):
    """Validate a string parameter: must be string type, within length."""
    if not isinstance(val, str):
        return f'{name} 类型无效，需要字符串'
    if not allow_empty and not val.strip():
        return f'{name} 不能为空'
    if len(val) > max_len:
        return f'{name} 超过最大长度 {max_len}'
    return None  # no error

def validate_int(val, name='参数', min_v=None, max_v=None):
    """Validate an integer parameter."""
    if val is None:
        return f'{name} 不能为空'
    if not isinstance(val, (int, float)):
        return f'{name} 类型无效，需要数字'
    if min_v is not None and val < min_v:
        return f'{name} 不能小于 {min_v}'
    if max_v is not None and val > max_v:
        return f'{name} 不能大于 {max_v}'
    return None

def validate_platform(val):
    """Validate platform name."""
    err = validate_str(val, '平台', 20)
    if err: return err
    if val not in VALID_PLATFORMS:
        return f'平台 "{val}" 无效，仅支持: {", ".join(sorted(VALID_PLATFORMS))}'
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        self.parsed_path = parsed  # for api modules that need parsed path

        # Delegate to API modules first
        self.path = self.path  # preserve for modules that read handler.path
        for mod in API_MODULES:
            if mod.handle(self, "GET", parsed.path):
                return

        if parsed.path == '/api/data':
            try:
                json_response(self, query_data())
            except Exception as e:
                json_response(self, {'error': str(e)}, 500)

        elif parsed.path == '/api/stats/history':
            try:
                from urllib.parse import parse_qs
                qs = parse_qs(parsed.query)
                platform = qs.get('platform', ['all'])[0]
                conn = get_db()
                if platform and platform != 'all':
                    rows = conn.execute('''
                        SELECT DATE(s.collected_at) as d,
                               COUNT(DISTINCT s.video_id) as videos,
                               COUNT(*) as snapshots,
                               SUM(s.play_count) as total_play
                        FROM snapshots s
                        JOIN videos v ON v.id = s.video_id
                        WHERE v.platform = ?
                        GROUP BY DATE(s.collected_at)
                        ORDER BY d
                    ''', (platform,)).fetchall()
                else:
                    rows = conn.execute('''
                        SELECT DATE(s.collected_at) as d,
                               COUNT(DISTINCT s.video_id) as videos,
                               COUNT(*) as snapshots,
                               SUM(s.play_count) as total_play
                        FROM snapshots s
                        GROUP BY DATE(s.collected_at)
                        ORDER BY d
                    ''').fetchall()
                conn.close()
                points = [{'date': r['d'], 'videos': r['videos'], 'snapshots': r['snapshots'], 'play': r['total_play']} for r in rows]
                json_response(self, {'points': points})
            except Exception as e:
                json_response(self, {'error': str(e)}, 500)

        elif parsed.path == '/api/accounts':
            conn = get_db()
            accounts = [
                dict(r) for r in conn.execute(
                    'SELECT id, platform, account_name, nickname, is_active, follower_count, total_digg_count, total_play_count, total_following_count, profile_bio, profile_douyin_id, profile_avatar_url, profile_like_count, cookie_status FROM accounts ORDER BY platform, id'
                )
            ]
            # Compute per-account health score: compare latest video play vs 7-day avg
            for a in accounts:
                aid = a['id']
                # Get latest snapshot play per video for this account in past 7 days
                seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
                rows = conn.execute('''
                    SELECT v.id, MAX(s.collected_at) as last_collected, s.play_count
                    FROM videos v
                    JOIN snapshots s ON s.video_id = v.id
                    WHERE v.account_id = ? AND s.collected_at >= ?
                    GROUP BY v.id
                    ORDER BY s.collected_at DESC
                ''', (aid, seven_days_ago)).fetchall()

                if len(rows) >= 2:
                    plays = [r['play_count'] for r in rows]
                    latest_play = plays[0]
                    avg_play = sum(plays) / len(plays)

                    if latest_play > avg_play * 1.2:
                        a['health_level'] = 'green'
                        a['health_score'] = round(90 - (latest_play - avg_play * 1.2) / avg_play * 10, 1)
                        a['health_score'] = max(70, min(100, a['health_score']))
                        a['health_detail'] = f'最新播放 {latest_play:,} › 7日均值 {int(avg_play):,} (↑{int((latest_play/avg_play-1)*100)}%)'
                    elif latest_play < avg_play * 0.8:
                        a['health_level'] = 'red'
                        a['health_score'] = round(30 - (avg_play * 0.8 - latest_play) / avg_play * 30, 1)
                        a['health_score'] = max(0, min(50, a['health_score']))
                        a['health_detail'] = f'最新播放 {latest_play:,} ‹ 7日均值 {int(avg_play):,} (↓{int((1-latest_play/avg_play)*100)}%)'
                    else:
                        a['health_level'] = 'yellow'
                        a['health_score'] = round(60 + (latest_play - avg_play) / avg_play * 20, 1)
                        a['health_score'] = max(50, min(80, a['health_score']))
                        a['health_detail'] = f'最新播放 {latest_play:,} ≈ 7日均值 {int(avg_play):,}'
                elif len(rows) == 1:
                    a['health_level'] = 'yellow'
                    a['health_score'] = 50
                    a['health_detail'] = '仅1条数据，无法对比'
                else:
                    a['health_level'] = 'gray'
                    a['health_score'] = 0
                    a['health_detail'] = '7天内无数据'

            conn.close()
            json_response(self, {'accounts': accounts})

        elif parsed.path == '/api/keywords':
            conn = get_db()
            rows = conn.execute(
                'SELECT k.*, a.nickname as account_nick, a.platform as acct_platform '
                'FROM keywords k LEFT JOIN accounts a ON k.account_id = a.id '
                'ORDER BY k.created_at DESC'
            ).fetchall()
            conn.close()
            json_response(self, {'keywords': [dict(r) for r in rows]})

        elif parsed.path == '/api/comments/matched':
            conn = get_db()
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query)
            kw = qs.get('keyword', [''])[0]
            limit_val = int(qs.get('limit', ['50'])[0])
            if kw:
                rows = conn.execute('''
                    SELECT c.*, v.title as video_title, v.aweme_id,
                           a.nickname as account_nick, a.account_name
                    FROM comments c
                    JOIN videos v ON v.id = c.video_id
                    JOIN accounts a ON a.id = v.account_id
                    WHERE c.matched_kw LIKE ?
                    ORDER BY c.digg_count DESC, c.collected_at DESC
                    LIMIT ?
                ''', (f'%{kw}%', limit_val)).fetchall()
            else:
                rows = conn.execute('''
                    SELECT c.*, v.title as video_title, v.aweme_id,
                           a.nickname as account_nick, a.account_name
                    FROM comments c
                    JOIN videos v ON v.id = c.video_id
                    JOIN accounts a ON a.id = v.account_id
                    WHERE c.matched_kw != ''
                    ORDER BY c.digg_count DESC, c.collected_at DESC
                    LIMIT ?
                ''', (limit_val,)).fetchall()
            conn.close()
            json_response(self, {'comments': [dict(r) for r in rows]})

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
            # 账号健康度红绿灯计数
            active_accounts = conn.execute(
                "SELECT id FROM accounts WHERE is_active=1"
            ).fetchall()
            seven_days_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            hl_counts = {'green': 0, 'yellow': 0, 'red': 0, 'gray': 0}
            for acc in active_accounts:
                aid = acc['id']
                video_rows = conn.execute("""
                    SELECT v.id, MAX(s.collected_at) as last_collected, s.play_count
                    FROM videos v
                    JOIN snapshots s ON s.video_id = v.id
                    WHERE v.account_id = ? AND s.collected_at >= ?
                    GROUP BY v.id
                    ORDER BY s.collected_at DESC
                """, (aid, seven_days_ago)).fetchall()
                if len(video_rows) >= 2:
                    plays = [r['play_count'] for r in video_rows]
                    latest_play = plays[0]
                    avg_play = sum(plays) / len(plays)
                    if latest_play > avg_play * 1.2:
                        hl_counts['green'] += 1
                    elif latest_play < avg_play * 0.8:
                        hl_counts['red'] += 1
                    else:
                        hl_counts['yellow'] += 1
                elif len(video_rows) == 1:
                    hl_counts['yellow'] += 1
                else:
                    hl_counts['gray'] += 1
            conn.close()
            health = {}
            for r in rows:
                health[r['platform']] = {'total': r['total'], 'ok': r['ok'], 'failed': r['total'] - r['ok']}
            for r in stale:
                if r['platform'] in health:
                    health[r['platform']]['last_snap'] = r['last_snap']
                    health[r['platform']]['days_stale'] = r['days_stale']
            health['accounts_health'] = hl_counts
            json_response(self, health)

        elif parsed.path == '/api/compare':
            conn = get_db()
            # 按 group_id 分组，未分组的按 account_name 单列
            rows = conn.execute("""
                SELECT a.id, a.account_name, a.platform, a.nickname, a.cookie_status,
                       a.follower_count, a.total_digg_count, a.total_play_count,
                       a.group_id, g.group_name
                FROM accounts a
                LEFT JOIN groups g ON g.id = a.group_id
                WHERE a.is_active=1
                ORDER BY COALESCE(g.group_name, a.account_name), a.platform
            """).fetchall()
            # 7日播放增长：每个账号过去7天 vs 上7天的播放量变化
            seven_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            fourteen_ago = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
            growth_rows = conn.execute("""
                WITH per_video AS (
                    SELECT v.account_id,
                           (SELECT s.play_count FROM snapshots s
                            WHERE s.video_id = v.id AND s.collected_at >= ?
                            ORDER BY s.collected_at DESC LIMIT 1) as recent_play,
                           (SELECT s.play_count FROM snapshots s
                            WHERE s.video_id = v.id AND s.collected_at >= ? AND s.collected_at < ?
                            ORDER BY s.collected_at DESC LIMIT 1) as prior_play
                    FROM videos v
                )
                SELECT account_id,
                       COALESCE(SUM(recent_play), 0) as recent_total,
                       COALESCE(SUM(prior_play), 0) as prior_total
                FROM per_video
                GROUP BY account_id
            """, (seven_ago, fourteen_ago, seven_ago)).fetchall()
            growth_map = {}
            for gr in growth_rows:
                growth_map[gr['account_id']] = gr['recent_total'] - gr['prior_total']
            conn.close()
            groups = {}
            for r in rows:
                if r['group_id']:
                    key = 'g:' + str(r['group_id'])
                    label = r['group_name'] or f'分组{r["group_id"]}'
                else:
                    key = 'u:' + r['account_name']
                    label = r['nickname'] or r['account_name']
                if key not in groups:
                    groups[key] = {'id': key, 'label': label, 'platforms': {}}
                growth = growth_map.get(r['id'], 0)
                groups[key]['platforms'][r['platform']] = {
                    'nickname': r['nickname'], 'cookie_status': r['cookie_status'],
                    'followers': r['follower_count'], 'diggs': r['total_digg_count'],
                    'plays': r['total_play_count'],
                    'account_name': r['account_name'],
                    'growth_plays': growth,
                }
            json_response(self, {'groups': list(groups.values())})

        elif parsed.path == '/api/groups':
            conn = get_db()
            gs = conn.execute('SELECT * FROM groups ORDER BY group_name').fetchall()
            result = []
            for g in gs:
                members = conn.execute(
                    'SELECT id, platform, account_name, nickname FROM accounts WHERE group_id=? ORDER BY platform',
                    (g['id'],)
                ).fetchall()
                result.append({
                    'id': g['id'],
                    'name': g['group_name'],
                    'members': [dict(m) for m in members],
                })
            # 未分组账号
            ungrouped = conn.execute(
                'SELECT id, platform, account_name, nickname FROM accounts WHERE is_active=1 AND group_id IS NULL ORDER BY platform, account_name'
            ).fetchall()
            conn.close()
            json_response(self, {'groups': result, 'ungrouped': [dict(u) for u in ungrouped]})

        elif parsed.path == '/api/collect/stats':
            # 触发采集账号统计数据
            try:
                spawn_script(str(COLLECTOR), '--stats-only')
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

        elif parsed.path == '/api/collect/summary':
            summary_path = MONITOR_DIR / 'collect_summary.json'
            if summary_path.exists():
                try:
                    with open(summary_path) as f:
                        summary = json.load(f)
                    json_response(self, summary)
                except Exception as e:
                    json_response(self, {'error': str(e)}, 500)
            else:
                json_response(self, {'status': 'idle', 'message': '暂无采集摘要'})

        elif parsed.path == '/api/alerts':
            # 从采集摘要中提取预警 + DB实时查询连续失败
            summary_path = MONITOR_DIR / 'collect_summary.json'
            alerts = []
            try:
                if summary_path.exists():
                    with open(summary_path) as f:
                        summary = json.load(f)
                    alerts = summary.get('alerts', [])
            except Exception:
                pass
            # 实时补充：查询连续失败 >= 3 但可能不在摘要中的
            conn = get_db()
            failure_rows = conn.execute(
                'SELECT platform, account_name, nickname, consecutive_failures '
                'FROM accounts WHERE is_active=1 AND consecutive_failures >= 3'
            ).fetchall()
            conn.close()
            existing_failures = {a['account'] for a in alerts if a.get('type') == 'consecutive_failure'}
            for fr in failure_rows:
                if fr['account_name'] not in existing_failures:
                    alerts.append({
                        'platform': fr['platform'],
                        'account': fr['account_name'],
                        'nickname': fr['nickname'] or fr['account_name'],
                        'consecutive_failures': fr['consecutive_failures'],
                        'type': 'consecutive_failure',
                    })
            json_response(self, {'alerts': alerts, 'count': len(alerts)})

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
                csv += f'{r["platform"]},{csv_quote(r["account_name"])},{csv_quote(r["nickname"])},{r["cookie_status"]},{r["follower_count"] or 0},{r["total_digg_count"] or 0},{r["total_play_count"] or 0},{r["account_stats_updated"] or ""}\n'
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
                csv += f'{r["platform"]},{csv_quote(r["account_name"])},{csv_quote(r["title"])},{r["aweme_id"]},{r["first_seen"] or ""},{r["play_count"]},{r["digg_count"]},{r["comment_count"]},{r["share_count"]},{r["collect_count"]},{r["collected_at"]}\n'
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
            if not is_safe_image_url(url):
                self.send_error(403, 'Blocked: domain not allowed')
                return
            try:
                req = urllib.request.Request(url, headers={
                    'Referer': config.image_proxy_referer(),
                    'User-Agent': config.image_proxy_user_agent(),
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
                self.send_header('Cache-Control', f'public, max-age={config.image_proxy_cache_max_age()}')
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

        elif parsed.path == '/api/config':
            json_response(self, config.get())

        elif parsed.path == '/api/qr-login/status':
            """GET /api/qr-login/status?token=xxx — poll QR login status"""
            qs = urlparse(self.path).query
            params = dict(p.split('=') for p in qs.split('&') if '=' in p) if qs else {}
            token = params.get('token', '')
            if not token:
                json_response(self, {'status': 'error', 'error': 'missing token'}, 400)
                return
            status_path = MONITOR_DIR / 'tmp' / f'qr_{token}.json'
            if not status_path.exists():
                # Status file not yet written — QR is still being generated
                json_response(self, {'status': 'starting', 'message': '正在生成二维码...'})
                return
            try:
                with open(status_path) as f:
                    st = json.load(f)
                # On success, update DB cookie_status
                if st.get('status') == 'success':
                    conn = get_db()
                    conn.execute(
                        "UPDATE accounts SET cookie_status='ok', is_active=1 "
                        "WHERE platform=? AND account_name=?",
                        (st.get('platform', ''), st.get('account_name', ''))
                    )
                    conn.commit()
                    conn.close()
                    # Clean up status file
                    status_path.unlink(missing_ok=True)
                    # Clean up QR image
                    qr_img = MONITOR_DIR / 'tmp' / f'qr_{token}.png'
                    qr_img.unlink(missing_ok=True)
                json_response(self, st)
            except Exception as e:
                json_response(self, {'status': 'error', 'error': str(e)}, 500)

        elif parsed.path == '/api/qr-image':
            """GET /api/qr-image?token=xxx — serve QR code image"""
            qs = urlparse(self.path).query
            params = dict(p.split('=') for p in qs.split('&') if '=' in p) if qs else {}
            token = params.get('token', '')
            if not token:
                self.send_response(400)
                self.end_headers()
                return
            img_path = MONITOR_DIR / 'tmp' / f'qr_{token}.png'
            if not img_path.exists():
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(str(img_path), 'rb') as f:
                self.wfile.write(f.read())

        elif parsed.path == '/api/relogin/status':
            """查询扫码登录状态"""
            status_path = MONITOR_DIR / 'relogin_status.json'
            if status_path.exists():
                try:
                    with open(status_path) as f:
                        st = json.load(f)
                    account_name = st.get('account_name', '')
                    platform = st.get('platform', '')
                    done_file = MONITOR_DIR / 'social-auto-upload' / 'cookies' / f'.{platform}_{account_name}_done'
                    if done_file.exists():
                        done_file.unlink(missing_ok=True)
                        st['status'] = 'success'
                        st['message'] = '扫码登录成功'
                        with open(status_path, 'w') as f:
                            json.dump(st, f, ensure_ascii=False)
                        # 更新数据库中的 cookie 状态
                        conn = get_db()
                        conn.execute(
                            "UPDATE accounts SET cookie_status='ok', is_active=1 "
                            "WHERE platform=? AND account_name=?",
                            (platform, account_name)
                        )
                        conn.commit()
                        conn.close()
                    json_response(self, st)
                except:
                    json_response(self, {'status': 'idle', 'message': '无扫码登录任务'})
            else:
                json_response(self, {'status': 'idle', 'message': '无扫码登录任务'})

        else:
            filepath = FRONTEND_DIR / parsed.path.lstrip('/')
            if not filepath.exists() or not filepath.is_file():
                filepath = FRONTEND_DIR / 'index.html'

            ct_map = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml'}
            ct = ct_map.get(filepath.suffix, 'application/octet-stream')

            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(str(filepath), 'rb') as f:
                self.wfile.write(f.read())

    def do_POST(self):
        parsed = urlparse(self.path)
        self.parsed_path = parsed

        # Delegate to API modules first
        for mod in API_MODULES:
            if mod.handle(self, "POST", parsed.path):
                return

        if parsed.path == '/api/groups':
            body = json.loads(read_body(self))
            action = body.get('action', '')
            conn = get_db()
            try:
                if action == 'create':
                    name = body.get('name', '').strip()
                    err = validate_str(name, '分组名', 50)
                    if err:
                        json_response(self, {'error': err}, 400)
                        return
                    conn.execute('INSERT OR IGNORE INTO groups (group_name) VALUES (?)', (name,))
                    conn.commit()
                    gid = conn.execute('SELECT id FROM groups WHERE group_name=?', (name,)).fetchone()[0]
                    # 如果传了 account_ids，直接加入
                    for aid in (body.get('account_ids') or []):
                        if not isinstance(aid, int):
                            continue
                        conn.execute('UPDATE accounts SET group_id=? WHERE id=?', (gid, aid))
                    conn.commit()
                    json_response(self, {'status': 'ok', 'id': gid})

                elif action == 'delete':
                    gid = body.get('id')
                    if not isinstance(gid, int):
                        json_response(self, {'error': '分组ID无效'}, 400)
                        return
                    conn.execute('UPDATE accounts SET group_id=NULL WHERE group_id=?', (gid,))
                    conn.execute('DELETE FROM groups WHERE id=?', (gid,))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                elif action == 'add_member':
                    gid = body.get('group_id')
                    aid = body.get('account_id')
                    if not isinstance(gid, int) or not isinstance(aid, int):
                        json_response(self, {'error': '参数无效'}, 400)
                        return
                    conn.execute('UPDATE accounts SET group_id=? WHERE id=?', (gid, aid))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                elif action == 'remove_member':
                    aid = body.get('account_id')
                    if not isinstance(aid, int):
                        json_response(self, {'error': '账号ID无效'}, 400)
                        return
                    conn.execute('UPDATE accounts SET group_id=NULL WHERE id=?', (aid,))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                elif action == 'rename':
                    gid = body.get('id')
                    name = body.get('name', '').strip()
                    if not isinstance(gid, int):
                        json_response(self, {'error': '分组ID无效'}, 400)
                        return
                    err = validate_str(name, '分组名', 50)
                    if err:
                        json_response(self, {'error': err}, 400)
                        return
                    conn.execute('UPDATE groups SET group_name=? WHERE id=?', (name, gid))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                else:
                    json_response(self, {'error': 'unknown action'}, 400)
            except Exception as e:
                conn.rollback()
                json_response(self, {'error': str(e)}, 500)
            finally:
                conn.close()
            return

        if parsed.path == '/api/login':
            body = json.loads(read_body(self))
            platform = body.get('platform', '')
            account_name = body.get('account_name', '')

            err = validate_platform(platform)
            if err:
                json_response(self, {'error': err}, 400)
                return
            err = validate_str(account_name, '账号名', 100)
            if err:
                json_response(self, {'error': err}, 400)
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

            # Generate token and spawn headless QR login (embedded, no popup Chrome window)
            token = str(uuid.uuid4())[:8]
            spawn_script(str(MONITOR_DIR / 'qr_login.py'), token, platform, account_name)

            json_response(self, {
                'status': 'ok',
                'token': token,
                'message': f'二维码已生成，请用手机扫码登录 {platform}',
            })

        elif parsed.path == '/api/keywords':
            body = json.loads(read_body(self))
            action = body.get('action', '')
            conn = get_db()
            try:
                if action == 'add':
                    kw = body.get('keyword', '').strip()
                    err = validate_str(kw, '关键词', MAX_KEYWORD_LEN)
                    if err:
                        json_response(self, {'error': err}, 400)
                        return
                    platform = body.get('platform') or None
                    account_id = body.get('account_id') or None
                    conn.execute(
                        'INSERT INTO keywords (keyword, platform, account_id) VALUES (?, ?, ?)',
                        (kw, platform, account_id)
                    )
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                elif action == 'delete':
                    kid = body.get('id')
                    if not isinstance(kid, int):
                        json_response(self, {'error': '关键词ID无效'}, 400)
                        return
                    conn.execute('DELETE FROM keywords WHERE id=?', (kid,))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                elif action == 'toggle':
                    kid = body.get('id')
                    if not isinstance(kid, int):
                        json_response(self, {'error': '关键词ID无效'}, 400)
                        return
                    is_active = body.get('is_active', 0)
                    if not isinstance(is_active, int) or is_active not in (0, 1):
                        json_response(self, {'error': '状态值无效，需要 0 或 1'}, 400)
                        return
                    conn.execute('UPDATE keywords SET is_active=? WHERE id=?', (is_active, kid))
                    conn.commit()
                    json_response(self, {'status': 'ok'})

                else:
                    json_response(self, {'error': 'unknown action'}, 400)
            except Exception as e:
                conn.rollback()
                json_response(self, {'error': str(e)}, 500)
            finally:
                conn.close()
            return

        elif parsed.path == '/api/account/toggle':
            body = json.loads(read_body(self))
            account_id = body.get('id')
            is_active = body.get('is_active', 1)
            if not isinstance(account_id, int):
                json_response(self, {'error': '账号ID无效'}, 400)
                return
            if not isinstance(is_active, int) or is_active not in (0, 1):
                json_response(self, {'error': '状态值无效，需要 0 或 1'}, 400)
                return
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
                spawn_script(str(COLLECTOR))
                json_response(self, {'status': 'ok'})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

        elif parsed.path.startswith('/api/relogin'):
            """POST /api/relogin/{platform}/{account} — 后台启动扫码"""
            parts = parsed.path.split('/')
            if len(parts) >= 5:
                platform = parts[3]
                account_name = parts[4]
                err = validate_platform(platform)
                if err:
                    json_response(self, {'status': 'error', 'message': err}, 400)
                    return
                err = validate_str(account_name, '账号名', 100)
                if err:
                    json_response(self, {'status': 'error', 'message': err}, 400)
                    return
                try:
                    log_path = MONITOR_DIR / 'relogin_status.json'
                    with open(log_path, 'w') as f:
                        json.dump({'status': 'running', 'platform': platform, 'account_name': account_name,
                                   'message': f'正在打开浏览器扫码登录 {platform}/{account_name}...'}, f)

                    spawn_script(str(MONITOR_DIR / 'win_relogin.py'), platform, account_name)
                    json_response(self, {'status': 'ok', 'message': '扫码登录已启动，请查看浏览器窗口'})
                except Exception as e:
                    json_response(self, {'status': 'error', 'message': str(e)}, 500)
            else:
                json_response(self, {'status': 'error', 'message': '参数不足: /api/relogin/{platform}/{account}'}, 400)

        elif parsed.path == '/api/config':
            body = json.loads(read_body(self))
            try:
                # Validate critical numeric fields
                port = body.get('server', {}).get('port')
                if port is not None:
                    err = validate_int(port, '端口', 1024, 65535)
                    if err:
                        json_response(self, {'status': 'error', 'message': err}, 400)
                        return
                timeout = body.get('collect', {}).get('timeout_seconds')
                if timeout is not None:
                    err = validate_int(timeout, '采集超时', 10, 600)
                    if err:
                        json_response(self, {'status': 'error', 'message': err}, 400)
                        return
                config.save(body)
                json_response(self, {'status': 'ok', 'config': config.get()})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

        elif parsed.path == '/api/alerts/dismiss':
            body = json.loads(read_body(self))
            alert_key = body.get('key', '')  # e.g. "douyin:benxian1:cookie_expiring"
            if not alert_key:
                json_response(self, {'status': 'error', 'message': '缺少 key'}, 400)
                return
            dismiss_path = MONITOR_DIR / 'alert_dismissals.json'
            try:
                if dismiss_path.exists():
                    with open(dismiss_path) as f:
                        dismissed = json.load(f)
                else:
                    dismissed = []
                if alert_key not in dismissed:
                    dismissed.append(alert_key)
                with open(dismiss_path, 'w') as f:
                    json.dump(dismissed, f)
                json_response(self, {'status': 'ok'})
            except Exception as e:
                json_response(self, {'status': 'error', 'message': str(e)}, 500)

        else:
            # Serve static files from frontend/ directory
            # Map URL path to file; strip query string, default to index.html for /
            file_path = parsed.path.lstrip('/')
            if file_path == '':
                file_path = 'index.html'
            full_path = FRONTEND_DIR / file_path
            # Resolve to prevent directory traversal
            try:
                full_path = full_path.resolve()
                if not str(full_path).startswith(str(FRONTEND_DIR.resolve())):
                    json_response(self, {'error': 'forbidden'}, 403)
                    return
            except Exception:
                json_response(self, {'error': 'not found'}, 404)
                return

            if full_path.is_file():
                # MIME type lookup
                ext = full_path.suffix.lower()
                mime_map = {
                    '.html': 'text/html; charset=utf-8',
                    '.htm': 'text/html; charset=utf-8',
                    '.css': 'text/css; charset=utf-8',
                    '.js': 'application/javascript; charset=utf-8',
                    '.json': 'application/json; charset=utf-8',
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.svg': 'image/svg+xml',
                    '.ico': 'image/x-icon',
                    '.woff': 'font/woff',
                    '.woff2': 'font/woff2',
                    '.txt': 'text/plain; charset=utf-8',
                }
                content_type = mime_map.get(ext, 'application/octet-stream')

                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                # Cache static assets aggressively (1 hour), HTML lightly (no-cache)
                if ext in ('.html', '.htm'):
                    self.send_header('Cache-Control', 'no-cache')
                else:
                    self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                with open(full_path, 'rb') as f:
                    self.wfile.write(f.read())
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
    # Sync db module's DB_PATH with server's (might differ under SM_DATA_DIR override)
    db.DB_PATH = DATA_DIR / "monitor.db"
    db.MONITOR_DIR = MONITOR_DIR
    migrate_db()
    port = config.server_port()
    print(f"📡 Social Monitor API — http://localhost:{port}")
    print(f"   前端页面: http://localhost:{port}")
    print(f"   API接口:  http://localhost:{port}/api/data")
    print(f"   新增账号: POST http://localhost:{port}/api/login")
    print()

    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()
