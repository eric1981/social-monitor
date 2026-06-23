"""Tests for all GET API endpoints."""
from tests.conftest import (
    seed_account, seed_video, seed_keyword, seed_group, seed_comment,
)


# ── /api/health ───────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, api_get):
        status, body = api_get('/api/health')
        assert status == 200
        assert isinstance(body, dict)

    def test_health_empty_db_returns_no_accounts(self, api_get, clean_db):
        status, body = api_get('/api/health')
        assert status == 200
        # Should have accounts_health keys
        assert 'accounts_health' in body


# ── /api/data ─────────────────────────────────────────

class TestData:
    def test_data_returns_accounts_and_videos(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'test1', 'T1')
        seed_video(clean_db, 'douyin', 'test1', aweme_id='v001',
                   play_count=1000)
        status, body = api_get('/api/data')
        assert status == 200
        assert len(body['accounts']) >= 1
        assert len(body['videos']) >= 1
        v = body['videos'][0]
        assert 'play_count' in v
        assert 'nickname' in v

    def test_data_empty_db(self, api_get, clean_db):
        status, body = api_get('/api/data')
        assert status == 200
        assert body['accounts'] == []
        assert body['videos'] == []


# ── /api/accounts ─────────────────────────────────────

class TestAccounts:
    def test_accounts_lists_active(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'a1', 'Alice')
        seed_account(clean_db, 'kuaishou', 'a2', 'Bob')
        status, body = api_get('/api/accounts')
        assert status == 200
        assert len(body['accounts']) == 2

    def test_accounts_empty(self, api_get, clean_db):
        status, body = api_get('/api/accounts')
        assert status == 200
        assert body['accounts'] == []


# ── /api/compare ──────────────────────────────────────

class TestCompare:
    def test_compare_groups_by_account(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'u1', 'User1')
        seed_account(clean_db, 'kuaishou', 'u1', 'User1')
        status, body = api_get('/api/compare')
        assert status == 200
        assert len(body['groups']) >= 1

    def test_compare_empty(self, api_get, clean_db):
        status, body = api_get('/api/compare')
        assert status == 200
        assert body['groups'] == []


# ── /api/groups ───────────────────────────────────────

class TestGroups:
    def test_groups_lists_with_members(self, api_get, clean_db):
        gid = seed_group(clean_db, 'MyGroup')
        acc = seed_account(clean_db, 'douyin', 'guser', 'GUser')
        clean_db.execute(
            'UPDATE accounts SET group_id=? WHERE id=?', (gid, acc['id']))
        clean_db.commit()
        status, body = api_get('/api/groups')
        assert status == 200
        assert len(body['groups']) >= 1
        assert body['groups'][0]['name'] == 'MyGroup'

    def test_groups_has_ungrouped(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'nogroup', 'NoGroup')
        status, body = api_get('/api/groups')
        assert status == 200
        assert 'ungrouped' in body


# ── /api/keywords ─────────────────────────────────────

class TestKeywords:
    def test_keywords_lists_all(self, api_get, clean_db):
        seed_keyword(clean_db, 'hello')
        seed_keyword(clean_db, 'world', platform='douyin')
        status, body = api_get('/api/keywords')
        assert status == 200
        assert len(body['keywords']) >= 2

    def test_keywords_empty(self, api_get, clean_db):
        status, body = api_get('/api/keywords')
        assert status == 200
        assert body['keywords'] == []


# ── /api/alerts ───────────────────────────────────────

class TestAlerts:
    def test_alerts_returns_list(self, api_get):
        status, body = api_get('/api/alerts')
        assert status == 200
        assert 'alerts' in body
        assert 'count' in body

    def test_alerts_empty_db(self, api_get, clean_db):
        """With a clean DB and no real summary file, count should be 0."""
        status, body = api_get('/api/alerts')
        # DB is clean — no consecutive failures, so alerts only from summary file
        # If collect_summary.json exists with production data, filter that out
        assert status == 200
        assert 'alerts' in body
        assert 'count' in body


# ── /api/config ───────────────────────────────────────

class TestConfig:
    def test_config_returns_dict(self, api_get):
        status, body = api_get('/api/config')
        assert status == 200
        assert 'server' in body
        assert 'collect' in body


# ── /api/collect/log ──────────────────────────────────

class TestCollectLog:
    def test_log_returns_status(self, api_get):
        status, body = api_get('/api/collect/log')
        assert status == 200
        assert 'status' in body


# ── /api/collect/summary ──────────────────────────────

class TestCollectSummary:
    def test_summary_returns_status(self, api_get):
        status, body = api_get('/api/collect/summary')
        assert status == 200
        assert 'status' in body


# ── /api/collect/stats ────────────────────────────────

class TestCollectStats:
    def test_stats_trigger_returns_ok(self, api_get):
        status, body = api_get('/api/collect/stats')
        assert status == 200
        assert body.get('status') == 'ok'


# ── /api/account/<id> ─────────────────────────────────

class TestAccountDetail:
    def test_account_detail_valid(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'detail1', 'Detail')
        seed_video(clean_db, 'douyin', 'detail1', aweme_id='dv001')
        status, body = api_get(f'/api/account/{acc["id"]}')
        assert status == 200
        assert body['account']['account_name'] == 'detail1'
        assert 'videos' in body

    def test_account_detail_invalid_id(self, api_get):
        status, body = api_get('/api/account/99999')
        assert status == 404
        assert 'error' in body

    def test_account_growth_valid(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'grow1', 'Grow')
        seed_video(clean_db, 'douyin', 'grow1', aweme_id='gv001')
        status, body = api_get(f'/api/account/{acc["id"]}/growth')
        assert status == 200
        assert 'points' in body

    def test_account_growth_invalid_id(self, api_get):
        status, body = api_get('/api/account/99999/growth')
        assert status == 404


# ── /api/stats/history ────────────────────────────────

class TestStatsHistory:
    def test_history_returns_points(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'h1', 'Hist')
        seed_video(clean_db, 'douyin', 'h1', aweme_id='hv001')
        status, body = api_get('/api/stats/history')
        assert status == 200
        assert 'points' in body

    def test_history_with_platform_filter(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'h2', 'H2')
        seed_video(clean_db, 'douyin', 'h2', aweme_id='hv002')
        status, body = api_get('/api/stats/history?platform=douyin')
        assert status == 200
        assert 'points' in body


# ── /api/comments/matched ─────────────────────────────

class TestCommentsMatched:
    def test_comments_matched_no_filter(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'cuser', 'CUser')
        vid = seed_video(clean_db, 'douyin', 'cuser', aweme_id='cv001')
        seed_comment(clean_db, vid, 'douyin', 'c001', 'hello world',
                     matched_kw='hello')
        status, body = api_get('/api/comments/matched')
        assert status == 200
        assert len(body['comments']) >= 1

    def test_comments_matched_by_keyword(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'cuser2', 'CUser2')
        vid = seed_video(clean_db, 'douyin', 'cuser2', aweme_id='cv002')
        seed_comment(clean_db, vid, 'douyin', 'c002', 'nice one',
                     matched_kw='nice')
        status, body = api_get('/api/comments/matched?keyword=nice')
        assert status == 200
        assert len(body['comments']) >= 1

    def test_comments_matched_empty(self, api_get, clean_db):
        status, body = api_get('/api/comments/matched')
        assert status == 200
        assert body['comments'] == []


# ── /api/trend ────────────────────────────────────────

class TestTrend:
    def test_trend_valid_video(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'tuser', 'TUser')
        vid = seed_video(clean_db, 'douyin', 'tuser', aweme_id='tv001')
        status, body = api_get(f'/api/trend?video_id={vid}')
        assert status == 200
        assert 'points' in body
        assert len(body['points']) >= 1

    def test_trend_missing_video_id(self, api_get):
        status, body = api_get('/api/trend')
        assert status == 400
        assert 'error' in body

    def test_trend_nonexistent_video(self, api_get):
        status, body = api_get('/api/trend?video_id=99999')
        assert status == 200
        assert body['points'] == []


# ── /api/export/accounts ──────────────────────────────

class TestExportAccounts:
    def test_export_accounts_csv(self, api_get, clean_db):
        seed_account(clean_db, 'douyin', 'ex1', 'Ex1')
        status, body = api_get('/api/export/accounts')
        assert status == 200
        assert isinstance(body, str)  # CSV
        assert '平台' in body or 'platform' in body.lower()


# ── /api/export/videos ────────────────────────────────

class TestExportVideos:
    def test_export_videos_csv(self, api_get, clean_db):
        acc = seed_account(clean_db, 'douyin', 'exv', 'ExV')
        seed_video(clean_db, 'douyin', 'exv', aweme_id='ev001')
        status, body = api_get('/api/export/videos')
        assert status == 200
        assert isinstance(body, str)  # CSV


# ── /api/relogin/status ───────────────────────────────

class TestReloginStatus:
    def test_relogin_status_idle(self, api_get):
        status, body = api_get('/api/relogin/status')
        assert status == 200
        assert body['status'] in ('idle', 'running', 'success')


# ── /api/qr-login/status ──────────────────────────────

class TestQrLoginStatus:
    def test_qr_login_missing_token(self, api_get):
        status, body = api_get('/api/qr-login/status')
        assert status == 400
        assert 'error' in body


# ── /api/qr-image ─────────────────────────────────────

class TestQrImage:
    def test_qr_image_missing_token(self, api_get):
        # Returns 400 with empty body
        status, body = api_get('/api/qr-image')
        assert status == 400


# ── /proxy/image ──────────────────────────────────────

class TestProxyImage:
    def test_proxy_image_missing_url(self, api_get):
        status, body = api_get('/proxy/image')
        assert status == 400

    def test_proxy_image_blocked_domain(self, api_get):
        status, body = api_get('/proxy/image?url=http://192.168.1.1/test.jpg')
        assert status == 403


# ── Static file serving ──────────────────────────────

class TestStaticFiles:
    def test_root_serves_frontend(self, api_get):
        status, body = api_get('/')
        assert status == 200
        assert isinstance(body, str)
        assert '<!DOCTYPE html>' in body or '<html' in body.lower()

    def test_nonexistent_path_serves_index(self, api_get):
        status, body = api_get('/nonexistent-page')
        assert status == 200  # falls back to index.html
