#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/eric/social-monitor')

try:
    from db import get_db, migrate, MONITOR_DIR, DB_PATH, FRONTEND_DIR
    print(f"db.py OK — DB_PATH={DB_PATH}, FRONTEND_DIR={FRONTEND_DIR}")

    from utils import json_response, read_body, spawn_script, validate_str, validate_int, validate_platform, csv_quote, is_safe_image_url
    print("utils.py OK")

    from api.accounts import handle as accounts_handle
    from api.groups import handle as groups_handle
    from api.keywords import handle as keywords_handle
    from api.config import handle as config_handle
    from api.collect import handle as collect_handle
    from api.relogin import handle as relogin_handle
    from api.health import handle as health_handle
    from api.data import handle as data_handle
    print("All api modules OK")

    # Test migrate
    migrate()
    print("migrate() OK")

    # Check schema_version
    conn = get_db()
    ver = conn.execute("SELECT * FROM schema_version ORDER BY version").fetchall()
    print(f"Applied migrations: {[dict(r) for r in ver]}")
    conn.close()

    print("\n✅ All checks passed")
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
