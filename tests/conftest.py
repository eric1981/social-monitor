"""
pytest conftest — 测试数据库 + 服务器
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parent.parent

import sys
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


_db_path = None


def _get_test_db():
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(db_path):
    """Apply all migrations in order."""
    conn = sqlite3.connect(str(db_path))
    migrations_dir = PROJECT_DIR / 'migrations'
    migration_files = sorted(
        f for f in migrations_dir.iterdir() if f.suffix == '.sql'
    )
    for mf in migration_files:
        conn.executescript(mf.read_text())
    conn.commit()
    conn.close()


@pytest.fixture(scope="session")
def test_db():
    """Session-scoped: initialize schema, return DB path."""
    global _db_path

    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_sm_')
    os.close(fd)
    _db_path = path
    _init_schema(path)

    yield path

    os.unlink(path)
    _db_path = None


@pytest.fixture
def db():
    conn = _get_test_db()
    yield conn
    conn.close()


@pytest.fixture
def clean_db(db):
    tables = ['snapshots', 'comments', 'keywords', 'videos', 'accounts', 'groups']
    for t in tables:
        db.execute(f'DELETE FROM {t}')
    db.commit()
    yield db


# ── Test Server ────────────────────────────────────────

@pytest.fixture(scope="session")
def server_url(test_db):
    import server as server_module

    import db as db_module
    db_module.DB_PATH = Path(test_db)

    server_module.DB_PATH = Path(test_db)
    original_get_db = server_module.get_db
    server_module.get_db = _get_test_db
    # Also override db module's get_db so api modules use test DB
    original_db_get_db = db_module.get_db
    db_module.get_db = _get_test_db
    original_spawn = server_module.spawn_script
    server_module.spawn_script = lambda *a, **kw: None

    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()

    srv = ThreadingHTTPServer(('127.0.0.1', port), server_module.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)

    yield f"http://127.0.0.1:{port}"

    srv.shutdown()
    server_module.DB_PATH = Path(PROJECT_DIR / 'monitor.db')
    server_module.get_db = original_get_db
    db_module.get_db = original_db_get_db
    server_module.spawn_script = original_spawn


@pytest.fixture
def api_get(server_url):
    def _get(path):
        url = server_url + path
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode('utf-8')
                ct = resp.headers.get('Content-Type', '')
                if 'json' in ct or not ct:
                    try:
                        return resp.status, json.loads(body)
                    except json.JSONDecodeError:
                        return resp.status, body
                return resp.status, body
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode('utf-8'))
            except Exception:
                err_body = {'error': str(e)}
            return e.code, err_body
    return _get


@pytest.fixture
def api_post(server_url):
    def _post(path, data):
        url = server_url + path
        body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode('utf-8'))
            except Exception:
                err_body = {'error': str(e)}
            return e.code, err_body
    return _post


# ── Helpers ─────────────────────────────────────────────

def seed_account(db, platform='douyin', account_name='testuser',
                 nickname='TestUser', is_active=1, cookie_status='ok'):
    db.execute("""
        INSERT OR REPLACE INTO accounts
            (platform, account_name, nickname, is_active, cookie_status)
        VALUES (?, ?, ?, ?, ?)
    """, (platform, account_name, nickname, is_active, cookie_status))
    db.commit()
    return dict(db.execute(
        'SELECT * FROM accounts WHERE platform=? AND account_name=?',
        (platform, account_name)).fetchone())


def seed_video(db, platform='douyin', account_name='testuser',
               account_id=None, aweme_id='v001', title='Test Video',
               play_count=1000, digg_count=50,
               collected_at='2026-06-22 10:00:00'):
    if account_id is None:
        acc = db.execute(
            'SELECT id FROM accounts WHERE platform=? AND account_name=?',
            (platform, account_name)).fetchone()
        if not acc:
            acc = seed_account(db, platform, account_name)
        account_id = acc['id']

    db.execute("""
        INSERT OR REPLACE INTO videos
            (platform, account_name, account_id, aweme_id, title)
        VALUES (?, ?, ?, ?, ?)
    """, (platform, account_name, account_id, aweme_id, title))
    db.commit()
    vid = db.execute(
        'SELECT id FROM videos WHERE platform=? AND aweme_id=?',
        (platform, aweme_id)).fetchone()['id']

    db.execute("""
        INSERT INTO snapshots
            (video_id, play_count, digg_count, collected_at)
        VALUES (?, ?, ?, ?)
    """, (vid, play_count, digg_count, collected_at))
    db.commit()
    return vid


def seed_keyword(db, keyword='testkw', platform=None, account_id=None,
                 is_active=1):
    db.execute("""
        INSERT INTO keywords (keyword, platform, account_id, is_active)
        VALUES (?, ?, ?, ?)
    """, (keyword, platform, account_id, is_active))
    db.commit()
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def seed_group(db, group_name='TestGroup'):
    db.execute("INSERT OR IGNORE INTO groups (group_name) VALUES (?)",
               (group_name,))
    db.commit()
    return db.execute(
        'SELECT id FROM groups WHERE group_name=?',
        (group_name,)).fetchone()['id']


def seed_comment(db, video_id, platform='douyin', comment_id='c001',
                 content='great video', author_name='fan1', matched_kw=''):
    db.execute("""
        INSERT OR REPLACE INTO comments
            (video_id, platform, comment_id, author_name, content, matched_kw)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (video_id, platform, comment_id, author_name, content, matched_kw))
    db.commit()
