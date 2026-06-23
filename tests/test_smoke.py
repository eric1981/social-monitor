"""Smoke test — verify conftest fixtures work."""
import json


def test_server_starts(api_get):
    """Server is reachable."""
    status, body = api_get('/api/health')
    assert status == 200
    assert isinstance(body, dict)


def test_db_fixture(db):
    """Database fixture works."""
    db.execute("SELECT 1")
    assert True


def test_seed_helpers(clean_db, api_get):
    """Can seed data and query it."""
    from tests.conftest import seed_account, seed_video, seed_keyword

    seed_account(clean_db, 'douyin', 'test1', 'Tester1')
    seed_video(clean_db, 'douyin', 'test1', aweme_id='v001')
    seed_keyword(clean_db, 'hello')

    status, body = api_get('/api/data')
    assert status == 200
    assert len(body.get('accounts', [])) >= 1
    assert len(body.get('videos', [])) >= 1

    status2, body2 = api_get('/api/keywords')
    assert status2 == 200
    assert len(body2.get('keywords', [])) >= 1
