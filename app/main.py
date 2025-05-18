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
from dotenv import load_dotenv
from f95apiclient import F95ApiClient # Assuming f95apiclient is in PYTHONPATH or installed
from typing import Optional # Added
import re # Added for regex in get_first_significant_word
from pushover import Client as PushoverClient # Added for Pushover

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
        level=logging.DEBUG,
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
            # Logger might not be fully set up if this is called before setup_logging
            # or if setup_logging itself had issues. Print for robustness.
            print(f"Database directory created: {db_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create database directory {db_dir}. Error: {e}")
            # If the directory cannot be created, connecting to the DB will likely fail or use a wrong path.
            # Consider raising an exception or exiting if this is a hard requirement.
            return # Stop further processing in this function if dir creation fails
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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
        
        # Check if last_checked_at column exists, add if not (for existing databases)
        cursor.execute("PRAGMA table_info(games)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'last_checked_at' not in columns:
            cursor.execute("ALTER TABLE games ADD COLUMN last_checked_at TEXT DEFAULT NULL")
            logger.info("Added 'last_checked_at' column to 'games' table.")

        # Create user_played_games table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_played_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                user_notes TEXT,
                user_rating REAL, -- e.g., 0.0 to 5.0
                notify_for_updates BOOLEAN DEFAULT TRUE,
                date_added_to_played_list TEXT NOT NULL,
                last_notified_version TEXT, -- Store version for which notification was last sent
                last_notified_rss_pub_date TEXT, -- Store RSS pub date for which notification was last sent
                last_notified_completion_status TEXT, -- Store completion status for which notification was last sent
                user_acknowledged_version TEXT, -- Store version acknowledged by user
                user_acknowledged_rss_pub_date TEXT, -- Store RSS pub date acknowledged by user
                user_acknowledged_completion_status TEXT, -- Store completion status acknowledged by user
                FOREIGN KEY(game_id) REFERENCES games(id),
                UNIQUE(game_id) -- Assuming a user adds a game to their played list only once
            )
        """)
        
        # Create app_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        """)
        # Optionally, pre-populate with default settings if they don't exist
        # Example: Set a default update schedule if not already set
        cursor.execute("INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)", 
                       ('update_schedule_hours', '24')) # Default to 24 hours
        
        # Add Pushover related settings with defaults
        default_pushover_settings = {
            'pushover_user_key': '',
            'pushover_api_key': '',
            'notify_on_game_add': 'True',
            'notify_on_game_delete': 'True',
            'notify_on_game_update': 'True',
            'notify_on_status_change_completed': 'True',
            'notify_on_status_change_abandoned': 'True',
            'notify_on_status_change_on_hold': 'True'
        }
        for key, value in default_pushover_settings.items():
            cursor.execute("INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)", (key, value))
        
        conn.commit()
        logger.info(f"Database initialized successfully at {db_path}")
    except sqlite3.Error as e:
        logger.error(f"Database error during initialization: {e}")
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
def get_setting(db_path: str, key: str, default_value: str = None) -> str:
    """Retrieves a setting value from the app_settings table."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row[0]
        return default_value
    except sqlite3.Error as e:
        logger.error(f"Database error getting setting '{key}': {e}")
        return default_value
    finally:
        if conn:
            conn.close()

def set_setting(db_path: str, key: str, value: str) -> bool:
    """Saves or updates a setting in the app_settings table."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO app_settings (setting_key, setting_value) VALUES (?, ?)", (key, value))
        conn.commit()
        logger.info(f"Setting '{key}' saved with value: '{value}'")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error setting '{key}' to '{value}': {e}")
        return False
    finally:
        if conn:
            conn.close()

# --- Pushover Notification Function ---
def send_pushover_notification(db_path: str, title: str, message: str, priority: int = 0, url: Optional[str] = None, url_title: Optional[str] = None):
    """Sends a notification via Pushover if configured."""
    user_key = get_setting(db_path, 'pushover_user_key')
    api_key = get_setting(db_path, 'pushover_api_key')

    if not user_key or not api_key:
        logger.info("Pushover user_key or api_key not configured. Skipping notification.")
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

    logger.info(f"Attempting to add game to user list: {name_to_use} ({f95_url})")
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
            search_name_part = name_to_use.split(' ')[0] if name_to_use else ""

            # Check for COMPLETED status
            completed_games_rss = client.get_latest_game_data_from_rss(
                search_term=search_name_part, 
                completion_status_filter="completed",
                limit=90 # Max limit
            )
            if completed_games_rss is None: # API call failed
                 logger.warning(f"Failed to fetch 'completed' RSS feed for game '{name_to_use}' during add_game_to_my_list. Status determination may be impacted.")
                 current_game_completed_status = "UNKNOWN" # Fallback
            elif any(g['url'] == f95_url for g in completed_games_rss):
                current_game_completed_status = "COMPLETED"
            else:
                # Check for ABANDONED status
                abandoned_games_rss = client.get_latest_game_data_from_rss(
                    search_term=search_name_part,
                    completion_status_filter="abandoned",
                    limit=90
                )
                if abandoned_games_rss is None:
                    logger.warning(f"Failed to fetch 'abandoned' RSS feed for game '{name_to_use}' during add_game_to_my_list. Status determination may be impacted.")
                elif any(g['url'] == f95_url for g in abandoned_games_rss):
                    current_game_completed_status = "ABANDONED"
                else:
                    # Check for ON_HOLD status
                    on_hold_games_rss = client.get_latest_game_data_from_rss(
                        search_term=search_name_part,
                        completion_status_filter="on_hold",
                        limit=90
                    )
                    if on_hold_games_rss is None:
                        logger.warning(f"Failed to fetch 'on_hold' RSS feed for game '{name_to_use}' during add_game_to_my_list. Status determination may be impacted.")
                    elif any(g['url'] == f95_url for g in on_hold_games_rss):
                        current_game_completed_status = "ON_HOLD"
                    else:
                        # If not found in specific status feeds, and not UNKNOWN from a previous fetch, assume ONGOING
                        # We don't explicitly query "ongoing" as it's the default if not in other categories
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
                        game_id, user_notes, user_rating, notify_for_updates, date_added_to_played_list,
                        last_notified_version, last_notified_rss_pub_date, last_notified_completion_status,
                        user_acknowledged_version, user_acknowledged_rss_pub_date, user_acknowledged_completion_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (game_id_in_db, user_notes, user_rating, notify, current_timestamp,
                      current_game_version, current_game_rss_pub_date, current_game_completed_status, # Initialize last_notified_*
                      current_game_version, current_game_rss_pub_date, current_game_completed_status  # Initialize user_acknowledged_*
                      ))
                conn.commit()
                logger.info(f"Game ID {game_id_in_db} ('{name_to_use}') added to user_played_games. Initial acknowledged state set.")
                
                # Send Pushover notification for game add
                if get_setting(db_path, 'notify_on_game_add', 'False') == 'True':
                    send_pushover_notification(
                        db_path,
                        title=f"Game Added: {name_to_use}",
                        message=f"'{name_to_use}' was added to your monitored list.\nStatus: {current_game_completed_status}, Version: {current_game_version}",
                        url=f95_url,
                        url_title=f"View {name_to_use} on F95Zone"
                    )
                return True, f"Game '{name_to_use}' added to your list."
            except sqlite3.IntegrityError: # Handles UNIQUE constraint violation (game_id already in user_played_games)
                conn.rollback()
                logger.warning(f"Game ID {game_id_in_db} ('{name_to_use}') is already in user_played_games.")
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

def get_my_played_games(db_path: str, 
                        name_filter: Optional[str] = None, 
                        min_rating_filter: Optional[float] = None, 
                        sort_by: str = 'name', 
                        sort_order: str = 'ASC') -> list[dict]:
    """
    Retrieves all games from the user's played list, joined with details from the main games table.
    Supports filtering by name (partial match) and minimum rating,
    and sorting by specified columns.

    Args:
        db_path: Path to the SQLite database.
        name_filter: Optional string to filter games by name (case-insensitive partial match).
        min_rating_filter: Optional float to filter games by minimum user rating (inclusive).
        sort_by: Column to sort by. Allowed: 'name', 'last_updated', 'date_added'. Defaults to 'name'.
        sort_order: Sort order. Allowed: 'ASC', 'DESC'. Defaults to 'ASC'.
    """
    logger.info(f"Fetching user's played games list with filters: name='{name_filter}', min_rating='{min_rating_filter}', sort_by='{sort_by}', sort_order='{sort_order}'.")
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
        
        where_clauses = []
        params = []

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
            'last_updated': 'g.last_updated_in_db',
            'date_added': 'upg.date_added_to_played_list',
            'rating': 'upg.user_rating' # Added rating sort
        }
        sql_sort_column = allowed_sort_columns.get(sort_by, 'g.name') # Default to g.name if invalid
        sql_sort_order = 'DESC' if sort_order.upper() == 'DESC' else 'ASC' # Default to ASC

        base_query += f" ORDER BY {sql_sort_column} {sql_sort_order}"
        
        cursor.execute(base_query, tuple(params))
        rows = cursor.fetchall()
        for row in rows:
            games_list.append(dict(row))
        logger.info(f"Retrieved {len(games_list)} games from user's played list.")
    except sqlite3.Error as e:
        logger.error(f"Database error in get_my_played_games: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in get_my_played_games: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return games_list

def get_my_played_game_details(db_path: str, played_game_id: int) -> Optional[dict]:
    """
    Retrieves details for a specific game from the user's played list, 
    joined with details from the main games table.
    'played_game_id' is the ID from the user_played_games table.
    """
    logger.info(f"Fetching details for played game ID: {played_game_id}")
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
            WHERE upg.id = ?
        """, (played_game_id,))
        row = cursor.fetchone()
        if row:
            logger.info(f"Details found for played game ID: {played_game_id} - {row['name']}")
            return dict(row)
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id}")
            return None
    except sqlite3.Error as e:
        logger.error(f"Database error in get_my_played_game_details for ID {played_game_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_my_played_game_details for ID {played_game_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def update_my_played_game_details(db_path: str, played_game_id: int, 
                                  user_notes: str = None, user_rating: float = None, 
                                  notify_for_updates: bool = None) -> dict:
    """
    Updates details for a specific game in the user's played list.
    Only updates fields that are provided (not None).
    'played_game_id' is the ID from the user_played_games table.
    """
    logger.info(f"Attempting to update details for played game ID: {played_game_id}")
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
        
        sql = f"UPDATE user_played_games SET {', '.join(set_clauses)} WHERE id = ?"
        
        cursor.execute(sql, tuple(params))
        updated_rows = cursor.rowcount
        conn.commit()

        if updated_rows > 0:
            logger.info(f"Successfully updated details for played game ID: {played_game_id}")
            return {'success': True, 'message': "Game details updated successfully."}
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id} to update.")
            return {'success': False, 'message': "No game found with that ID in your played list."}

    except sqlite3.Error as e:
        logger.error(f"Database error in update_my_played_game_details for ID {played_game_id}: {e}", exc_info=True)
        return {'success': False, 'message': f"Database error: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error in update_my_played_game_details for ID {played_game_id}: {e}", exc_info=True)
        return {'success': False, 'message': f"Unexpected error: {e}"}
    finally:
        if conn:
            conn.close()

def delete_game_from_my_list(db_path: str, played_game_id: int) -> tuple[bool, str]:
    """
    Deletes a game from the user's played list based on the user_played_games.id.
    Does not delete from the main 'games' table.
    """
    logger.info(f"Attempting to delete played game ID: {played_game_id} from user's list.")
    conn = None
    game_name_for_notification = "Unknown Game" # For Pushover
    game_url_for_notification = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get game name and URL for message before deleting
        cursor.execute("""
            SELECT g.name, g.f95_url 
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.id = ?
        """, (played_game_id,))
        game_info = cursor.fetchone()
        if game_info:
            game_name_for_notification = game_info[0]
            game_url_for_notification = game_info[1]
        else:
            game_name_for_notification = "Unknown Game (ID: " + str(played_game_id) + ")"

        cursor.execute("DELETE FROM user_played_games WHERE id = ?", (played_game_id,))
        deleted_rows = cursor.rowcount
        conn.commit()

        if deleted_rows > 0:
            logger.info(f"Successfully deleted played game ID: {played_game_id} ('{game_name_for_notification}') from user's list.")
            # Send Pushover notification for game delete
            if get_setting(db_path, 'notify_on_game_delete', 'False') == 'True':
                send_pushover_notification(
                    db_path,
                    title=f"Game Removed: {game_name_for_notification}",
                    message=f"'{game_name_for_notification}' was removed from your monitored list.",
                    url=game_url_for_notification,
                    url_title=f"View {game_name_for_notification} on F95Zone" if game_url_for_notification else None
                )
            return True, f"Game '{game_name_for_notification}' removed from your list."
        else:
            logger.warning(f"No game found with played_game_id: {played_game_id} to delete from user's list.")
            return False, "No game found with that ID in your list to delete."

    except sqlite3.Error as e:
        logger.error(f"Database error deleting played game ID {played_game_id}: {e}", exc_info=True)
        return False, f"Database error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error deleting played game ID {played_game_id}: {e}", exc_info=True)
        return False, f"An unexpected error occurred: {e}"
    finally:
        if conn:
            conn.close()

def mark_game_as_acknowledged(db_path: str, played_game_id: int) -> tuple[bool, str, Optional[dict]]:
    """
    Updates the user_acknowledged_version, _rss_pub_date, and _completion_status
    for a game in the user's played list to match the current state in the 'games' table.
    Returns success status, message, and a dict of the acknowledged (current) game details on success.
    """
    logger.info(f"Attempting to mark updates as acknowledged for played game ID: {played_game_id}.")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Step 1: Get the game_id from user_played_games
        cursor.execute("SELECT game_id FROM user_played_games WHERE id = ?", (played_game_id,))
        played_game_row = cursor.fetchone()
        if not played_game_row:
            logger.warning(f"No played game entry found for played_game_id: {played_game_id}.")
            return False, "Game not found in your list.", None
        
        game_id_from_games_table = played_game_row[0]

        # Step 2: Get current details from the 'games' table
        cursor.execute("SELECT name, version, rss_pub_date, completed_status FROM games WHERE id = ?", (game_id_from_games_table,))
        game_details_row = cursor.fetchone()
        if not game_details_row:
            logger.error(f"Could not find game details in 'games' table for game_id: {game_id_from_games_table} (linked from played_game_id: {played_game_id}).")
            return False, "Could not retrieve current game details to acknowledge.", None

        game_name, current_version, current_rss_pub_date, current_completed_status = game_details_row
        
        # Step 3: Update user_played_games
        cursor.execute("""
            UPDATE user_played_games
            SET user_acknowledged_version = ?,
                user_acknowledged_rss_pub_date = ?,
                user_acknowledged_completion_status = ?
            WHERE id = ?
        """, (current_version, current_rss_pub_date, current_completed_status, played_game_id))
        
        updated_rows = cursor.rowcount
        conn.commit()

        if updated_rows > 0:
            logger.info(f"Successfully marked updates as acknowledged for played game ID: {played_game_id} ('{game_name}').")
            acknowledged_details = {
                "version": current_version,
                "rss_pub_date": current_rss_pub_date,
                "completed_status": current_completed_status
            }
            return True, f"Updates for '{game_name}' marked as acknowledged.", acknowledged_details
        else:
            # This case should be rare if the initial select for played_game_id succeeded
            logger.warning(f"Failed to update acknowledged status for played_game_id: {played_game_id} (rowcount 0).")
            return False, "Failed to update acknowledged status.", None

    except sqlite3.Error as e:
        logger.error(f"Database error marking game acknowledged (ID {played_game_id}): {e}", exc_info=True)
        return False, f"Database error: {e}", None
    except Exception as e:
        logger.error(f"Unexpected error marking game acknowledged (ID {played_game_id}): {e}", exc_info=True)
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

def check_for_my_updates(db_path: str) -> list[dict]:
    """
    Checks for updates for games in the user's played list that are marked for notification.
    Identifies version changes, RSS pub date changes, or significant completion status changes.
    Returns a list of notification objects (dictionaries).
    This function DOES NOT update the 'last_notified' fields in the database.
    """
    logger.info("Checking for updates in user's played games list...")
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
            WHERE upg.notify_for_updates = TRUE
        """)
        games_to_notify = cursor.fetchall()
        logger.info(f"Found {len(games_to_notify)} games in played list marked for notifications.")

        for game in games_to_notify:
            notification_reasons = []
            is_newly_completed = False

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
            # elif game['current_completed_status'] == 'ON_HOLD' and game['last_notified_completion_status'] != 'ON_HOLD':
            #     notification_reasons.append("Game status changed to ON HOLD.")
            # elif game['current_completed_status'] == 'ABANDONED' and game['last_notified_completion_status'] != 'ABANDONED':
            #     notification_reasons.append("Game status changed to ABANDONED.")

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
                    'new_notified_completion_status': game['current_completed_status']
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

def update_last_notified_status(db_path: str, played_game_id: int, version: str, rss_pub_date: str, completed_status: str):
    """
    Updates the last_notified fields for a game in the user_played_games table.
    This should be called AFTER a notification has been successfully sent/processed.
    """
    logger.info(f"Updating last notified status for played game ID: {played_game_id}")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_played_games 
            SET last_notified_version = ?, 
                last_notified_rss_pub_date = ?, 
                last_notified_completion_status = ?
            WHERE id = ?
        """, (version, rss_pub_date, completed_status, played_game_id))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Successfully updated last_notified status for played_game_id {played_game_id}.")
        else:
            logger.warning(f"No row found to update last_notified status for played_game_id {played_game_id}.")
    except sqlite3.Error as e:
        logger.error(f"Database error in update_last_notified_status for ID {played_game_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in update_last_notified_status for ID {played_game_id}: {e}", exc_info=True)
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
    if not name_str:
        return ""
    # Remove content in brackets (like version, status, or author)
    name_str_cleaned = re.sub(r'\\s*\\[.*?\\]\\s*', ' ', name_str).strip() # More robust removal
    name_str_cleaned = re.sub(r'\\s*\\(.*?\\)\\s*', ' ', name_str_cleaned).strip() # Remove content in parentheses

    # Remove common punctuation that might stick to words or be standalone
    # Keep alphanumeric, spaces, and hyphens if they are part of a word
    name_str_cleaned = re.sub(r'[^\\w\\s-]', '', name_str_cleaned) 
    
    words = name_str_cleaned.split()
    for word in words:
        # Further clean individual words: remove leading/trailing hyphens not part of word
        cleaned_word = word.strip('-')
        if cleaned_word.lower() not in _STOP_WORDS and len(cleaned_word) > 2: # Ensure word is reasonably long
            return cleaned_word # Return the cleaned word
    
    # Fallback: if all words are stop words or too short, try the first word if it exists and is not tiny
    if words:
        first_word_cleaned = words[0].strip('-')
        if len(first_word_cleaned) > 1 : # Avoid single characters as search terms
             return first_word_cleaned
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

def check_single_game_update_and_status(db_path: str, f95_client: F95ApiClient, played_game_row_id: int):
    """
    Checks a single game for updates (version, RSS date) and then for status changes
    (COMPLETED, ABANDONED, ON-HOLD) based on the logic requested.
    Updates the 'games' table accordingly.
    Sends Pushover notifications based on settings.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Access columns by name
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT g.id, g.name, g.version, g.rss_pub_date, g.completion_status, g.f95_url as url, upg.id as user_played_game_id
            FROM games g
            JOIN user_played_games upg ON g.id = upg.game_id
            WHERE upg.id = ?
        """, (played_game_row_id,))
        game_data = cursor.fetchone()

        if not game_data:
            logger.warning(f"SCHEDULER: No game data found for user_played_games.id {played_game_row_id}. Skipping.")
            return

        game_id = game_data['id']
        current_name = game_data['name']
        current_version = game_data['version']
        current_rss_pub_date_str = game_data['rss_pub_date']
        current_status = game_data['completion_status']
        game_url = game_data['url']
        
        original_name_for_notification = current_name # Store before potential update
        original_version_for_notification = current_version
        original_status_for_notification = current_status

        logger.info(f"SCHEDULER/SYNC: Checking '{current_name}' (GameID: {game_id}, PlayedID: {played_game_row_id}, URL: {game_url})")
        
        search_term = get_first_significant_word(current_name)
        if not search_term:
            logger.warning(f"SCHEDULER: No significant search term for '{current_name}'. General update check might be unreliable.")
            # We will still proceed to status checks as per logic.
        
        latest_data_items = None
        if search_term: # Only search if we have a term
            latest_data_items = f95_client.get_latest_game_data_from_rss(search_term=search_term, limit=10) # Small limit for general update check

        found_game_update_data = None
        if latest_data_items:
            for item in latest_data_items:
                if item.get('url') == game_url:
                    found_game_update_data = item
                    break
        
        has_primary_update = False
        if found_game_update_data:
            new_name = found_game_update_data.get('name') # Name from RSS via client
            new_version = found_game_update_data.get('version') # Version from RSS title via client
            new_author = found_game_update_data.get('author')
            new_image_url = found_game_update_data.get('image_url')
            new_rss_pub_date = found_game_update_data.get('rss_pub_date') # This is a datetime object from client

            current_rss_pub_date_dt = None
            if current_rss_pub_date_str:
                try:
                    # Ensure it's timezone-aware for comparison with new_rss_pub_date (which is timezone-aware UTC from client)
                    dt_obj = datetime.fromisoformat(current_rss_pub_date_str.replace('Z', '+00:00'))
                    if dt_obj.tzinfo is None:
                         current_rss_pub_date_dt = timezone.utc.localize(dt_obj) # Should not happen if fromisoformat worked with Z/offset
                    else:
                         current_rss_pub_date_dt = dt_obj.astimezone(timezone.utc)
                except ValueError:
                    try: # Fallback for other common RSS date formats if fromisoformat fails
                        dt_obj = datetime.strptime(current_rss_pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                        current_rss_pub_date_dt = dt_obj.astimezone(timezone.utc)
                    except ValueError as e_parse:
                        logger.error(f"SCHEDULER: Could not parse current_rss_pub_date '{current_rss_pub_date_str}' for game '{current_name}': {e_parse}")
            
            # Check for changes
            name_changed = new_name and new_name != current_name
            version_changed = new_version and new_version != current_version
            # Ensure new_rss_pub_date is not None before comparison
            date_changed = new_rss_pub_date and current_rss_pub_date_dt and new_rss_pub_date > current_rss_pub_date_dt
            author_changed = new_author and new_author != game_data['author'] # game_data has original author
            image_changed = new_image_url and new_image_url != game_data['image_url'] # game_data has original image

            if name_changed or version_changed or date_changed or author_changed or image_changed:
                has_primary_update = True
                logger.info(f"SCHEDULER/SYNC: Primary update found for '{original_name_for_notification}'. OldVer: {original_version_for_notification}, NewVer: {new_version}. OldDate: {current_rss_pub_date_str}, NewDate: {new_rss_pub_date.isoformat() if new_rss_pub_date else 'N/A'}")
                
                pushover_update_message_parts = []
                if name_changed and new_name: pushover_update_message_parts.append(f"Name: {original_name_for_notification} -> {new_name}")
                if version_changed and new_version: pushover_update_message_parts.append(f"Version: {original_version_for_notification} -> {new_version}")
                if date_changed and new_rss_pub_date: pushover_update_message_parts.append(f"RSS Date Updated") # Simpler message for date
                # Author/image changes less critical for primary notification, can be logged.

                update_fields = {}
                if name_changed: update_fields['name'] = new_name
                if version_changed: update_fields['version'] = new_version
                if date_changed: update_fields['rss_pub_date'] = new_rss_pub_date.isoformat()
                if author_changed: update_fields['author'] = new_author
                if image_changed: update_fields['image_url'] = new_image_url
                
                if update_fields:
                    set_clause = ", ".join([f"{key} = ?" for key in update_fields.keys()])
                    params = list(update_fields.values())
                    params.append(datetime.now(timezone.utc).isoformat()) # last_updated_in_db
                    params.append(game_id)
                    
                    try:
                        cursor.execute(f"UPDATE games SET {set_clause}, last_updated_in_db = ?, last_seen_on_rss = ? WHERE id = ?", params) # last_seen_on_rss is also now
                        # The last param for last_seen_on_rss should be the current timestamp as well
                        # Corrected params:
                        final_params = list(update_fields.values()) + [datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), game_id]

                        cursor.execute(f"UPDATE games SET {set_clause}, last_updated_in_db = ?, last_seen_on_rss = ? WHERE id = ?", final_params)

                        conn.commit()
                        logger.info(f"SCHEDULER/SYNC: Updated game details in DB for '{original_name_for_notification}'.")
                        # Update current_name, current_version etc. if they were changed, for subsequent status checks
                        if name_changed: current_name = new_name 
                        if version_changed: current_version = new_version
                        # current_status not updated here, but by specific status checks below.

                        # Send Pushover notification for game update if enabled
                        if pushover_update_message_parts and get_setting(db_path, 'notify_on_game_update', 'False') == 'True':
                            send_pushover_notification(
                                db_path,
                                title=f"Update: {new_name if new_name else original_name_for_notification}",
                                message="Details updated:\n" + "\n".join(pushover_update_message_parts),
                                url=game_url,
                                url_title=f"View {new_name if new_name else original_name_for_notification} on F95Zone"
                            )
                    except sqlite3.Error as e_update:
                         logger.error(f"SCHEDULER/SYNC: DB error updating game '{original_name_for_notification}': {e_update}")
                         has_primary_update = False # If DB update fails, treat as no primary update for status logic

        # Status checking logic
        new_status_determined = None
        status_change_notification_message = None

        if has_primary_update:
            logger.info(f"SCHEDULER/SYNC: Primary update for '{current_name}'. Checking for 'COMPLETED' status.")
            # Only check for completed if the game is not already marked as such
            if original_status_for_notification != "COMPLETED": # Use original status for this check
                status_check_result = _determine_specific_game_status(f95_client, game_url, current_name, "completed")
                if status_check_result == "COMPLETED":
                    new_status_determined = "COMPLETED"
                    if get_setting(db_path, 'notify_on_status_change_completed', 'False') == 'True':
                        status_change_notification_message = f"'{current_name}' status changed: {original_status_for_notification} -> COMPLETED"
            elif original_status_for_notification == "COMPLETED": 
                status_check_result = _determine_specific_game_status(f95_client, game_url, current_name, "completed")
                if status_check_result != "COMPLETED":
                    logger.info(f"SCHEDULER/SYNC: Game '{current_name}' was COMPLETED, but no longer found in completed feed after update. Setting to ONGOING.")
                    new_status_determined = "ONGOING" # Reverted from COMPLETED
                    # Decide if this reversion warrants a notification based on 'notify_on_game_update' or a new toggle
                    if get_setting(db_path, 'notify_on_game_update', 'False') == 'True': # Treat as a general update
                         status_change_notification_message = f"'{current_name}' status changed: COMPLETED -> ONGOING"
                else:
                    logger.info(f"SCHEDULER/SYNC: Game '{current_name}' confirmed still COMPLETED after update.")

        else: # No primary update detected (or general search failed / DB update failed)
            logger.info(f"SCHEDULER/SYNC: No primary update for '{current_name}'. Checking for 'ABANDONED' or 'ON-HOLD'.")
            if original_status_for_notification not in ["COMPLETED", "ABANDONED"]:
                status_check_result = _determine_specific_game_status(f95_client, game_url, current_name, "abandoned")
                if status_check_result == "ABANDONED":
                    new_status_determined = "ABANDONED"
                    if get_setting(db_path, 'notify_on_status_change_abandoned', 'False') == 'True':
                        status_change_notification_message = f"'{current_name}' status changed: {original_status_for_notification} -> ABANDONED"
                elif original_status_for_notification not in ["ON_HOLD"]: 
                     status_check_result_onhold = _determine_specific_game_status(f95_client, game_url, current_name, "on_hold")
                     if status_check_result_onhold == "ON_HOLD":
                         new_status_determined = "ON_HOLD"
                         if get_setting(db_path, 'notify_on_status_change_on_hold', 'False') == 'True':
                            status_change_notification_message = f"'{current_name}' status changed: {original_status_for_notification} -> ON_HOLD"
        
        if new_status_determined and new_status_determined != original_status_for_notification: # Compare with original status
            try:
                cursor.execute("UPDATE games SET completion_status = ?, last_updated_in_db = ?, last_seen_on_rss = ? WHERE id = ?", 
                               (new_status_determined, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), game_id))
                conn.commit()
                logger.info(f"SCHEDULER/SYNC: Status for '{current_name}' (ID: {game_id}) changed from '{original_status_for_notification}' to '{new_status_determined}'.")
                
                # Send Pushover for status change if message was prepared and not already sent by primary update
                if status_change_notification_message and not (has_primary_update and get_setting(db_path, 'notify_on_game_update', 'False') == 'True'):
                    send_pushover_notification(
                        db_path,
                        title=f"Status Change: {current_name}",
                        message=status_change_notification_message,
                        url=game_url,
                        url_title=f"View {current_name} on F95Zone"
                    )
                # If it was a primary update AND a status change, and primary update notifications are on,
                # the status change might already be part of that broader update context or could be sent separately.
                # Current logic might send two if primary update + specific status change toggle are both on.
                # Let's refine: only send specific status change if no primary update notif was sent.
                elif status_change_notification_message and has_primary_update and get_setting(db_path, 'notify_on_game_update', 'False') == 'False':
                     # Primary update occurred, but its notification toggle is off.
                     # So, if this specific status change toggle is on, send it.
                     send_pushover_notification(
                        db_path,
                        title=f"Status Change: {current_name}",
                        message=status_change_notification_message,
                        url=game_url,
                        url_title=f"View {current_name} on F95Zone"
                    )

            except sqlite3.Error as e_status_update:
                logger.error(f"SCHEDULER/SYNC: DB error updating status for '{current_name}': {e_status_update}")
        
        # Update last_checked_at regardless of updates found, to show it was processed
        try:
            cursor.execute("UPDATE games SET last_checked_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), game_id))
            conn.commit()
        except sqlite3.Error as e_lc:
            logger.error(f"SCHEDULER/SYNC: DB error updating last_checked_at for '{current_name}': {e_lc}")

    except sqlite3.Error as e:
        logger.error(f"SCHEDULER/SYNC: Database error in check_single_game_update_and_status for played_game_id {played_game_row_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"SCHEDULER/SYNC: Unexpected error in check_single_game_update_and_status for played_game_id {played_game_row_id}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def scheduled_games_update_check(db_path: str, f95_client: F95ApiClient):
    """
    Scheduled task to check all user-tracked games for updates and status changes.
    Only processes games where 'notify_for_updates' is true in 'user_played_games'.
    """
    logger.info("--- Starting scheduled games update check (task initiated by APScheduler) ---")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    games_to_check_count = 0
    try:
        # Select user_played_games.id for games where notify_for_updates is true
        # AND the game is not already marked as 'COMPLETED' in the games table.
        cursor.execute("""
            SELECT upg.id 
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.notify_for_updates = 1 
              AND (g.completed_status IS NULL OR g.completed_status != 'COMPLETED')
        """)
        played_game_ids_to_check = [row[0] for row in cursor.fetchall()]
        games_to_check_count = len(played_game_ids_to_check)
        
        if not played_game_ids_to_check:
            logger.info("SCHEDULER: No games in user's list are set for update notifications. Scheduled check complete.")
            return

        logger.info(f"SCHEDULER: Found {games_to_check_count} games to check for updates based on user notification preferences.")
        
        for i, played_game_row_id in enumerate(played_game_ids_to_check):
            logger.info(f"SCHEDULER: Processing game {i+1}/{games_to_check_count} (PlayedID: {played_game_row_id})")
            check_single_game_update_and_status(db_path, f95_client, played_game_row_id)
            # Optional: time.sleep(1) # Consider if API rate limiting becomes an issue despite client's proxy use
            
    except sqlite3.Error as e:
        logger.error(f"SCHEDULER: Database error during scheduled_games_update_check: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"SCHEDULER: Unexpected error during scheduled_games_update_check: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
        logger.info(f"--- Scheduled games update check finished (processed {games_to_check_count} applicable games) ---")

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("F95Zone Update Checker - Application Started")

    # Load environment variables - No longer needed for credentials
    # if not load_dotenv(ENV_FILE_PATH):
    #     logger.error(f"Failed to load {ENV_FILE_PATH}. Please ensure it exists with credentials.")
    #     exit(1)
    #
    # f95_username = os.getenv("F95_USERNAME")
    # f95_password = os.getenv("F95_PASSWORD")
    #
    # if not f95_username or not f95_password:
    #     logger.error("F95_USERNAME or F95_PASSWORD not found in environment variables.")
    #     exit(1)
    # logger.info("Credentials loaded successfully.")

    # Initialize F95APIClient
    client = F95ApiClient() # No credentials passed
    
    try:
        # Login - No longer needed
        # logger.info(f"Attempting to log in as {f95_username}...")
        # login_result = client.login(f95_username, f95_password)
        #
        # if not login_result.get('success'):
        #     logger.error(f"Login failed: {login_result.get('message', 'Unknown error')}")
        #     exit(1)
        # logger.info("Login successful.")

        # Initialize Database
        initialize_database(DB_PATH)

        # Process RSS Feed for general updates
        process_rss_feed(DB_PATH, client)

        # Update completion statuses
        update_completion_statuses(DB_PATH, client)

        # Check for notifications
        notifications = check_for_my_updates(DB_PATH)
        if notifications:
            logger.info(f"--- {len(notifications)} UPDATES/NOTIFICATIONS FOUND ---")
            for notif in notifications:
                logger.info(f"Notification for Game: '{notif['game_name']}' (Played ID: {notif['played_game_id']})")
                logger.info(f"  URL: {notif['game_url']}")
                logger.info(f"  Current Version: {notif['current_version']}, Status: {notif['current_completed_status']}")
                for reason in notif['reasons']:
                    logger.info(f"  - {reason}")
                
                # In a real app, send notification here. 
                # For now, we'll just log and then update the notified status immediately.
                update_last_notified_status(DB_PATH, 
                                            notif['played_game_id'], 
                                            notif['new_notified_version'], 
                                            notif['new_notified_rss_pub_date'], 
                                            notif['new_notified_completion_status'])
            logger.info("--- FINISHED PROCESSING NOTIFICATIONS ---")
        else:
            logger.info("No new updates or notifications for your played games.")

    except Exception as e:
        logger.error(f"An unexpected error occurred in the main execution block: {e}", exc_info=True)
    finally:
        if 'client' in locals() and client:
            client.close_session()
        logger.info("F95Zone Update Checker - Application Finished") 