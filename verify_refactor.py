import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

try:
    # Mock pushover to bypass missing dependency in this env
    from unittest.mock import MagicMock
    import sys
    sys.modules["pushover"] = MagicMock()
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.sync_api"] = MagicMock()
    sys.modules["apscheduler"] = MagicMock()
    sys.modules["apscheduler.schedulers.background"] = MagicMock()
    sys.modules["apscheduler.triggers.interval"] = MagicMock()
    print("Mocked pushover, playwright, and apscheduler modules.")

    print("Attempting to import app...")
    from run_app import flask_app
    print("Import successful.")

    print("Checking database initialization...")
    from app.database import get_db_connection, initialize_database
    db_path = "test_db.sqlite"
    initialize_database(db_path)
    conn = get_db_connection(db_path)
    if conn:
        print("Database connection successful.")
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        print(f"Journal Mode: {mode}")
        if mode.upper() == 'WAL':
            print("WAL mode confirmed.")
        else:
            print("WARNING: WAL mode not active.")
        conn.close()
    else:
        print("Database connection failed.")
    
    # Cleanup test db
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Test DB removed.")

    print("Checking routes...")
    # Get all rule patterns
    rules = [rule.rule for rule in flask_app.url_map.iter_rules()]
    required_routes = [
        '/search', '/admin/users', '/search_games_api', '/manual_sync_all', 
        '/manual_sync_game/<int:played_game_id>', '/edit_game/<int:played_game_id>', 
        '/acknowledge_update/<int:played_game_id>', '/change_password'
    ]
    
    missing = [req for req in required_routes if req not in rules]
    if missing:
        raise Exception(f"Missing required routes: {missing}")
    print("All required routes found.")
        
    print("Refactor verification complete.")

except Exception as e:
    print(f"Verification FAILED: {e}")
    sys.exit(1)
