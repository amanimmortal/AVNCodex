import sqlite3
import os
from app.logging_config import logger

def get_db_connection(db_path):
    """Establishes a connection to the database."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Failed to connect to database at {db_path}: {e}")
        return None

def initialize_database(db_path):
    """Initializes the SQLite database and creates the 'games' table if it doesn't exist."""
    # Ensure db directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir): 
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"Database directory created: {db_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create database directory {db_dir}. Error: {e}")
            return
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        
        # Enable WAL mode for concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        
        cursor = conn.cursor()

        # Enable foreign key support
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TEXT NOT NULL
            )
        """)
        
        # Update games table schema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                f95_url TEXT UNIQUE NOT NULL,
                name TEXT,
                version TEXT,
                author TEXT,
                image_url TEXT,
                rss_pub_date TEXT,
                completed_status TEXT DEFAULT 'UNKNOWN',
                first_added_to_db TEXT NOT NULL,
                last_seen_on_rss TEXT NOT NULL,
                last_updated_in_db TEXT NOT NULL,
                last_checked_at TEXT DEFAULT NULL,
                -- New fields for scraper data
                description TEXT DEFAULT NULL,
                engine TEXT DEFAULT NULL,
                language TEXT DEFAULT NULL,
                censorship TEXT DEFAULT NULL,
                tags_json TEXT DEFAULT NULL, -- For storing tags as a JSON list
                download_links_json TEXT DEFAULT NULL, -- For storing download links as JSON
                download_links_raw_html TEXT DEFAULT NULL, -- Raw extracted download block
                scraper_last_run_at TEXT DEFAULT NULL, -- Timestamp of the last successful scrape
                os_list TEXT DEFAULT NULL,
                release_date TEXT DEFAULT NULL,
                thread_updated_date TEXT DEFAULT NULL
            )
        """)
        
        # Check and add columns if missing (Simple migration logic)
        cursor.execute("PRAGMA table_info(games)")
        columns = [column[1] for column in cursor.fetchall()]
        
        new_columns_to_add = {
            'last_checked_at': "TEXT DEFAULT NULL",
            'description': "TEXT DEFAULT NULL",
            'engine': "TEXT DEFAULT NULL",
            'language': "TEXT DEFAULT NULL",
            'censorship': "TEXT DEFAULT NULL",
            'tags_json': "TEXT DEFAULT NULL",
            'download_links_json': "TEXT DEFAULT NULL",
            'download_links_raw_html': "TEXT DEFAULT NULL",
            'scraper_last_run_at': "TEXT DEFAULT NULL",
            'os_list': "TEXT DEFAULT NULL",
            'release_date': "TEXT DEFAULT NULL",
            'thread_updated_date': "TEXT DEFAULT NULL"
        }

        for col_name, col_def in new_columns_to_add.items():
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_def}")
                logger.info(f"Added '{col_name}' column to 'games' table.")

        # Create user_played_games table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_played_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
                section TEXT DEFAULT 'playing',
                user_notes TEXT,
                user_rating REAL, -- e.g., 0.0 to 5.0
                notify_for_updates BOOLEAN DEFAULT TRUE,
                date_added_to_played_list TEXT NOT NULL,
                last_notified_version TEXT, 
                last_notified_rss_pub_date TEXT, 
                last_notified_completion_status TEXT, 
                user_acknowledged_version TEXT, 
                user_acknowledged_rss_pub_date TEXT, 
                user_acknowledged_completion_status TEXT, 
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
                UNIQUE(user_id, game_id)
            )
        """)
        
        # Check and add missing columns to user_played_games for older databases
        cursor.execute("PRAGMA table_info(user_played_games)")
        upg_columns = [column[1] for column in cursor.fetchall()]

        potential_missing_upg_cols = {
            'section': "TEXT DEFAULT 'playing'",
            'user_acknowledged_version': "TEXT",
            'user_acknowledged_rss_pub_date': "TEXT",
            'last_notified_completion_status': "TEXT",
            'user_acknowledged_completion_status': "TEXT"
        }

        for col, col_type in potential_missing_upg_cols.items():
            if col not in upg_columns:
                try:
                    cursor.execute(f"ALTER TABLE user_played_games ADD COLUMN {col} {col_type}")
                    logger.info(f"Added '{col}' column to 'user_played_games' table.")
                    conn.commit() # Commit individually to be safe
                except sqlite3.Error as e:
                    logger.error(f"Error adding column {col}: {e}")

        
        # Create app_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                user_id INTEGER NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                PRIMARY KEY (user_id, setting_key),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
        logger.info(f"Database initialized successfully at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Database error during initialization: {e}")
    finally:
        if conn:
            conn.close()

def get_primary_admin_user_id(db_path: str):
    """Retrieves the ID of the first admin user (lowest ID)."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE is_admin = 1 ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0]
        logger.info("No primary admin user ID found (is_admin=1).")
        return None
    except sqlite3.Error as e:
        logger.error(f"Database error getting primary admin user ID: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_user_ids(db_path: str) -> list[int]:
    """Retrieves a list of all user IDs."""
    conn = None
    user_ids = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users ORDER BY id ASC")
        rows = cursor.fetchall()
        user_ids = [row[0] for row in rows]
        return user_ids
    except sqlite3.Error as e:
        logger.error(f"Database error getting all user IDs: {e}")
        return [] 
    finally:
        if conn:
            conn.close()

def get_all_users_details(db_path: str) -> list[dict]:
    """Retrieves details (id, username, is_admin, created_at) for all users."""
    conn = None
    users_details = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY username ASC")
        rows = cursor.fetchall()
        for row in rows:
            users_details.append(dict(row))
        return users_details
    except sqlite3.Error as e:
        logger.error(f"Database error getting all users details: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_setting(db_path: str, key: str, default_value: str = None, user_id: int = None) -> str:
    """
    Retrieves a setting value from the app_settings table for a specific user.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("SELECT setting_value FROM app_settings WHERE user_id = ? AND setting_key = ?", (user_id, key))
        else:
            logger.warning(f"get_setting called for key '{key}' with user_id=None. Returning default.")
            return default_value

        row = cursor.fetchone()
        if row:
            return row[0]
        return default_value
    except sqlite3.Error as e:
        logger.error(f"Database error getting setting '{key}' for user_id '{user_id}': {e}")
        return default_value
    finally:
        if conn:
            conn.close()

def set_setting(db_path: str, key: str, value: str, user_id: int = None) -> bool:
    """
    Saves or updates a setting for a specific user.
    If user_id is None, it attempts to save a global setting (owned by primary admin).
    """
    target_user_id = user_id
    if user_id is None: # Indicates a request for a global setting
        if key == 'update_schedule_hours_global': 
            target_user_id = get_primary_admin_user_id(db_path)
        else:
            logger.error(f"set_setting called with user_id=None for non-global key '{key}'. Operation aborted.")
            return False

    if target_user_id is None:
        logger.error(f"Cannot determine target user ID for setting '{key}'. Operation aborted.")
        return False

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO app_settings (user_id, setting_key, setting_value) VALUES (?, ?, ?)", 
                       (target_user_id, key, value))
        conn.commit()
        logger.info(f"Setting '{key}' for user {target_user_id} saved with value: '{value}'")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error setting '{key}' for user {target_user_id} to '{value}': {e}")
        return False
    finally:
        if conn:
            conn.close()
