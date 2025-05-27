import sys
import os
import time # Added for rate limiting

# Add project root to sys.path to allow importing f95apiclient
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import sqlite3
import logging
import os
from datetime import datetime, timezone, timedelta # Ensure all are imported
from email.utils import parsedate_to_datetime # Added for RSS date parsing
from dotenv import load_dotenv
from f95apiclient import F95ApiClient # Assuming f95apiclient is in PYTHONPATH or installed
from typing import Optional, Set # Added Set
import re # Added for regex in get_first_significant_word
from pushover import Client as PushoverClient # Added for Pushover
from apscheduler.schedulers.background import BackgroundScheduler

# --- Constants ---
DB_PATH = "/data/f95_games.db" # Changed for Docker volume
ENV_FILE_PATH = "f95.env" # This might also need to be volume mapped if used
LOG_FILE_PATH = "/data/logs/update_checker.log" # Changed for Docker volume
NUM_GAMES_TO_PROCESS_FROM_RSS = 60 # Process all games from RSS by default
MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK = 90 # Adjusted to observed RSS limit

# --- Logging Setup ---
def setup_logging():
    """Configures logging for the application."""
    # Ensure log directory exists
    log_dir = os.path.dirname(LOG_FILE_PATH)
    # Check and create directory before basicConfig tries to open the file handler
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            # If logger isn't configured yet, a simple print might be necessary for this initial step
            print(f"Log directory created: {log_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create log directory {log_dir}. Error: {e}")
            # Decide on fallback or exit strategy if logging is critical
            # For now, allow to proceed, basicConfig might fail or log to current dir if path invalid.
    
    logging.basicConfig(
        level=logging.INFO, # CHANGED from DEBUG to INFO
        format='%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE_PATH, mode='a'), # Append to log file
            logging.StreamHandler() # Also print to console
        ]
    )
    # Silence excessively verbose loggers (e.g., urllib3)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# --- Database Functions ---
def initialize_database(db_path):
    """Initializes the SQLite database and creates the 'games' table if it doesn't exist."""
    # Ensure db directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir): # Check if db_dir is not empty (for relative paths in root)
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"Database directory created: {db_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create database directory {db_dir}. Error: {e}")
            return
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
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
                last_checked_at TEXT DEFAULT NULL 
            )
        """)
        
        cursor.execute("PRAGMA table_info(games)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'last_checked_at' not in columns:
            cursor.execute("ALTER TABLE games ADD COLUMN last_checked_at TEXT DEFAULT NULL")
            logger.info("Added 'last_checked_at' column to 'games' table.")

        # Create user_played_games table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_played_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
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
        # print(f"DEBUG_INIT_DB: Columns in user_played_games before alter: {upg_columns}", file=sys.stderr) # REMOVE

        if 'user_acknowledged_version' not in upg_columns:
            # print("DEBUG_INIT_DB: Attempting to add user_acknowledged_version.", file=sys.stderr) # REMOVE
            cursor.execute("ALTER TABLE user_played_games ADD COLUMN user_acknowledged_version TEXT")
            conn.commit()
            logger.info("Added 'user_acknowledged_version' column to 'user_played_games' table.")
            # print("DEBUG_INIT_DB: Committed user_acknowledged_version.", file=sys.stderr) # REMOVE
        
        if 'user_acknowledged_rss_pub_date' not in upg_columns:
            # print("DEBUG_INIT_DB: Attempting to add user_acknowledged_rss_pub_date.", file=sys.stderr) # REMOVE
            cursor.execute("ALTER TABLE user_played_games ADD COLUMN user_acknowledged_rss_pub_date TEXT")
            conn.commit()
            logger.info("Added 'user_acknowledged_rss_pub_date' column to 'user_played_games' table.")
            # print("DEBUG_INIT_DB: Committed user_acknowledged_rss_pub_date.", file=sys.stderr) # REMOVE

        if 'last_notified_completion_status' not in upg_columns:
            # print("DEBUG_INIT_DB: 'last_notified_completion_status' NOT FOUND in columns.", file=sys.stderr) # REMOVE
            # print("DEBUG_INIT_DB: Attempting to add last_notified_completion_status.", file=sys.stderr) # REMOVE
            try:
                cursor.execute("ALTER TABLE user_played_games ADD COLUMN last_notified_completion_status TEXT")
                # print("DEBUG_INIT_DB: Executed ALTER TABLE for last_notified_completion_status.", file=sys.stderr) # REMOVE
                conn.commit()
                logger.info("Added 'last_notified_completion_status' column to 'user_played_games' table.")
                # print("DEBUG_INIT_DB: Committed last_notified_completion_status.", file=sys.stderr) # REMOVE
                
                # Immediate re-check for this specific column
                cursor.execute("PRAGMA table_info(user_played_games)")
                rechecked_columns = [column_info[1] for column_info in cursor.fetchall()]
                if 'last_notified_completion_status' in rechecked_columns:
                    # print("DEBUG_INIT_DB: CONFIRMED - 'last_notified_completion_status' IS PRESENT after specific add and commit.", file=sys.stderr) # REMOVE
                    pass
                else:
                    # print("DEBUG_INIT_DB: CRITICAL FAILURE - 'last_notified_completion_status' IS STILL MISSING after specific add and commit.", file=sys.stderr) # REMOVE
                    logger.error("CRITICAL FAILURE - 'last_notified_completion_status' IS STILL MISSING after specific add and commit.")

            except sqlite3.Error as e_alter_lncs:
                # print(f"DEBUG_INIT_DB: SQLITE ERROR during ALTER TABLE for last_notified_completion_status: {e_alter_lncs}", file=sys.stderr) # REMOVE
                logger.error(f"SQLITE ERROR during ALTER TABLE for last_notified_completion_status: {e_alter_lncs}")
            except Exception as e_alter_lncs_generic:
                # print(f"DEBUG_INIT_DB: GENERIC ERROR during ALTER TABLE for last_notified_completion_status: {e_alter_lncs_generic}", file=sys.stderr) # REMOVE
                logger.error(f"GENERIC ERROR during ALTER TABLE for last_notified_completion_status: {e_alter_lncs_generic}")
        else:
            # print("DEBUG_INIT_DB: 'last_notified_completion_status' ALREADY FOUND in columns.", file=sys.stderr) # REMOVE
            pass

        # Check for user_acknowledged_completion_status (this block should already exist and be correct)
        if 'user_acknowledged_completion_status' not in upg_columns:
            # print("DEBUG_INIT_DB: 'user_acknowledged_completion_status' NOT FOUND in columns.", file=sys.stderr) # REMOVE
            # print("DEBUG_INIT_DB: Attempting to add user_acknowledged_completion_status.", file=sys.stderr) # REMOVE
            try:
                cursor.execute("ALTER TABLE user_played_games ADD COLUMN user_acknowledged_completion_status TEXT")
                # print("DEBUG_INIT_DB: Executed ALTER TABLE for user_acknowledged_completion_status.", file=sys.stderr) # REMOVE
                conn.commit()
                logger.info("Added 'user_acknowledged_completion_status' column to 'user_played_games' table.")
                # print("DEBUG_INIT_DB: Committed user_acknowledged_completion_status.", file=sys.stderr) # REMOVE
            except sqlite3.Error as e_alter:
                # print(f"DEBUG_INIT_DB: SQLITE ERROR during ALTER TABLE for user_acknowledged_completion_status: {e_alter}", file=sys.stderr) # REMOVE
                logger.error(f"SQLITE ERROR during ALTER TABLE for user_acknowledged_completion_status: {e_alter}")
            except Exception as e_alter_generic:
                # print(f"DEBUG_INIT_DB: GENERIC ERROR during ALTER TABLE for user_acknowledged_completion_status: {e_alter_generic}", file=sys.stderr) # REMOVE
                logger.error(f"GENERIC ERROR during ALTER TABLE for user_acknowledged_completion_status: {e_alter_generic}")
        else:
            # print("DEBUG_INIT_DB: 'user_acknowledged_completion_status' ALREADY FOUND in columns.", file=sys.stderr) # REMOVE
            pass
        
        # Refresh column list to see if it was added
        cursor.execute("PRAGMA table_info(user_played_games)")
        upg_columns_after = [column[1] for column in cursor.fetchall()]
        # print(f"DEBUG_INIT_DB: Columns in user_played_games AFTER alter attempts: {upg_columns_after}", file=sys.stderr) # REMOVE
        
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

def get_primary_admin_user_id(db_path: str) -> Optional[int]:
    """Retrieves the ID of the first admin user (lowest ID)."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Assuming is_admin is 1 for True (standard for SQLite boolean)
        cursor.execute("SELECT id FROM users WHERE is_admin = 1 ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0]
        # Log if no admin found, as this might be unexpected in some contexts
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
        return [] # Return empty list on error
    finally:
        if conn:
            conn.close()

def get_all_users_details(db_path: str) -> list[dict]:
    """Retrieves details (id, username, is_admin, created_at) for all users."""
    conn = None
    users_details = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row # To access columns by name
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY username ASC")
        rows = cursor.fetchall()
        for row in rows:
            users_details.append(dict(row))
        return users_details
    except sqlite3.Error as e:
        logger.error(f"Database error getting all users details: {e}")
        return [] # Return empty list on error
    finally:
        if conn:
            conn.close()

def process_rss_feed(db_path, client):
    """
    Fetches game data from RSS, compares with the database, 
    and updates the database with new games or new versions.
    """
    logger.info("Starting RSS feed processing...")
    
    game_items = client.get_latest_game_data_from_rss(limit=NUM_GAMES_TO_PROCESS_FROM_RSS)
    if not game_items:
        logger.info("No game items fetched from RSS feed. Nothing to process.")
        return

    logger.info(f"Fetched {len(game_items)} items from RSS feed.")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        current_timestamp = datetime.now(timezone.utc).isoformat()

        for item in game_items:
            f95_url = item.get('url')
            if not f95_url:
                logger.warning(f"Skipping item due to missing URL: {item.get('name_rss', 'N/A')}")
                continue

            # Sanitize None values to avoid issues with DB or comparisons
            name_rss = item.get('name_rss')
            version_rss = item.get('version_rss')
            author_rss = item.get('author_rss')
            image_url_rss = item.get('image_url_rss')
            pub_date_rss = item.get('pub_date_rss')

            cursor.execute("SELECT version, rss_pub_date FROM games WHERE f95_url = ?", (f95_url,))
            row = cursor.fetchone()

            if row is None:
                # New game
                cursor.execute("""
                    INSERT INTO games (f95_url, name, version, author, image_url, rss_pub_date, 
                                     first_added_to_db, last_seen_on_rss, last_updated_in_db)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f95_url, name_rss, version_rss, author_rss, image_url_rss, pub_date_rss,
                      current_timestamp, current_timestamp, current_timestamp))
                conn.commit()
                logger.info(f"New game added: '{name_rss}' (Version: {version_rss}) from URL: {f95_url}")
            else:
                # Existing game
                db_version, db_rss_pub_date = row
                updated = False

                # Check for updates
                # Note: Direct string comparison for versions and dates might not be robust for all cases
                # but is a starting point. More sophisticated version/date parsing could be added.
                if version_rss is not None and version_rss != db_version:
                    updated = True
                elif pub_date_rss is not None and pub_date_rss != db_rss_pub_date: # Simplistic date check, assumes newer date string is 'greater'
                    # A more robust check would parse dates into datetime objects
                    updated = True 
                
                if updated:
                    cursor.execute("""
                        UPDATE games 
                        SET name = ?, version = ?, author = ?, image_url = ?, rss_pub_date = ?, 
                            last_seen_on_rss = ?, last_updated_in_db = ?
                        WHERE f95_url = ?
                    """, (name_rss, version_rss, author_rss, image_url_rss, pub_date_rss,
                          current_timestamp, current_timestamp, f95_url))
                    conn.commit()
                    logger.info(f"Game updated: '{name_rss}' to Version: {version_rss} (Old ver: {db_version}, Old pub: {db_rss_pub_date}, New pub: {pub_date_rss}) URL: {f95_url}")
                else:
                    # No version/date change, just update last_seen_on_rss
                    cursor.execute("UPDATE games SET last_seen_on_rss = ? WHERE f95_url = ?", 
                                   (current_timestamp, f95_url))
                    conn.commit()
                    logger.debug(f"No update for game: '{name_rss}'. Last seen updated. URL: {f95_url}")
        
        logger.info("Finished processing RSS feed items against the database.")

    except sqlite3.Error as e:
        logger.error(f"Database error during RSS feed processing: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error during RSS feed processing: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Settings Functions ---
def get_setting(db_path: str, key: str, default_value: Optional[str] = None, user_id: Optional[int] = None) -> Optional[str]:
    """
    Retrieves a setting value from the app_settings table for a specific user.
    If user_id is None, it implies a non-user-specific context or an error.
    For global settings like 'update_schedule_hours_global', user_id for the primary admin should be provided by the caller.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("SELECT setting_value FROM app_settings WHERE user_id = ? AND setting_key = ?", (user_id, key))
        else:
            # This case should ideally be handled by the caller by providing the primary admin's user_id for global settings.
            # If user_id is None, we are trying to fetch a setting not tied to a specific user.
            # This might be valid for settings that are truly global and not under any user_id,
            # but current schema has user_id in PK.
            # For 'update_schedule_hours_global', the caller (app.py) should resolve the primary admin ID.
            logger.warning(f"get_setting called for key '{key}' with user_id=None. This might not yield expected results for user-specific settings or global settings stored under an admin.")
            # Attempt to fetch if there's a setting with a NULL user_id (though schema doesn't directly support this for PK user_id)
            # Or, this branch could be removed if all settings are strictly user_id-bound or global-admin-bound.
            # For now, let it try to find a match for the key alone if user_id is None, though this is unlikely with current schema.
            # A better approach for global settings: caller gets primary admin ID and passes it.
            # If we assume global settings are stored with primary_admin_id, then caller MUST provide it.
            # If user_id is None here, it implies the caller didn't specify, so return default.
            logger.debug(f"get_setting for '{key}' with user_id=None, will return default_value if not found through other means (e.g. primary admin passed by caller).")
            # The query below would fail if user_id is part of PK and NOT NULL.
            # cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = ? AND user_id IS NULL", (key,))
            # Given current design (global settings stored under primary admin), user_id should always be provided.
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

def set_setting(db_path: str, key: str, value: str, user_id: Optional[int] = None) -> bool:
    """
    Saves or updates a setting for a specific user.
    If user_id is None, it attempts to save a global setting (owned by primary admin).
    """
    target_user_id = user_id
    if user_id is None: # Indicates a request for a global setting
        if key == 'update_schedule_hours_global': # Only certain keys are treated as global
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

# --- Pushover Notification Function ---
def send_pushover_notification(db_path: str, user_id: int, title: str, message: str, priority: int = 0, url: Optional[str] = None, url_title: Optional[str] = None):
    """Sends a notification via Pushover if configured for the given user."""
    user_key = get_setting(db_path, 'pushover_user_key', user_id=user_id)
    api_key = get_setting(db_path, 'pushover_api_key', user_id=user_id)

    if not user_key or not api_key:
        logger.info(f"Pushover user_key or api_key not configured for user_id {user_id}. Skipping notification '{title}'.")
        return

    try:
        client = PushoverClient(user_key, api_token=api_key)
        client.send_message(message, title=title, priority=priority, url=url, url_title=url_title)
        logger.info(f"Pushover notification sent: '{title}'")
    except Exception as e:
        logger.error(f"Failed to send Pushover notification for '{title}': {e}", exc_info=True)

# --- User-Specific Game Management Functions ---

def search_games_for_user(client: F95ApiClient, search_term: str, limit: int = 10) -> list[dict]:
    """
    Searches the F95Zone RSS feed for games matching the search term.
    Returns a list of game data dictionaries (not yet saved to any user list).
    """
    logger.info(f"Searching RSS feed for term: '{search_term}' with limit {limit}")
    if not search_term or not search_term.strip():
        logger.warning("Search term is empty. Returning no results.")
        return []
    
    try:
        game_items = client.get_latest_game_data_from_rss(search_term=search_term, limit=limit)
        logger.info(f"Search for '{search_term}' returned {len(game_items)} items from RSS.")
        return game_items
    except Exception as e:
        logger.error(f"Error during RSS search for '{search_term}': {e}", exc_info=True)
        return []

def add_game_to_my_list(db_path: str,
                        user_id: int, # Added user_id
                        client: F95ApiClient,
                        f95_url: str,
                        name_override: str = None,
                        version_override: str = None,
                        author_override: str = None,
                        image_url_override: str = None,
                        rss_pub_date_override: str = None,
                        game_data: dict = None, # Kept for potential internal use, but overrides take precedence
                        user_notes: str = None, 
                        user_rating: float = None, 
                        notify: bool = True) -> tuple[bool, str]:
    """
    Adds a game to the user's played list.
    First, ensures the game exists in the main 'games' table (adding/updating it if necessary
    using provided overrides or data from game_data).
    Then, adds its reference to the 'user_played_games' table.

    Args:
        db_path: Path to the SQLite database.
        client: F95ApiClient instance for accessing RSS feeds.
        f95_url: The unique F95Zone URL for the game.
        name_override: Optional direct override for the game's name.
        version_override: Optional direct override for the game's version.
        author_override: Optional direct override for the game's author.
        image_url_override: Optional direct override for the game's image URL.
        rss_pub_date_override: Optional direct override for the game's RSS publication date.
        game_data: Optional dictionary containing game details (e.g., from RSS).
                   Overrides will take precedence.
        user_notes: Optional notes from the user about the game.
        user_rating: Optional rating from the user (e.g., 0.0-5.0).
        notify: Whether to notify for updates by default.

    Returns:
        A tuple (success: bool, message: str).
    """
    if not f95_url:
        return False, "Game URL is required."

    # Determine game details: overrides > game_data > defaults
    name_to_use = name_override if name_override is not None else (game_data.get('name_rss') if game_data else "Unknown Name")
    version_to_use = version_override if version_override is not None else (game_data.get('version_rss') if game_data else "Unknown Version")
    author_to_use = author_override if author_override is not None else (game_data.get('author_rss') if game_data else "Unknown Author")
    image_to_use = image_url_override if image_url_override is not None else (game_data.get('image_url_rss') if game_data else None)
    pub_date_to_use = rss_pub_date_override if rss_pub_date_override is not None else (game_data.get('pub_date_rss') if game_data else None)

    # Determine initial completion status
    # This requires fetching the game's current status when adding it to the list.
    current_game_status = "UNKNOWN" # Default if not found or error

    logger.info(f"Attempting to add game to user list for user_id {user_id}: {name_to_use} ({f95_url})")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        current_timestamp = datetime.now(timezone.utc).isoformat()
        game_id_in_db = None
        current_game_version = version_to_use
        current_game_rss_pub_date = pub_date_to_use
        current_game_completed_status = "UNKNOWN" # Default

        # Try to get the game from the main 'games' table
        cursor.execute("SELECT id, version, rss_pub_date, completed_status FROM games WHERE f95_url = ?", (f95_url,))
        game_row = cursor.fetchone()

        if game_row:
            game_id_in_db = game_row[0]
            current_game_version = game_row[1] if game_row[1] is not None else version_to_use
            current_game_rss_pub_date = game_row[2] if game_row[2] is not None else pub_date_to_use
            current_game_completed_status = game_row[3] if game_row[3] is not None else "UNKNOWN"
            
            # Update existing game entry if overrides are provided or if fetched data is newer
            # For simplicity, always update with provided/fetched info if it differs.
            # A more sophisticated logic would compare dates/versions to decide if an update is warranted.
            update_fields = []
            update_values = []

            if name_to_use != "Unknown Name" and name_to_use != (game_row[0] if len(game_row) > 4 else None): # Assuming name was part of an extended select if we had it
                 # Need to re-query if name is not in game_row, or assume it won't change often once added
                 pass # For now, don't update name, version, author etc. in games table here, focus on adding to user list

            if version_to_use != "Unknown Version" and version_to_use != current_game_version:
                update_fields.append("version = ?")
                update_values.append(version_to_use)
                current_game_version = version_to_use
            if author_to_use != "Unknown Author" and author_to_use != (game_row[0] if len(game_row) > 5 else None): # Placeholder for author
                # update_fields.append("author = ?")
                # update_values.append(author_to_use)
                pass
            if image_to_use is not None and image_to_use != (game_row[0] if len(game_row) > 6 else None): # Placeholder for image
                # update_fields.append("image_url = ?")
                # update_values.append(image_to_use)
                pass
            if pub_date_to_use is not None and pub_date_to_use != current_game_rss_pub_date:
                update_fields.append("rss_pub_date = ?")
                update_values.append(pub_date_to_use)
                current_game_rss_pub_date = pub_date_to_use

            if update_fields:
                update_fields.append("last_updated_in_db = ?")
                update_values.append(current_timestamp)
                query = f"UPDATE games SET {', '.join(update_fields)} WHERE id = ?"
                update_values.append(game_id_in_db)
                cursor.execute(query, tuple(update_values))
                logger.info(f"Updated existing game in 'games' table: ID {game_id_in_db} - {name_to_use}")
        else:
            # Game not in 'games' table, add it
            # Before adding, try to determine its current status
            logger.info(f"Game '{name_to_use}' not in 'games' table. Querying status before adding.")
            
            # Extract first significant word from name for search
            search_name_part = get_first_significant_word(name_to_use) # Use helper
            if not search_name_part:
                logger.warning(f"Could not derive a search term for '{name_to_use}'. Status will default to UNKNOWN.")
                current_game_completed_status = "UNKNOWN"
            else:
                # Check for COMPLETED status
                completed_games_rss = client.get_latest_game_data_from_rss(
                    search_term=search_name_part, 
                    completion_status_filter="completed",
                    limit=MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK # Use defined constant
                )
                if completed_games_rss is None:
                     logger.warning(f"Failed to fetch 'completed' RSS feed for game '{name_to_use}' during add_game_to_my_list. Status determination may be impacted.")
                     # current_game_completed_status remains "UNKNOWN" or its previous value if this isn't the first check
                elif any(g['url'] == f95_url for g in completed_games_rss):
                    current_game_completed_status = "COMPLETED"
                
                # If not found as COMPLETED, check for ABANDONED
                if current_game_completed_status == "UNKNOWN":
                    abandoned_games_rss = client.get_latest_game_data_from_rss(
                        search_term=search_name_part,
                        completion_status_filter="abandoned",
                        limit=MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK
                    )
                    if abandoned_games_rss is None:
                        logger.warning(f"Failed to fetch 'abandoned' RSS feed for game '{name_to_use}' during add_game_to_my_list.")
                    elif any(g['url'] == f95_url for g in abandoned_games_rss):
                        current_game_completed_status = "ABANDONED"

                # If not found as COMPLETED or ABANDONED, check for ON_HOLD
                if current_game_completed_status == "UNKNOWN":
                    on_hold_games_rss = client.get_latest_game_data_from_rss(
                        search_term=search_name_part,
                        completion_status_filter="on_hold",
                        limit=MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK
                    )
                    if on_hold_games_rss is None:
                        logger.warning(f"Failed to fetch 'on_hold' RSS feed for game '{name_to_use}' during add_game_to_my_list.")
                    elif any(g['url'] == f95_url for g in on_hold_games_rss):
                        current_game_completed_status = "ON_HOLD"

                # If not found in any specific status feeds, assume ONGOING
                if current_game_completed_status == "UNKNOWN":
                    # We don't explicitly query "ongoing" here as it's the default if not in other categories.
                    # An "ongoing" check could be added if needed, but for adding a new game,
                    # if it's not explicitly completed, on-hold, or abandoned, "ONGOING" is a reasonable assumption.
                    # However, to be consistent, we could do an "ongoing" search.
                    # For now, if still UNKNOWN, it becomes ONGOING.
                    logger.info(f"Game '{name_to_use}' not found in Completed, Abandoned, or On-Hold feeds. Assuming ONGOING.")
                    current_game_completed_status = "ONGOING"
            
            logger.info(f"Determined status for new game '{name_to_use}': {current_game_completed_status}")

            cursor.execute("""
                INSERT INTO games (f95_url, name, version, author, image_url, rss_pub_date, completed_status,
                                 first_added_to_db, last_seen_on_rss, last_updated_in_db)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f95_url, name_to_use, version_to_use, author_to_use, image_to_use, pub_date_to_use, current_game_completed_status,
                  current_timestamp, current_timestamp, current_timestamp))
            game_id_in_db = cursor.lastrowid
            logger.info(f"Added new game to 'games' table: ID {game_id_in_db} - {name_to_use} with status {current_game_completed_status}")

        # Now, add to user_played_games
        if game_id_in_db:
            try:
                cursor.execute("""
                    INSERT INTO user_played_games (
                        user_id, game_id, user_notes, user_rating, notify_for_updates, date_added_to_played_list,
                        last_notified_version, last_notified_rss_pub_date, last_notified_completion_status,
                        user_acknowledged_version, user_acknowledged_rss_pub_date, user_acknowledged_completion_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, game_id_in_db, user_notes, user_rating, notify, current_timestamp,
                      current_game_version, current_game_rss_pub_date, current_game_completed_status, # Initialize last_notified_*
                      current_game_version, current_game_rss_pub_date, current_game_completed_status  # Initialize user_acknowledged_*
                      ))
                conn.commit()
                logger.info(f"Game ID {game_id_in_db} ('{name_to_use}') added to user_played_games for user_id {user_id}. Initial acknowledged state set.")
                
                # Send Pushover notification for game add
                if get_setting(db_path, 'notify_on_game_add', 'False', user_id=user_id) == 'True': # Pass user_id
                    send_pushover_notification(
                        db_path,
                        user_id=user_id, # Pass user_id
                        title=f"Game Added: {name_to_use}",
                        message=f"'{name_to_use}' was added to your monitored list.{chr(10)}Status: {current_game_completed_status}, Version: {current_game_version}",
                        url=f95_url,
                        url_title=f"View {name_to_use} on F95Zone"
                    )
                return True, f"Game '{name_to_use}' added to your list."
            except sqlite3.IntegrityError: # Handles UNIQUE constraint violation (game_id already in user_played_games)
                conn.rollback()
                logger.warning(f"Game ID {game_id_in_db} ('{name_to_use}') is already in user_played_games for user_id {user_id}.")
                return False, f"Game '{name_to_use}' is already in your list."
        else:
            # This case should ideally not be reached if game insertion/retrieval was successful
            logger.error(f"Failed to obtain game_id for {f95_url}. Cannot add to user list.")
            return False, "Failed to add game to your list due to an internal error (game_id not found)."

    except sqlite3.Error as e:
        logger.error(f"Database error while adding game '{f95_url}' to user list: {e}", exc_info=True)
        return False, f"Database error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error while adding game '{f95_url}' to user list: {e}", exc_info=True)
        return False, f"An unexpected error occurred: {e}"
    finally:
        if conn:
            conn.close()

def get_user_played_game_urls(db_path: str, user_id: int) -> Set[str]:
    """
    Retrieves a set of F95 URLs for all games in the specified user's played list.
    """
    urls = set()
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.f95_url
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.user_id = ?
        """, (user_id,))
        rows = cursor.fetchall()
        for row in rows:
            urls.add(row[0])
        logger.info(f"Retrieved {len(urls)} unique F95 URLs from user_id {user_id}'s played list.")
    except sqlite3.Error as e:
        logger.error(f"Database error in get_user_played_game_urls for user_id {user_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return urls

def get_my_played_games(db_path: str,
                        user_id: int, # Added user_id
                        name_filter: Optional[str] = None, 
                        min_rating_filter: Optional[float] = None, 
                        sort_by: str = 'name', 
                        sort_order: str = 'ASC') -> list[dict]:
    # logger.critical("ENTERING get_my_played_games FUNCTION NOW") # REMOVE
    logger.info(f"Fetching user's (user_id: {user_id}) played games list with filters: name='{name_filter}', min_rating='{min_rating_filter}', sort_by='{sort_by}', sort_order='{sort_order}'.")
    games_list = []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row # To fetch rows as dictionary-like objects
        cursor = conn.cursor()
        
        base_query = """
            SELECT 
                g.id AS game_db_id, g.f95_url, g.name, g.version, g.author, g.image_url, 
                g.rss_pub_date, g.completed_status, g.first_added_to_db, 
                g.last_seen_on_rss, g.last_updated_in_db,
                upg.id AS played_game_id, upg.user_notes, upg.user_rating, 
                upg.notify_for_updates, upg.date_added_to_played_list,
                upg.last_notified_version, upg.last_notified_rss_pub_date,
                upg.last_notified_completion_status,
                upg.user_acknowledged_version, upg.user_acknowledged_rss_pub_date,
                upg.user_acknowledged_completion_status
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
        """
        
        where_clauses = ["upg.user_id = ?"] # Start with user_id filter
        params = [user_id]

        if name_filter:
            where_clauses.append("g.name LIKE ?")
            params.append(f'%{name_filter}%')
        
        if min_rating_filter is not None:
            try:
                rating_val = float(min_rating_filter)
                if 0 <= rating_val <= 5:
                    where_clauses.append("upg.user_rating >= ?")
                    params.append(rating_val)
                else:
                    logger.warning(f"Invalid min_rating_filter value ignored: {min_rating_filter}")
            except ValueError:
                logger.warning(f"Non-float min_rating_filter value ignored: {min_rating_filter}")

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)
            
        # Sorting logic
        # Validate sort_by and sort_order to prevent SQL injection
        allowed_sort_columns = {
            'name': 'g.name',
            'last_updated': 'g.rss_pub_date', # Changed to use rss_pub_date
            'date_added': 'upg.date_added_to_played_list',
            'rating': 'upg.user_rating' # Added rating sort
        }
        sql_sort_column = allowed_sort_columns.get(sort_by, 'g.name') # Default to g.name if invalid
        sql_sort_order = 'DESC' if sort_order.upper() == 'DESC' else 'ASC' # Default to ASC

        base_query += f" ORDER BY {sql_sort_column} {sql_sort_order}"
        
        cursor.execute(base_query, tuple(params))
        rows = cursor.fetchall()
        # logger.critical(f"get_my_played_games: BEFORE LOOP. Number of rows fetched: {len(rows)}") # REMOVE
        for row_data in rows:
            game_dict = dict(row_data)

            # --- START DEBUG LOGGING FOR ACKNOWLEDGE BUTTON (ALL GAMES) ---
            # logger.info(f"ACK_INFO_ALL (GameID: {game_dict.get('game_db_id')}, PlayedID: {game_dict.get('played_game_id')}) - Comparing for needs_ack:") # REMOVE
            # logger.info(f"  g.version: '{game_dict.get('version')}' (type: {type(game_dict.get('version'))})") # REMOVE
            # logger.info(f"  upg.user_acknowledged_version: '{game_dict.get('user_acknowledged_version')}' (type: {type(game_dict.get('user_acknowledged_version'))})") # REMOVE
            # logger.info(f"  Version Match: {game_dict.get('version') == game_dict.get('user_acknowledged_version')}") # REMOVE

            # logger.info(f"  g.rss_pub_date (raw from DB): '{game_dict.get('rss_pub_date')}' (type: {type(game_dict.get('rss_pub_date'))})") # REMOVE
            # logger.info(f"  upg.user_acknowledged_rss_pub_date: '{game_dict.get('user_acknowledged_rss_pub_date')}' (type: {type(game_dict.get('user_acknowledged_rss_pub_date'))})") # REMOVE
            # logger.info(f"  Raw RSS Date Match (g.rss_pub_date vs upg.user_acknowledged_rss_pub_date): {game_dict.get('rss_pub_date') == game_dict.get('user_acknowledged_rss_pub_date')}") # REMOVE

            # logger.info(f"  g.completed_status: '{game_dict.get('completed_status')}' (type: {type(game_dict.get('completed_status'))})") # REMOVE
            # logger.info(f"  upg.user_acknowledged_completion_status: '{game_dict.get('user_acknowledged_completion_status')}' (type: {type(game_dict.get('user_acknowledged_completion_status'))})") # REMOVE
            # logger.info(f"  Status Match: {game_dict.get('completed_status') == game_dict.get('user_acknowledged_completion_status')}") # REMOVE
            # --- END DEBUG LOGGING ---
            
            # Determine if acknowledgement is needed BEFORE formatting rss_pub_date for display
            needs_ack = False
            if game_dict.get('version') != game_dict.get('user_acknowledged_version'):
                needs_ack = True
            
            if not needs_ack and game_dict.get('rss_pub_date') != game_dict.get('user_acknowledged_rss_pub_date'):
                needs_ack = True
            
            if not needs_ack and game_dict.get('completed_status') != game_dict.get('user_acknowledged_completion_status'):
                needs_ack = True
            game_dict['needs_acknowledgement_flag'] = needs_ack

            # Also log the outcome of needs_ack determination
            # logger.info(f"ACK_INFO_ALL (GameID: {game_dict.get('game_db_id')}, PlayedID: {game_dict.get('played_game_id')}) - Final needs_ack: {needs_ack}") # REMOVE

            raw_pub_date_str = game_dict.get('rss_pub_date')
            if raw_pub_date_str and isinstance(raw_pub_date_str, str) and raw_pub_date_str.strip():
                dt_obj = None
                try:
                    # Attempt to parse ISO 8601 format directly
                    # Handle 'Z' for UTC explicitly for fromisoformat
                    iso_format_str = raw_pub_date_str
                    if iso_format_str.endswith('Z'):
                        iso_format_str = iso_format_str[:-1] + '+00:00'
                    dt_obj = datetime.fromisoformat(iso_format_str)
                except ValueError: # If fromisoformat fails, try parsedate_to_datetime as a fallback
                    try:
                        dt_obj = parsedate_to_datetime(raw_pub_date_str)
                    except Exception as e_fallback:
                        logger.debug(f"Fallback parsedate_to_datetime also failed for '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')}: {e_fallback}")
                        dt_obj = None # Ensure dt_obj is None if fallback fails
                except Exception as e_main_parse: # Catch any other unexpected error from fromisoformat or its prep
                    logger.warning(f"Initial date parsing failed for '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')} due to: {e_main_parse}")
                    dt_obj = None # Ensure dt_obj is None

                if dt_obj:  
                    if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
                        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                    else:
                        dt_obj = dt_obj.astimezone(timezone.utc)
                    game_dict['rss_pub_date'] = dt_obj.strftime('%a, %d %b %Y %H:%M') + ' UTC'
                else: 
                    logger.warning(f"All parsing attempts failed for date string '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')}. Setting to 'Invalid Date'.")
                    game_dict['rss_pub_date'] = 'Invalid Date'
            elif not raw_pub_date_str or not raw_pub_date_str.strip():
                 game_dict['rss_pub_date'] = 'N/A' # Handle empty or whitespace-only strings
            else: # Not a string or None
                game_dict['rss_pub_date'] = 'N/A'
            games_list.append(game_dict)
        logger.info(f"Retrieved {len(games_list)} games from user's played list.")
    except sqlite3.Error as e:
        logger.error(f"Database error in get_my_played_games: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in get_my_played_games: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return games_list

def get_my_played_game_details(db_path: str, user_id: int, played_game_id: int) -> Optional[dict]: # Added user_id
    """
    Retrieves details for a specific game from the user's played list, 
    joined with details from the main games table.
    'played_game_id' is the ID from the user_played_games table, constrained by user_id.
    """
    logger.info(f"Fetching details for played game ID: {played_game_id} for user_id: {user_id}")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row # To fetch row as dictionary-like object
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                g.id AS game_db_id, g.f95_url, g.name, g.version, g.author, g.image_url, 
                g.rss_pub_date, g.completed_status, g.first_added_to_db, 
                g.last_seen_on_rss, g.last_updated_in_db,
                upg.id AS played_game_id, upg.user_notes, upg.user_rating, 
                upg.notify_for_updates, upg.date_added_to_played_list,
                upg.last_notified_version, upg.last_notified_rss_pub_date,
                upg.last_notified_completion_status,
                upg.user_acknowledged_version, upg.user_acknowledged_rss_pub_date,
                upg.user_acknowledged_completion_status
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_id, user_id)) # Added user_id to query
        row = cursor.fetchone()
        if row:
            game_dict = dict(row)
            
            # Determine if acknowledgement is needed BEFORE formatting rss_pub_date for display
            needs_ack = False
            if game_dict.get('version') != game_dict.get('user_acknowledged_version'):
                needs_ack = True
            
            if not needs_ack and game_dict.get('rss_pub_date') != game_dict.get('user_acknowledged_rss_pub_date'):
                needs_ack = True
            
            if not needs_ack and game_dict.get('completed_status') != game_dict.get('user_acknowledged_completion_status'):
                needs_ack = True
            game_dict['needs_acknowledgement_flag'] = needs_ack

            # Add logging for the outcome of needs_ack in get_my_played_game_details as well
            # logger.info(f"ACK_INFO_DETAILS (GameID: {game_dict.get('game_db_id')}, PlayedID: {game_dict.get('played_game_id')}) - Final needs_ack: {needs_ack}") # REMOVE

            raw_pub_date_str = game_dict.get('rss_pub_date')
            if raw_pub_date_str and isinstance(raw_pub_date_str, str) and raw_pub_date_str.strip():
                dt_obj = None
                try:
                    iso_format_str = raw_pub_date_str
                    if iso_format_str.endswith('Z'):
                        iso_format_str = iso_format_str[:-1] + '+00:00'
                    dt_obj = datetime.fromisoformat(iso_format_str)
                except ValueError: # If fromisoformat fails, try parsedate_to_datetime as a fallback
                    try:
                        dt_obj = parsedate_to_datetime(raw_pub_date_str)
                    except Exception as e_fallback_details:
                        logger.debug(f"Fallback parsedate_to_datetime also failed for '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')} (details): {e_fallback_details}")
                        dt_obj = None # Ensure None on fallback failure
                except Exception as e_main_parse_details:
                    logger.warning(f"Initial date parsing failed for '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')} (details) due to: {e_main_parse_details}")
                    dt_obj = None

                if dt_obj: 
                    if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
                        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                    else:
                        dt_obj = dt_obj.astimezone(timezone.utc)
                    game_dict['rss_pub_date'] = dt_obj.strftime('%a, %d %b %Y %H:%M') + ' UTC'
                else:
                    logger.warning(f"All parsing attempts failed for date string '{raw_pub_date_str}' in game {game_dict.get('name', 'Unknown')} (details). Setting to 'Invalid Date'.")
                    game_dict['rss_pub_date'] = 'Invalid Date'
            elif not raw_pub_date_str or not raw_pub_date_str.strip():
                game_dict['rss_pub_date'] = 'N/A'
            else:
                game_dict['rss_pub_date'] = 'N/A'
            logger.info(f"Details found for played game ID: {played_game_id} (user_id: {user_id}) - {game_dict['name']}")
            return game_dict
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id} for user_id: {user_id}")
            return None
    except sqlite3.Error as e:
        logger.error(f"Database error in get_my_played_game_details for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_my_played_game_details for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def update_my_played_game_details(db_path: str, user_id: int, played_game_id: int, # Added user_id
                                  user_notes: str = None, user_rating: float = None, 
                                  notify_for_updates: bool = None) -> dict:
    """
    Updates details for a specific game in the user's played list.
    Only updates fields that are provided (not None).
    'played_game_id' is the ID from the user_played_games table, constrained by user_id.
    """
    logger.info(f"Attempting to update details for played game ID: {played_game_id} for user_id: {user_id}")
    if not any([user_notes is not None, user_rating is not None, notify_for_updates is not None]):
        return {'success': False, 'message': "No update parameters provided."}

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        set_clauses = []
        params = []
        
        if user_notes is not None:
            set_clauses.append("user_notes = ?")
            params.append(user_notes)
        if user_rating is not None:
            set_clauses.append("user_rating = ?")
            params.append(user_rating)
        if notify_for_updates is not None:
            set_clauses.append("notify_for_updates = ?")
            params.append(notify_for_updates)
        
        if not set_clauses: # Should be caught by the check above, but as a safeguard
            return {'success': False, 'message': "No valid update fields provided."}

        params.append(played_game_id)
        params.append(user_id) # Add user_id to params for WHERE clause
        
        sql = f"UPDATE user_played_games SET {', '.join(set_clauses)} WHERE id = ? AND user_id = ?" # Add user_id to WHERE
        
        cursor.execute(sql, tuple(params))
        updated_rows = cursor.rowcount
        conn.commit()

        if updated_rows > 0:
            logger.info(f"Successfully updated details for played game ID: {played_game_id}, user_id: {user_id}")
            return {'success': True, 'message': "Game details updated successfully."}
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id} for user_id: {user_id} to update.")
            return {'success': False, 'message': "No game found with that ID in your played list."}

    except sqlite3.Error as e:
        logger.error(f"Database error in update_my_played_game_details for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
        return {'success': False, 'message': f"Database error: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error in update_my_played_game_details for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
        return {'success': False, 'message': f"Unexpected error: {e}"}
    finally:
        if conn:
            conn.close()

def delete_game_from_my_list(db_path: str, user_id: int, played_game_id: int) -> tuple[bool, str]: # Added user_id
    """
    Deletes a game from the user's played list based on the user_played_games.id.
    Does not delete from the main 'games' table. Constrained by user_id.
    """
    logger.info(f"Attempting to delete played game ID: {played_game_id} from user's (user_id: {user_id}) list.")
    conn = None
    game_name_for_notification = "Unknown Game"
    game_url_for_notification = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get game name and URL for message before deleting
        cursor.execute("""
            SELECT g.name, g.f95_url 
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_id, user_id)) # Added user_id to query
        game_info = cursor.fetchone()
        if game_info:
            game_name_for_notification = game_info[0]
            game_url_for_notification = game_info[1]
        else:
            game_name_for_notification = "Unknown Game (ID: " + str(played_game_id) + ")"

        cursor.execute("DELETE FROM user_played_games WHERE id = ? AND user_id = ?", (played_game_id, user_id)) # Added user_id
        deleted_rows = cursor.rowcount
        conn.commit()

        if deleted_rows > 0:
            logger.info(f"Successfully deleted played game ID: {played_game_id} ('{game_name_for_notification}') from user's (user_id: {user_id}) list.")
            # Send Pushover notification for game delete
            if get_setting(db_path, 'notify_on_game_delete', 'False', user_id=user_id) == 'True': # Pass user_id
                send_pushover_notification(
                    db_path,
                    user_id=user_id, # Pass user_id
                    title=f"Game Removed: {game_name_for_notification}",
                    message=f"'{game_name_for_notification}' was removed from your monitored list.",
                    url=game_url_for_notification,
                    url_title=f"View {game_name_for_notification} on F95Zone" if game_url_for_notification else None
                )
            return True, f"Game '{game_name_for_notification}' removed from your list."
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id} for user_id: {user_id} to delete from user's list.")
            return False, "No game found with that ID in your list to delete."

    except sqlite3.Error as e:
        logger.error(f"Database error deleting played game ID {played_game_id} for user_id {user_id}: {e}", exc_info=True)
        return False, f"Database error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error deleting played game ID {played_game_id} for user_id {user_id}: {e}", exc_info=True)
        return False, f"An unexpected error occurred: {e}"
    finally:
        if conn:
            conn.close()

def mark_game_as_acknowledged(db_path: str, user_id: int, played_game_id: int) -> tuple[bool, str, Optional[dict]]: # Added user_id
    """
    Marks a game associated with a user_played_games entry as acknowledged by the user.
    Updates the user_acknowledged_version, _rss_pub_date, and _completed_status
    in the user_played_games table to the current values from the games table for that game.
    Constrained by user_id.
    """
    logger.info(f"Attempting to mark updates as acknowledged for played game ID: {played_game_id} for user_id: {user_id}.")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # DEBUG: Check table info right before the problematic UPDATE
        try:
            # print(f"DEBUG_MARK_ACK: Checking table_info for user_played_games just before UPDATE for played_game_id: {played_game_id}", file=sys.stderr) # REMOVE
            cursor.execute("PRAGMA table_info(user_played_games)")
            columns_in_mark_ack = [column_info[1] for column_info in cursor.fetchall()]
            # print(f"DEBUG_MARK_ACK: Columns in user_played_games (from mark_game_as_acknowledged): {columns_in_mark_ack}", file=sys.stderr) # REMOVE
            if 'user_acknowledged_completion_status' not in columns_in_mark_ack:
                # print("DEBUG_MARK_ACK: CRITICAL - user_acknowledged_completion_status IS MISSING right before UPDATE!", file=sys.stderr) # REMOVE
                logger.error("CRITICAL - user_acknowledged_completion_status IS MISSING right before UPDATE in mark_game_as_acknowledged!")
            else:
                # print("DEBUG_MARK_ACK: user_acknowledged_completion_status IS PRESENT right before UPDATE.", file=sys.stderr) # REMOVE
                pass
        except Exception as e_pragma:
            # print(f"DEBUG_MARK_ACK: Error doing PRAGMA check: {e_pragma}", file=sys.stderr) # REMOVE
            logger.error(f"Error doing PRAGMA table_info check in mark_game_as_acknowledged: {e_pragma}")

        # Step 1: Get the game_id from user_played_games, ensuring it belongs to the user
        cursor.execute("SELECT game_id FROM user_played_games WHERE id = ? AND user_id = ?", (played_game_id, user_id)) # Added user_id
        played_game_row = cursor.fetchone()
        if not played_game_row:
            logger.warning(f"No played game entry found for played_game_id: {played_game_id} and user_id: {user_id}.")
            return False, "Game not found in your list.", None
        
        game_id_from_games_table = played_game_row[0]

        # Step 2: Get current details from the 'games' table
        cursor.execute("SELECT name, version, rss_pub_date, completed_status FROM games WHERE id = ?", (game_id_from_games_table,))
        game_details_row = cursor.fetchone()
        if not game_details_row:
            logger.error(f"Could not find game details in 'games' table for game_id: {game_id_from_games_table} (linked from played_game_id: {played_game_id}).")
            return False, "Could not retrieve current game details to acknowledge.", None

        game_name, current_version, current_rss_pub_date, current_completed_status = game_details_row
        
        # Step 3: Update user_played_games (This is where the error occurs)
        # Re-typing the column name carefully.
        sql_update_query = """
            UPDATE user_played_games
            SET user_acknowledged_version = ?,
                user_acknowledged_rss_pub_date = ?,
                user_acknowledged_completion_status = ? 
            WHERE id = ? AND user_id = ?
        """
        params_for_update = (current_version, current_rss_pub_date, current_completed_status, played_game_id, user_id)
        
        # logger.debug(f"Executing SQL: {sql_update_query} with params: {params_for_update}") # COMMENTED OUT - too verbose for INFO
        cursor.execute(sql_update_query, params_for_update)
        
        updated_rows = cursor.rowcount
        conn.commit() # Commit the changes

        if updated_rows > 0:
            # --- START POST-COMMIT VERIFICATION LOGGING ---
            try:
                cursor.execute("""
                    SELECT user_acknowledged_version, user_acknowledged_rss_pub_date, user_acknowledged_completion_status
                    FROM user_played_games
                    WHERE id = ? AND user_id = ?
                """, (played_game_id, user_id))
                refetched_row = cursor.fetchone()
                # if refetched_row: # REMOVE BLOCK
                #     logger.info(f"POST_ACK_VERIFY (PlayedID: {played_game_id}): Refetched user_acknowledged_version: '{refetched_row['user_acknowledged_version']}'")
                #     logger.info(f"POST_ACK_VERIFY (PlayedID: {played_game_id}): Refetched user_acknowledged_rss_pub_date: '{refetched_row['user_acknowledged_rss_pub_date']}'")
                #     logger.info(f"POST_ACK_VERIFY (PlayedID: {played_game_id}): Refetched user_acknowledged_completion_status: '{refetched_row['user_acknowledged_completion_status']}'")
                # else:
                #     logger.error(f"POST_ACK_VERIFY (PlayedID: {played_game_id}): Failed to re-fetch row after update.")
            except Exception as e_verify:
                logger.error(f"POST_ACK_VERIFY (PlayedID: {played_game_id}): Error during post-commit verification: {e_verify}")
            # --- END POST-COMMIT VERIFICATION LOGGING ---

            logger.info(f"Successfully marked updates as acknowledged for played game ID: {played_game_id} ('{game_name}') for user_id: {user_id}.")
            acknowledged_details = {
                "version": current_version,
                "rss_pub_date": current_rss_pub_date,
                "completed_status": current_completed_status
            }
            return True, f"Updates for '{game_name}' marked as acknowledged.", acknowledged_details
        else:
            # This case should be rare if the initial select for played_game_id succeeded
            logger.warning(f"Failed to update acknowledged status for played_game_id: {played_game_id}, user_id: {user_id} (rowcount 0).")
            return False, "Failed to update acknowledged status.", None

    except sqlite3.Error as e:
        logger.error(f"Database error marking game acknowledged (ID {played_game_id}, user_id {user_id}): {e}", exc_info=True)
        return False, f"Database error: {e}", None
    except Exception as e:
        logger.error(f"Unexpected error marking game acknowledged (ID {played_game_id}, user_id {user_id}): {e}", exc_info=True)
        return False, f"An unexpected error occurred: {e}", None
    finally:
        if conn:
            conn.close()

def update_completion_statuses(db_path: str, client: F95ApiClient):
    """
    Updates the 'completed_status' for games in the database.
    It fetches a list of recently completed games once.
    Then, for each local game not marked 'COMPLETED', it checks against this list.
    If found, status becomes 'COMPLETED'.
    If not found and status was 'UNKNOWN', it becomes 'ONGOING'.
    """
    logger.info("Starting update of game completion statuses using new optimized method...")
    conn = None
    games_updated_count = 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Step 1: Fetch a list of recently completed games ONCE
        logger.info(f"Fetching up to {MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK} recently completed games from RSS feed...")
        all_completed_games_rss = client.get_latest_game_data_from_rss(
            limit=MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK,
            completion_status_filter="completed"
        )

        if all_completed_games_rss is None: # client.get_latest_game_data_from_rss might return None on error
            logger.error("Failed to fetch the list of completed games from RSS. Aborting completion status update.")
            return

        completed_game_urls = {item.get('url') for item in all_completed_games_rss if item.get('url')}
        logger.info(f"Fetched {len(all_completed_games_rss)} items from the completed games RSS feed, resulting in {len(completed_game_urls)} unique URLs.")

        if not completed_game_urls:
            logger.info("No completed games found in the RSS feed, or all items lacked URLs. No statuses will be changed to COMPLETED based on this fetch.")
            # We can still proceed to potentially update UNKNOWN to ONGOING for local games

        # Step 2: Get all games from local DB that are not already marked as COMPLETED
        cursor.execute("SELECT id, f95_url, name, completed_status FROM games WHERE completed_status IS NULL OR completed_status != 'COMPLETED'")
        games_to_check = cursor.fetchall()

        if not games_to_check:
            logger.info("No games found in local DB that require completion status checking.")
            return

        logger.info(f"Found {len(games_to_check)} games in local DB to check against the fetched completed games list.")

        for game_id, game_url, game_name, db_completed_status in games_to_check:
            # Removed time.sleep(3) - no longer making per-game requests
            logger.debug(f"Processing completion status for: '{game_name}' (ID: {game_id}), current DB status: {db_completed_status}")
            
            new_status = db_completed_status # Assume no change initially
            
            if game_url in completed_game_urls:
                new_status = 'COMPLETED'
                logger.info(f"  MATCH FOUND: Game '{game_name}' (URL: {game_url}) is in the fetched completed games list. Setting status to COMPLETED.")
            elif db_completed_status == 'UNKNOWN':
                # If not found in the "completed" list and its status was UNKNOWN, set to ONGOING.
                new_status = 'ONGOING'
                logger.info(f"  Game '{game_name}' (URL: {game_url}) not in completed list and was UNKNOWN. Setting status to ONGOING.")
            
            # Update database only if the status has actually changed
            if new_status != db_completed_status:
                cursor.execute("UPDATE games SET completed_status = ?, last_updated_in_db = ? WHERE id = ?", 
                               (new_status, datetime.now(timezone.utc).isoformat(), game_id))
                conn.commit()
                games_updated_count += 1
                logger.info(f"  Status for '{game_name}' (ID: {game_id}) updated to {new_status} (was {db_completed_status}).")
            else:
                logger.debug(f"  Completion status for '{game_name}' (ID: {game_id}) remains '{db_completed_status}'. No update needed.")

        if games_updated_count > 0:
            logger.info(f"Finished completion status update. {games_updated_count} games had their status changed.")
        else:
            logger.info("Finished completion status update. No game statuses were changed based on the completed games feed.")

    except sqlite3.Error as e:
        logger.error(f"Database error during completion status update: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error during completion status update: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def check_for_my_updates(db_path: str, user_id: int) -> list[dict]: # Added user_id
    """
    Checks for updates for games in the specified user's played list that are marked for notification.
    Identifies version changes, RSS pub date changes, or significant completion status changes.
    Returns a list of notification objects (dictionaries).
    This function DOES NOT update the 'last_notified' fields in the database.
    """
    logger.info(f"Checking for updates in user's (user_id: {user_id}) played games list...")
    notifications = []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                upg.id AS played_game_id, 
                upg.game_id, 
                g.name AS game_name,
                g.f95_url AS game_url,
                g.version AS current_version,
                g.rss_pub_date AS current_rss_pub_date,
                g.completed_status AS current_completed_status,
                upg.last_notified_version,
                upg.last_notified_rss_pub_date,
                upg.last_notified_completion_status
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.notify_for_updates = TRUE AND upg.user_id = ? 
        """, (user_id,)) # Added user_id to query
        games_to_notify = cursor.fetchall()
        logger.info(f"Found {len(games_to_notify)} games in played list for user_id {user_id} marked for notifications.")

        for game in games_to_notify:
            notification_reasons = []
            is_newly_completed = False

            # Log values being compared
            logger.debug(f"Checking game for notification: {game['game_name']} (PlayedID: {game['played_game_id']}, UserID: {user_id})")
            logger.debug(f"  Current Version: '{game['current_version']}', Last Notified Version: '{game['last_notified_version']}'")
            logger.debug(f"  Current RSS Date: '{game['current_rss_pub_date']}', Last Notified RSS Date: '{game['last_notified_rss_pub_date']}'")
            logger.debug(f"  Current Status: '{game['current_completed_status']}', Last Notified Status: '{game['last_notified_completion_status']}'")

            # Check for version update
            # Only notify if there was a previous version and it's different
            if (game['last_notified_version'] is not None and
                game['last_notified_version'] != '' and
                game['current_version'] is not None and
                game['current_version'] != game['last_notified_version']):
                notification_reasons.append(
                    f"Version updated: {game['last_notified_version']} -> {game['current_version']}"
                )
            
            # Check for RSS pub date update
            # Only notify if there was a previous RSS date, it's different, and no version update was already noted
            if (not notification_reasons and
                game['last_notified_rss_pub_date'] is not None and
                game['last_notified_rss_pub_date'] != '' and
                game['current_rss_pub_date'] is not None and
                game['current_rss_pub_date'] != game['last_notified_rss_pub_date']):
                notification_reasons.append(
                    f"RSS publication date updated: {game['last_notified_rss_pub_date']} -> {game['current_rss_pub_date']}"
                )

            # Check for completion status change to COMPLETED
            # Only notify if previous status was known (not None/empty) and was not 'COMPLETED' already
            if (game['last_notified_completion_status'] is not None and
                game['last_notified_completion_status'] != '' and
                game['current_completed_status'] == 'COMPLETED' and
                game['last_notified_completion_status'] != 'COMPLETED'):
                notification_reasons.append("Game has been marked as COMPLETED!")
                is_newly_completed = True
            
            # Future: Check for other status changes (ON_HOLD, ABANDONED)
            # elif game['current_completed_status'] == 'ON_HOLD' and game['last_notified_completed_status'] != 'ON_HOLD':
            #     notification_reasons.append("Game status changed to ON HOLD.")
            # elif game['current_completed_status'] == 'ABANDONED' and game['last_notified_completed_status'] != 'ABANDONED':
            #     notification_reasons.append("Game status changed to ABANDONED.")

            if not notification_reasons:
                logger.debug(f"  No notification reasons identified for {game['game_name']} (PlayedID: {game['played_game_id']}).")

            if notification_reasons:
                notifications.append({
                    'played_game_id': game['played_game_id'],
                    'game_name': game['game_name'],
                    'game_url': game['game_url'],
                    'current_version': game['current_version'],
                    'current_completed_status': game['current_completed_status'],
                    'is_newly_completed': is_newly_completed, 
                    'reasons': notification_reasons,
                    # Fields needed to update the user_played_games table after notification
                    'new_notified_version': game['current_version'], 
                    'new_notified_rss_pub_date': game['current_rss_pub_date'],
                    'new_notified_completed_status': game['current_completed_status']
                })
        
        logger.info(f"Found {len(notifications)} potential notifications.")

    except sqlite3.Error as e:
        logger.error(f"Database error in check_for_my_updates: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in check_for_my_updates: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return notifications

def update_last_notified_status(db_path: str, user_id: int, played_game_id: int, version: str, rss_pub_date: str, completed_status: str): # Added user_id
    """
    Updates the last_notified fields for a game in the user_played_games table.
    This should be called AFTER a notification has been successfully sent/processed.
    Constrained by user_id.
    """
    logger.info(f"Updating last notified status for played game ID: {played_game_id} for user_id: {user_id}")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # DEBUG: Check table info right before the problematic UPDATE
        try:
            # print(f"DEBUG_UPDATE_NOTIFIED: Checking table_info for user_played_games just before UPDATE for played_game_id: {played_game_id}", file=sys.stderr) # REMOVE
            cursor.execute("PRAGMA table_info(user_played_games)")
            columns_in_update_notified = [column_info[1] for column_info in cursor.fetchall()]
            # print(f"DEBUG_UPDATE_NOTIFIED: Columns in user_played_games (from update_last_notified_status): {columns_in_update_notified}", file=sys.stderr) # REMOVE
            if 'last_notified_completion_status' not in columns_in_update_notified:
                # print("DEBUG_UPDATE_NOTIFIED: CRITICAL - last_notified_completion_status IS MISSING right before UPDATE!", file=sys.stderr) # REMOVE
                logger.error("CRITICAL - last_notified_completion_status IS MISSING right before UPDATE in update_last_notified_status!")
            else:
                # print("DEBUG_UPDATE_NOTIFIED: 'last_notified_completion_status' IS PRESENT right before UPDATE.", file=sys.stderr) # REMOVE
                pass
        except Exception as e_pragma_un:
            # print(f"DEBUG_UPDATE_NOTIFIED: Error doing PRAGMA check: {e_pragma_un}", file=sys.stderr) # REMOVE
            logger.error(f"Error doing PRAGMA table_info check in update_last_notified_status: {e_pragma_un}")

        # Correcting the column name in the SQL query.
        sql_update_query = """ 
            UPDATE user_played_games 
            SET last_notified_version = ?, 
                last_notified_rss_pub_date = ?, 
                last_notified_completion_status = ?  -- Corrected column name
            WHERE id = ? AND user_id = ?
        """
        params_for_update = (version, rss_pub_date, completed_status, played_game_id, user_id)
        
        # logger.debug(f"Executing SQL in update_last_notified_status: {sql_update_query} with params: {params_for_update}") # COMMENTED OUT - too verbose for INFO
        cursor.execute(sql_update_query, params_for_update)
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Successfully updated last_notified status for played_game_id {played_game_id}, user_id {user_id}.")
        else:
            logger.warning(f"No row found to update last_notified status for played_game_id {played_game_id}, user_id {user_id}.")
    except sqlite3.Error as e:
        logger.error(f"Database error in update_last_notified_status for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in update_last_notified_status for ID {played_game_id}, user_id {user_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Text Processing Helper ---
_STOP_WORDS = set([
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "can", "could", "may", "might", "must", "and", "but", "or", "nor",
    "for", "so", "yet", "of", "in", "on", "at", "by", "from", "to", "with",
    "about", "above", "after", "again", "against", "all", "am", "as",
    "because", "before", "below", "between", "both", "during", "each",
    "few", "further", "here", "how", "if", "into", "it", "its", "itself",
    "just", "me", "more", "most", "my", "myself", "no", "not", "now",
    "once", "only", "other", "our", "ours", "ourselves", "out", "over",
    "own", "same", "she", "he", "him", "her", "some", "still", "such", "than", 
    "that", "their", "theirs", "them", "themselves", "then", "there", "these", 
    "they", "this", "those", "through", "too", "under", "until", "up", "very", 
    "we", "what", "when", "where", "which", "while", "who", "whom", "why", 
    "won", "you", "your", "yours", "yourself", "yourselves",
    # Common game prefixes/suffixes that might not be useful as sole search terms
    "chapter", "episode", "book", "part", "vol", "edition", "remake", "remaster",
    "update", "new", "game", "mod" 
])

def get_first_significant_word(name_str: str) -> str:
    logger.debug(f"get_first_significant_word: Received original name_str: '{name_str}'")
    if not name_str:
        logger.debug("get_first_significant_word: name_str is empty, returning empty string.")
        return ""

    # Remove content in brackets (like version, status, or author)
    name_str_cleaned_brackets = re.sub(r'\s*\[.*?\]\s*', ' ', name_str).strip()
    name_str_cleaned_parentheses = re.sub(r'\s*\(.*?\)\s*', ' ', name_str_cleaned_brackets).strip()
    logger.debug(f"get_first_significant_word: After bracket/parenthesis removal: '{name_str_cleaned_parentheses}'")

    # Specifically remove possessive 's
    name_str_cleaned_possessive = re.sub(r"\'s\b", "", name_str_cleaned_parentheses, flags=re.IGNORECASE).strip()
    logger.debug(f"get_first_significant_word: After possessive \'s removal: '{name_str_cleaned_possessive}'")

    # Remove common punctuation that might stick to words or be standalone
    # Keep alphanumeric, spaces, and hyphens if they are part of a word
    name_str_final_cleaned = re.sub(r'[^\w\s-]', '', name_str_cleaned_possessive)
    logger.debug(f"get_first_significant_word: After punctuation removal: '{name_str_final_cleaned}'")
    
    words = name_str_final_cleaned.split()
    logger.debug(f"get_first_significant_word: Split into words: {words}")

    for word in words:
        # Further clean individual words: remove leading/trailing hyphens not part of word
        cleaned_word = word.strip('-')
        logger.debug(f"get_first_significant_word: Checking cleaned_word: '{cleaned_word}'")
        if cleaned_word.lower() not in _STOP_WORDS and len(cleaned_word) > 2: # Ensure word is reasonably long
            logger.debug(f"get_first_significant_word: Found significant word: '{cleaned_word}'")
            return cleaned_word # Return the cleaned word
    
    # Fallback: if all words are stop words or too short, try the first word if it exists and is not tiny
    if words:
        first_word_cleaned = words[0].strip('-')
        logger.debug(f"get_first_significant_word: Fallback - checking first_word_cleaned: '{first_word_cleaned}'")
        if len(first_word_cleaned) > 1 : # Avoid single characters as search terms
            logger.debug(f"get_first_significant_word: Using fallback first word: '{first_word_cleaned}'")
            return first_word_cleaned
            
    logger.warning(f"get_first_significant_word: No significant word found for original name '{name_str}'. Returning empty string.")
    return "" # Absolute fallback

# --- Scheduled Update Functions ---

def _determine_specific_game_status(f95_client: F95ApiClient, game_url: str, game_name: str, target_status_prefix: str) -> Optional[str]:
    """
    Checks if a game is listed in a feed with a specific status prefix.
    target_status_prefix: e.g., "completed", "abandoned", "on_hold"
    Returns target_status_prefix.upper() if found, else None.
    """
    search_term = get_first_significant_word(game_name)
    if not search_term:
        logger.warning(f"Cannot determine specific status for '{game_name}' (URL: {game_url}) due to no significant search term.")
        return None

    logger.info(f"Checking for status '{target_status_prefix}' for game '{game_name}' (URL: {game_url}) using search term '{search_term}'")

    try:
        data = f95_client.get_latest_game_data_from_rss(
            search_term=search_term,
            completion_status_filter=target_status_prefix, # This should be 'completed', 'on_hold', etc.
            limit=MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK 
        )
        if data:
            for item in data:
                if item.get('url') == game_url:
                    logger.info(f"Game '{game_name}' found in '{target_status_prefix}' feed. Confirming status as {target_status_prefix.upper()}.")
                    return target_status_prefix.upper()
        
        logger.info(f"Game '{game_name}' not found in '{target_status_prefix}' feed with search term '{search_term}'.")
        return None
    except Exception as e:
        logger.error(f"Error checking status '{target_status_prefix}' for game '{game_name}': {e}", exc_info=True)
        return None

def check_single_game_update_and_status(db_path: str, f95_client: F95ApiClient, played_game_row_id: int, user_id: int): # Added user_id
    """
    Checks a single game for updates (version, RSS date) and then for status changes
    (COMPLETED, ABANDONED, ON-HOLD) based on the logic requested.
    Updates the 'games' table accordingly.
    Sends Pushover notifications based on settings for the specified user.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Access columns by name
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT g.id, g.name, g.version, g.author, g.image_url, g.rss_pub_date, g.completed_status, g.f95_url as url, 
                   upg.id as user_played_game_id, upg.user_id
            FROM games g
            JOIN user_played_games upg ON g.id = upg.game_id
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_row_id, user_id)) # Added user_id to query
        game_data = cursor.fetchone()

        if not game_data:
            logger.warning(f"SCHEDULER: No game data found for user_played_games.id {played_game_row_id} and user_id {user_id}. Skipping.")
            return

        game_id = game_data['id']
        current_name = game_data['name']
        current_version = game_data['version']
        current_rss_pub_date_str = game_data['rss_pub_date']
        current_status = game_data['completed_status']
        game_url = game_data['url']
        
        # Ensure the user_id from fetched game_data matches the passed user_id, as a sanity check.
        # This should always be true due to the WHERE clause.
        if game_data['user_id'] != user_id:
            logger.error(f"SCHEDULER/SYNC: Mismatch user_id for game '{current_name}'. Expected {user_id}, got {game_data['user_id']}. Aborting for this game.")
            return

        original_name_for_notification = current_name # Store before potential update
        original_version_for_notification = current_version
        original_status_for_notification = current_status
        log_name_for_notification = current_name # Store for logging consistency

        logger.info(f"SCHEDULER/SYNC (User: {user_id}): Checking '{current_name}' (GameID: {game_id}, PlayedID: {played_game_row_id}, URL: {game_url})")
        
        search_term = get_first_significant_word(current_name)
        if not search_term:
            logger.warning(f"SCHEDULER: No significant search term for '{current_name}'. General update check might be unreliable.")
            # Fallback: use full name if get_first_significant_word returns empty
            search_term_for_rss = current_name 
        else:
            search_term_for_rss = search_term
        
        latest_data_items = None
        # Perform the initial "ongoing" search (noprefixes for C/A/OH implicitly by F95ApiClient)
        # We use completion_status_filter='ongoing' to be explicit about wanting the general/up-to-date items
        # that are not specifically completed, on-hold or abandoned.
        logger.info(f"SCHEDULER/SYNC (User: {user_id}): Performing initial 'ongoing' check for '{current_name}' using search term '{search_term_for_rss}'")
        latest_data_items = f95_client.get_latest_game_data_from_rss(
            search_term=search_term_for_rss, 
            limit=10, # Small limit for this check
            completion_status_filter='ongoing' # Ensures we get latest, not specific C/A/OH items
        )

        found_game_in_initial_ongoing_check = False
        found_game_update_data = None # This will store the matched item from initial check

        if latest_data_items:
            for item in latest_data_items:
                if item.get('url') == game_url:
                    found_game_update_data = item
                    found_game_in_initial_ongoing_check = True
                    # Single log for this event
                    logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{current_name}' FOUND in initial 'ongoing' check.")
                    break
        
        if not found_game_in_initial_ongoing_check:
            logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{current_name}' NOT FOUND in initial 'ongoing' check with search term '{search_term_for_rss}'. Will proceed to specific status checks.")

        has_primary_update = False # For version/date changes
        name_changed, version_changed, date_changed, author_changed, image_changed = False, False, False, False, False # Initialize all here
        new_name, new_version, new_author, new_image_url = None, None, None, None
        new_rss_pub_date_str = None
        new_rss_pub_date_dt = None # Initialize to None

        if found_game_update_data: # Process if found in initial 'ongoing' check
            new_name = found_game_update_data.get('name')
            new_version = found_game_update_data.get('version')
            new_author = found_game_update_data.get('author')
            new_image_url = found_game_update_data.get('image_url')
            new_rss_pub_date_str = found_game_update_data.get('rss_pub_date')

            # Robust date parsing for new_rss_pub_date_str
            if new_rss_pub_date_str and isinstance(new_rss_pub_date_str, str):
                parsed_dt = None # Initialize parsed_dt
                try:
                    # Remove 'Z' if present and ensure '+00:00' for fromisoformat
                    iso_date_str = new_rss_pub_date_str
                    if iso_date_str.endswith('Z'):
                        iso_date_str = iso_date_str[:-1] + '+00:00'
                    
                    parsed_dt = datetime.fromisoformat(iso_date_str)
                except ValueError:
                    try:
                        parsed_dt = parsedate_to_datetime(new_rss_pub_date_str)
                    except (TypeError, ValueError) as e_parse_new_fallback:
                        logger.warning(f"SCHEDULER/SYNC (User: {user_id}): Could not parse new_rss_pub_date_str (fallback) '{new_rss_pub_date_str}' for {log_name_for_notification}: {e_parse_new_fallback}")
                        parsed_dt = None # Ensure None on fallback failure
                except Exception as e_parse_new_main: # Catch any other unexpected error from fromisoformat
                    logger.warning(f"SCHEDULER/SYNC (User: {user_id}): Could not parse new_rss_pub_date_str (main) '{new_rss_pub_date_str}' for {log_name_for_notification}: {e_parse_new_main}")
                    parsed_dt = None # Ensure None on main parse failure

                if parsed_dt: # Check if parsed_dt is not None
                    if parsed_dt.tzinfo is None or parsed_dt.tzinfo.utcoffset(parsed_dt) is None:
                        new_rss_pub_date_dt = parsed_dt.replace(tzinfo=timezone.utc)
                    else:
                        new_rss_pub_date_dt = parsed_dt.astimezone(timezone.utc)
            
            # Robust date parsing for current_rss_pub_date_str (from DB)
            current_rss_pub_date_dt = None
            if current_rss_pub_date_str and isinstance(current_rss_pub_date_str, str):
                parsed_db_dt = None # Initialize parsed_db_dt
                try:
                    iso_db_date_str = current_rss_pub_date_str
                    if iso_db_date_str.endswith('Z'):
                        iso_db_date_str = iso_db_date_str[:-1] + '+00:00'
                    
                    parsed_db_dt = datetime.fromisoformat(iso_db_date_str)
                except ValueError:
                    try:
                        parsed_db_dt = parsedate_to_datetime(current_rss_pub_date_str)
                    except (TypeError, ValueError) as e_parse_db_fallback:
                         logger.warning(f"SCHEDULER/SYNC (User: {user_id}): Could not parse current_rss_pub_date_str (from DB fallback) '{current_rss_pub_date_str}' for {log_name_for_notification}: {e_parse_db_fallback}")
                         parsed_db_dt = None # Ensure None on fallback failure
                except Exception as e_parse_db_main: # Catch any other unexpected error from fromisoformat
                    logger.warning(f"SCHEDULER/SYNC (User: {user_id}): Could not parse current_rss_pub_date_str (from DB main) '{current_rss_pub_date_str}' for {log_name_for_notification}: {e_parse_db_main}")
                    parsed_db_dt = None # Ensure None on main parse failure

                if parsed_db_dt: # Check if parsed_db_dt is not None
                    if parsed_db_dt.tzinfo is None or parsed_db_dt.tzinfo.utcoffset(parsed_db_dt) is None:
                        current_rss_pub_date_dt = parsed_db_dt.replace(tzinfo=timezone.utc)
                    else:
                        current_rss_pub_date_dt = parsed_db_dt.astimezone(timezone.utc)

            name_changed = bool(new_name and new_name != current_name)
            version_changed = bool(new_version and current_version and new_version.lower() != current_version.lower())
            
            if new_rss_pub_date_dt and current_rss_pub_date_dt:
                if new_rss_pub_date_dt > current_rss_pub_date_dt:
                    date_changed = True
            elif new_rss_pub_date_dt and not current_rss_pub_date_dt:
                date_changed = True
            # Ensure author_changed and image_changed are based on whether new values are present and different
            author_changed = bool(new_author and new_author != game_data['author'])
            image_changed = bool(new_image_url and new_image_url != game_data['image_url'])

            if name_changed or version_changed or date_changed or author_changed or image_changed:
                has_primary_update = True
            
            # If game was found in the initial "ongoing" check, its status should be considered ONGOING
            # unless it was already COMPLETED/ABANDONED/ON_HOLD (which "ongoing" feed should exclude).
            # If it was UNKNOWN, it now becomes ONGOING.
            if current_status == "UNKNOWN":
                current_status = "ONGOING" 
                logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{current_name}' was UNKNOWN and found in 'ongoing' check. Setting status to ONGOING.")
            elif current_status != "COMPLETED" and current_status != "ABANDONED" and current_status != "ON_HOLD":
                current_status = "ONGOING"
                # Removed a redundant log here, the one above covers the "found and set to ongoing" case.
                # If it was already ongoing, no need to log "set to ongoing" again.

        # --- Status Determination and DB Update Block ---
        update_fields = {}
        pushover_message_parts = []
        is_newly_completed_for_notification = False # Initialize this flag

        # Populate update_fields based on primary data changes (name, version, date, etc.)
        # This part is fine and should run if found_game_update_data exists.
        if name_changed:
            update_fields['name'] = new_name
            pushover_message_parts.append(f"Name: {original_name_for_notification} -> {new_name}")
        if version_changed:
            update_fields['version'] = new_version
            pushover_message_parts.append(f"Version: {original_version_for_notification} -> {new_version}")
        if date_changed and new_rss_pub_date_dt: # Ensure new_rss_pub_date_dt is not None
            update_fields['rss_pub_date'] = new_rss_pub_date_dt.isoformat()
            pushover_message_parts.append(f"RSS Date Updated")
        if author_changed: # Check if new_author has a value
            update_fields['author'] = new_author
            pushover_message_parts.append(f"Author updated: {new_author}") # Simplified message
        if image_changed: # Check if new_image_url has a value
            update_fields['image_url'] = new_image_url
            pushover_message_parts.append(f"Image URL updated") # Simplified message
        
        # Store the status determined from the initial 'ongoing' check if the game was found there.
        # This status will be compared against original_status_for_notification later.
        status_after_ongoing_check = current_status if found_game_in_initial_ongoing_check else original_status_for_notification

        # --- Specific Status Checks (COMPLETED, ABANDONED, ON_HOLD) ---
        # This entire block should ONLY run if the game was NOT found in the initial 'ongoing' check.
        if not found_game_in_initial_ongoing_check:
            logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{current_name}' not found in initial ongoing check. Proceeding to specific status (C/A/OH) checks.")
            status_priority_checks = [
                ("COMPLETED", "completed"),
                ("ABANDONED", "abandoned"),
                ("ON_HOLD", "on_hold")
            ]
            
            new_determined_status_specific = None
            for status_name, status_filter_key in status_priority_checks:
                logger.info(f"SCHEDULER/SYNC (User: {user_id}): Checking specific status '{status_name}' for game '{log_name_for_notification}' (ID: {game_id})")
                if _determine_specific_game_status(f95_client, game_url, log_name_for_notification, status_filter_key):
                    new_determined_status_specific = status_name
                    logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{log_name_for_notification}' (ID: {game_id}) found as '{new_determined_status_specific}'.")
                    break 

            if new_determined_status_specific:
                current_status = new_determined_status_specific # This is the new status from C/A/OH checks
            elif current_status == "UNKNOWN": 
                current_status = "ONGOING" 
                logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{log_name_for_notification}' (ID: {game_id}) was UNKNOWN and not found in C/A/OH feeds. Defaulting status to ONGOING.")
            else:
                 logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{log_name_for_notification}' (ID: {game_id}) not found in C/A/OH feeds. Retaining previous status '{current_status}'.")
        else: 
            logger.info(f"SCHEDULER/SYNC (User: {user_id}): Game '{current_name}' was found in initial 'ongoing' check. Current status before DB update: '{status_after_ongoing_check}'. Skipping specific C/A/OH checks.")
            current_status = status_after_ongoing_check # Ensure current_status reflects the result of the 'ongoing' check path

        # --- Determine if Status Changed and Update DB ---
        # Compare the determined current_status (from either ongoing check or specific C/A/OH checks)
        # with the original status at the beginning of the function.
        if current_status != original_status_for_notification:
            logger.info(f"SCHEDULER/SYNC (User: {user_id}): Status change for '{log_name_for_notification}' (ID: {game_id}): {original_status_for_notification} -> {current_status}")
            update_fields['completed_status'] = current_status
            pushover_message_parts.append(f"Status: {original_status_for_notification} -> {current_status}")
            if current_status == "COMPLETED" and original_status_for_notification != "COMPLETED":
                is_newly_completed_for_notification = True
        else:
            logger.info(f"SCHEDULER/SYNC (User: {user_id}): Status for '{log_name_for_notification}' (ID: {game_id}) remains '{current_status}'. No status change to DB.")
        
        # Update database if any primary fields (name, version etc.) or status changed.
        if update_fields: # update_fields now includes 'completed_status' if it changed
            # Add last_updated_in_db and last_seen_on_rss for any update
            update_fields['last_updated_in_db'] = datetime.now(timezone.utc).isoformat()
            update_fields['last_seen_on_rss'] = datetime.now(timezone.utc).isoformat() # Also update last_seen if details changed

            set_clause_parts = [f"{key} = ?" for key in update_fields.keys()]
            set_clause = ", ".join(set_clause_parts)
            
            final_params = list(update_fields.values()) + [game_id]
            
            try:
                cursor.execute(f"UPDATE games SET {set_clause} WHERE id = ?", tuple(final_params))
                conn.commit()
                logger.info(f"SCHEDULER/SYNC (User: {user_id}): Updated game details/status in DB for '{original_name_for_notification}'. Fields: {list(update_fields.keys())}")

                # Update local variables if they were part of the update, for notification consistency
                if 'name' in update_fields: original_name_for_notification = update_fields['name'] # Use new name for notification if changed
                if 'version' in update_fields: original_version_for_notification = update_fields['version']
                
            except sqlite3.Error as e_update:
                 logger.error(f"SCHEDULER/SYNC (User: {user_id}): DB error updating game '{original_name_for_notification}': {e_update}")
        
        # --- Send Notifications ---
        # Notification for primary updates (name, version, date etc.)
        # Check if pushover_message_parts has reasons *other than* just a status change if status change is handled separately
        primary_update_reasons = [reason for reason in pushover_message_parts if not reason.startswith("Status:")]
        
        if primary_update_reasons and get_setting(db_path, 'notify_on_game_update', 'False', user_id=user_id) == 'True':
            message_lines = ["Game updated:"]
            message_lines.extend(primary_update_reasons)
            # If status also changed and is part of this batch, include it.
            status_change_reason = next((reason for reason in pushover_message_parts if reason.startswith("Status:")), None)
            if status_change_reason:
                message_lines.append(status_change_reason)

            final_pushover_message = chr(10).join(message_lines)
            send_pushover_notification(
                db_path, user_id=user_id,
                title=f"Update: {original_name_for_notification}", # Use potentially updated name
                message=final_pushover_message,
                url=game_url, url_title=f"View {original_name_for_notification} on F95Zone"
            )
            # Update last notified status after sending a primary update notification
            update_last_notified_status(db_path, user_id, played_game_row_id,
                                        new_version if version_changed else current_version,
                                        new_rss_pub_date_dt.isoformat() if date_changed and new_rss_pub_date_dt else current_rss_pub_date_str,
                                        current_status) # current_status here reflects the final status after all checks
        
        # Notification specifically for a status change to COMPLETED, if not already covered by primary update notification
        # and if primary update notifications are OFF but completed status change notifications are ON.
        elif is_newly_completed_for_notification and \
             get_setting(db_path, 'notify_on_status_change_completed', 'False', user_id=user_id) == 'True' and \
             not (primary_update_reasons and get_setting(db_path, 'notify_on_game_update', 'False', user_id=user_id) == 'True'):
            send_pushover_notification(
                db_path, user_id=user_id,
                title=f"Status Change: {original_name_for_notification}",
                message=f"'{original_name_for_notification}' status changed: {original_status_for_notification} -> COMPLETED",
                url=game_url, url_title=f"View {original_name_for_notification} on F95Zone"
            )
            # Update last notified status after sending a specific completion notification
            update_last_notified_status(db_path, user_id, played_game_row_id,
                                        current_version, # Version might not have changed, use current
                                        current_rss_pub_date_str, # Date might not have changed, use current
                                        "COMPLETED")
        
        # Simplified notification for other status changes (ABANDONED, ON_HOLD) if enabled
        # And not already covered by a primary update notification that included status.
        elif current_status != original_status_for_notification and \
             not is_newly_completed_for_notification and \
             not (primary_update_reasons and get_setting(db_path, 'notify_on_game_update', 'False', user_id=user_id) == 'True'):
            notify_toggle_key = None
            if current_status == "ABANDONED":
                notify_toggle_key = 'notify_on_status_change_abandoned'
            elif current_status == "ON_HOLD":
                notify_toggle_key = 'notify_on_status_change_on_hold'
            
            if notify_toggle_key and get_setting(db_path, notify_toggle_key, 'False', user_id=user_id) == 'True':
                send_pushover_notification(
                    db_path, user_id=user_id,
                    title=f"Status Change: {original_name_for_notification}",
                    message=f"'{original_name_for_notification}' status changed: {original_status_for_notification} -> {current_status}",
                    url=game_url, url_title=f"View {original_name_for_notification} on F95Zone"
                )
                # Update last notified status after sending other status change notifications
                update_last_notified_status(db_path, user_id, played_game_row_id,
                                            current_version, # Version might not have changed
                                            current_rss_pub_date_str, # Date might not have changed
                                            current_status)

        # Update last_checked_at regardless of updates found
        try:
            cursor.execute("UPDATE games SET last_checked_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), game_id))
            conn.commit()
        except sqlite3.Error as e_lc:
            logger.error(f"SCHEDULER/SYNC (User: {user_id}): DB error updating last_checked_at for '{current_name}': {e_lc}")

    except sqlite3.Error as e:
        logger.error(f"SCHEDULER/SYNC (User: {user_id}): Database error in check_single_game_update_and_status for played_game_id {played_game_row_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"SCHEDULER/SYNC (User: {user_id}): Unexpected error in check_single_game_update_and_status for played_game_id {played_game_row_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def scheduled_games_update_check(db_path: str, f95_client: F95ApiClient):
    """
    Scheduled task to check all user-tracked games for updates and status changes.
    Only processes games where 'notify_for_updates' is true in 'user_played_games'.
    Iterates over all users.
    """
    logger.info("--- Starting scheduled games update check for ALL USERS (task initiated by APScheduler) ---")
    
    all_user_ids = get_all_user_ids(db_path)
    if not all_user_ids:
        logger.info("SCHEDULER: No users found in the database. Scheduled check complete.")
        return

    logger.info(f"SCHEDULER: Found {len(all_user_ids)} users to process.")

    total_games_checked_for_all_users = 0

    for user_id_to_check in all_user_ids:
        logger.info(f"SCHEDULER: Processing user_id: {user_id_to_check}")
        conn = None
        games_to_check_for_this_user_count = 0
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT upg.id 
                FROM user_played_games upg
                JOIN games g ON upg.game_id = g.id
                WHERE upg.user_id = ? 
                  AND upg.notify_for_updates = 1 
                  AND (g.completed_status IS NULL OR g.completed_status NOT IN ('COMPLETED', 'ABANDONED')) 
            """, (user_id_to_check,)) # Added user_id filter, also don't re-check ABANDONED
            
            played_game_ids_for_user = [row[0] for row in cursor.fetchall()]
            games_to_check_for_this_user_count = len(played_game_ids_for_user)
            
            if not played_game_ids_for_user:
                logger.info(f"SCHEDULER: No games to check for user_id {user_id_to_check} based on preferences and status.")
                continue

            logger.info(f"SCHEDULER: Found {games_to_check_for_this_user_count} games to check for user_id {user_id_to_check}.")
            
            for i, played_game_row_id in enumerate(played_game_ids_for_user):
                logger.info(f"SCHEDULER (User: {user_id_to_check}): Processing game {i+1}/{games_to_check_for_this_user_count} (PlayedID: {played_game_row_id})")
                check_single_game_update_and_status(db_path, f95_client, played_game_row_id, user_id_to_check)
                total_games_checked_for_all_users +=1
                # Optional: time.sleep(1) 
                
        except sqlite3.Error as e:
            logger.error(f"SCHEDULER: Database error during processing for user_id {user_id_to_check}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"SCHEDULER: Unexpected error during processing for user_id {user_id_to_check}: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()
    
    logger.info(f"--- Scheduled games update check finished for all users (processed {total_games_checked_for_all_users} applicable games across all users) ---")

def sync_all_my_games_for_user(db_path: str, f95_client: F95ApiClient, user_id: int):
    """
    Manually triggers an update check for all relevant games for a specific user.
    Only processes games where 'notify_for_updates' is true and game is not COMPLETED or ABANDONED.
    """
    logger.info(f"--- Starting manual sync for all relevant games for user_id: {user_id} ---")
    
    conn = None
    games_processed_count = 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Select games for the user that are marked for notification and not in a final state
        cursor.execute("""
            SELECT upg.id 
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.user_id = ? 
              AND upg.notify_for_updates = 1 
              AND (g.completed_status IS NULL OR g.completed_status NOT IN ('COMPLETED', 'ABANDONED')) 
        """, (user_id,))
        
        played_game_ids_for_user = [row[0] for row in cursor.fetchall()]
        total_games_to_sync = len(played_game_ids_for_user)

        if not played_game_ids_for_user:
            logger.info(f"MANUAL_SYNC_ALL (User: {user_id}): No games to sync based on preferences and status.")
            return games_processed_count, total_games_to_sync

        logger.info(f"MANUAL_SYNC_ALL (User: {user_id}): Found {total_games_to_sync} games to sync.")
        
        for i, played_game_row_id in enumerate(played_game_ids_for_user):
            logger.info(f"MANUAL_SYNC_ALL (User: {user_id}): Processing game {i+1}/{total_games_to_sync} (PlayedID: {played_game_row_id})")
            try:
                check_single_game_update_and_status(db_path, f95_client, played_game_row_id, user_id)
                games_processed_count += 1
            except Exception as e_single:
                logger.error(f"MANUAL_SYNC_ALL (User: {user_id}): Error syncing played_game_id {played_game_row_id}: {e_single}", exc_info=True)
            # Optional: time.sleep(1) if rate limiting becomes an issue for many sequential calls

    except sqlite3.Error as e:
        logger.error(f"MANUAL_SYNC_ALL (User: {user_id}): Database error: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"MANUAL_SYNC_ALL (User: {user_id}): Unexpected error: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
            
    logger.info(f"--- Manual sync finished for user_id: {user_id}. Processed {games_processed_count}/{total_games_to_sync} games. ---")
    return games_processed_count, total_games_to_sync

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("F95Zone Update Checker - Application Started")

    # Initialize F95APIClient
    client = F95ApiClient() # No credentials passed
    
    try:
        # Initialize Database
        initialize_database(DB_PATH) 
        # process_rss_feed(DB_PATH, client) # Removed - master sync is no longer used
        # update_completion_statuses(DB_PATH, client) # Removed - master sync is no longer used
        logger.info("Direct run: Database initialized. Master RSS processing and completion status updates are skipped.")

        # The main purpose of a direct run of app/main.py might be for specific CLI tasks or tests.
        # User-specific checks are typically handled by the scheduler in the Flask app context.
        # If you need to test user-specific checks via CLI, you would call scheduled_games_update_check here,
        # possibly after ensuring a user and their game list exist.
        # For example:
        # primary_admin_id = get_primary_admin_user_id(DB_PATH)
        # if primary_admin_id:
        #    logger.info(f"CLI: Manually triggering user-specific checks for admin ID: {primary_admin_id}")
        #    scheduled_games_update_check(DB_PATH, client) # This would run for all users
        # else:
        #    logger.info("CLI: No primary admin user found to trigger checks for.")

    except Exception as e:
        logger.error(f"An unexpected error occurred in the main execution block of app/main.py: {e}", exc_info=True)
    finally:
        if 'client' in locals() and client:
            client.close_session()
        logger.info("F95Zone Update Checker - Application Finished")