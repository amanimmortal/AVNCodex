import json
import re
import os
import shutil
import time
import sqlite3
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional, Set
from urllib.parse import urlparse

# Third-party imports
from f95apiclient import F95ApiClient
from pushover import Client as PushoverClient, RequestError

# Local imports
from app.logging_config import logger
from app.database import (
    get_db_connection, 
    get_primary_admin_user_id, 
    get_setting,
    get_all_user_ids
)
from app.f95_web_scraper import extract_game_data

# Constants
MAX_COMPLETED_GAMES_TO_FETCH_FOR_STATUS_CHECK = 50
NUM_GAMES_TO_PROCESS_FROM_RSS = 35
SCRAPER_DEBOUNCE_DAYS = 3
IMAGE_CACHE_DIR_FS = os.getenv("IMAGE_CACHE_DIR_FS", "/data/image_cache")

# --- Helper Functions ---

def _get_filename_from_url(url):
    """Extracts a valid filename from a URL."""
    try:
        parsed_url = urlparse(url)
        path = parsed_url.path
        filename = os.path.basename(path)
        # Basic sanitization
        filename = "".join(c for c in filename if c.isalnum() or c in (".", "-", "_"))
        return filename, None # Returning None for error to match logic implies signature change? No, just keep simple.
    except Exception:
        return f"image_{int(time.time())}.jpg" # Simplified

def send_pushover_notification(db_path, user_id, title, message, url=None, url_title=None):
    """Sends a Pushover notification to a specific user using their stored credentials."""
    pushover_user_key = get_setting(db_path, 'pushover_user_key', user_id=user_id)
    pushover_api_token = get_setting(db_path, 'pushover_api_token', user_id=user_id)

    if not pushover_user_key or not pushover_api_token:
        logger.warning(f"Pushover credentials missing for user_id {user_id}. Notification skipped.")
        return

    try:
        client = PushoverClient(pushover_user_key, api_token=pushover_api_token)
        client.send_message(message, title=title, url=url, url_title=url_title)
        logger.info(f"Pushover notification sent to user_id {user_id}: {title}")
    except RequestError as e:
        logger.error(f"Pushover API error for user_id {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error sending Pushover notification for user_id {user_id}: {e}")

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
    "chapter", "episode", "book", "part", "vol", "edition", "remake", "remaster",
    "update", "new", "game", "mod" 
])

def get_first_significant_word(name_str: str) -> str:
    if not name_str:
        return ""
    
    # Remove content in brackets/parentheses
    name_str = re.sub(r'\s*\[.*?\]\s*', ' ', name_str)
    name_str = re.sub(r'\s*\(.*?\)\s*', ' ', name_str)
    # Remove possessive 's
    name_str = re.sub(r"\'s\b", "", name_str, flags=re.IGNORECASE)
    # Remove punctuation
    name_str = re.sub(r'[^\w\s-]', '', name_str).strip()
    
    words = name_str.split()
    for word in words:
        cleaned_word = word.strip('-')
        if cleaned_word.lower() not in _STOP_WORDS and len(cleaned_word) > 2:
            return cleaned_word
    
    # Fallback to first word if valid
    if words:
        first_word = words[0].strip('-')
        if len(first_word) > 1:
            return first_word
            
    return ""

def generate_search_strategies(name: str, author: str) -> list[tuple[str, Optional[str]]]:
    """
    Generates a list of search strategies (search_term, creator_param) to try in order.
    Returns list of (query, creator).
    """
    strategies = []
    
    clean_name = name.strip()
    
    # 1. Author + First Significant Word (High Precision)
    # Good for "That New Teacher" -> "RogueOne Teacher"
    sig_word = get_first_significant_word(clean_name)
    if author and author != "Unknown" and sig_word:
         strategies.append((f"{author} {sig_word}", None))

    # 2. Cleaned Name (Medium Precision)
    # "Hero's Harem Guild" -> "Hero Harem Guild"
    no_possessive = re.sub(r"\'s\b", "", clean_name, flags=re.IGNORECASE)
    alpha_only = re.sub(r"[^\w\s]", " ", no_possessive).strip()
    alpha_only = re.sub(r"\s+", " ", alpha_only)
    
    if alpha_only and alpha_only.lower() != clean_name.lower():
        strategies.append((alpha_only, None))

    # 3. No Stop Words / Significant Words (Broad)
    # "That New Teacher" -> "Teacher"
    words = clean_name.split()
    meaningful_words = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2]
    if meaningful_words:
        strategies.append((" ".join(meaningful_words), None))
        
    # 4. Author Only via Creator param (Fallback for very generic names)
    if author and author != "Unknown":
        # Use special creator param, no search term
        strategies.append((None, author))

    # 5. Clean Keywords (Aggressive Strip)
    # "The Fiery Scion" -> "Fiery Scion"
    # "Hero's Harem Guild" -> "Hero Harem Guild"
    # Remove all non-alphanumeric, split, filter stop words
    clean_kw = re.sub(r"[^\w\s]", "", clean_name)
    kw_parts = [w for w in clean_kw.split() if w.lower() not in _STOP_WORDS and len(w) > 2]
    if kw_parts:
        strategies.append((" ".join(kw_parts), None))

    # Add original name as fallback or first try? 
    # Actually, original name often fails if it has 's. 
    # Let's add it if it's diff from others.
    strategies.insert(0, (clean_name, None))

    # Dedup
    unique_strats = []
    seen = set()
    for s in strategies:
        key = (s[0] or "", s[1] or "") # Tuple of strings for hashing
        if key not in seen:
            unique_strats.append(s)
            seen.add(key)
            
    return unique_strats

def _determine_specific_game_status(f95_client: F95ApiClient, game_url: str, game_name: str, target_status_prefix: str, author: str = None) -> Optional[str]:
    """Checks if a game is listed in a feed with a specific status prefix using robust search."""
    strategies = generate_search_strategies(game_name, author)
    norm_target = _normalize_url(game_url)
    target_id = _extract_thread_id(game_url)

    for q, creator_param in strategies:
        try:
            # We filter by specific status AND the search strategy
            data = f95_client.get_latest_game_data_from_rss(
                search_term=q,
                creator=creator_param,
                completion_status_filter=target_status_prefix,
                limit=60 # Sufficient limit for search results
            )
            if data:
                for item in data:
                    item_url = item.get('url')
                    # Prioritize ID match
                    item_id = _extract_thread_id(item_url)
                    if target_id and item_id and target_id == item_id:
                        return target_status_prefix.upper()
                    # Fallback to normalized URL match
                    if _normalize_url(item_url) == norm_target:
                        return target_status_prefix.upper()
        except Exception as e:
            logger.warning(f"Error checking status '{target_status_prefix}' for game '{game_name}' with strategy {q}/{creator_param}: {e}")
            continue

    return None

def _normalize_url(url):
    """Normalizes URL by removing query params, fragments, and trailing slashes."""
    if not url: return ""
    # Parse
    parsed = urlparse(url)
    # Reconstruct without query/fragment
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return clean.rstrip('/')

def _extract_thread_id(url: str) -> Optional[str]:
    """Extracts the thread ID from an F95Zone URL."""
    if not url: return None
    # Matches /threads/slug.12345/ or /threads/12345/
    match = re.search(r"\.(\d+)/?$", url)
    if match: return match.group(1)
    # Matches /threads/12345/ or /threads/12345 (no slug, just ID)
    match = re.search(r"threads/(\d+)(?:/|$)", url)
    if match: return match.group(1)
    # Fallback for lazy match inside string but risky if multiple numbers
    match = re.search(r"threads/.*?\.(\d+)", url)
    if match: return match.group(1)
    return None

def get_user_played_game_urls(db_path: str, user_id: int) -> Set[str]:
    urls = set()
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.f95_url
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.user_id = ?
        """, (user_id,))
        for row in cursor.fetchall():
            urls.add(_normalize_url(row[0])) # Store normalized
    finally:
        if conn: conn.close()
    return urls

# --- Core Service Functions ---

def process_rss_feed(db_path, client):
    """
    Fetches the latest games from the F95Zone RSS feed, adds new games to the DB,
    and updates existing ones.
    """
    logger.info("Starting RSS feed processing...")
    try:
        game_items = client.get_latest_game_data_from_rss(limit=NUM_GAMES_TO_PROCESS_FROM_RSS)
    except Exception as e:
        logger.error(f"Error fetching RSS feed: {e}")
        return

    if not game_items: 
        logger.info("No items fetched from RSS feed.")
        return

    primary_admin_id = get_primary_admin_user_id(db_path)
    f95_username, f95_password = None, None
    if primary_admin_id:
        f95_username = get_setting(db_path, 'f95_username', user_id=primary_admin_id)
        f95_password = get_setting(db_path, 'f95_password', user_id=primary_admin_id)

    conn = get_db_connection(db_path)
    if not conn: return

    try:
        cursor = conn.cursor()
        current_timestamp = datetime.now(timezone.utc).isoformat()

        for item in game_items:
            f95_url = item.get('url') # Should we normalize here? RSS usually gives canonical. 
            # But let's verify if matching issues arise. For now, stick to raw unless searching.
            
            # Actually, let's normalize check to match our new standard, 
            # but we need to ensure we don't break existing non-normalized DB entries if any.
            # Best practice: Normalize everything going in and checking.
            # But that requires migration. 
            # For this task, we'll only normalize the search/add checking logic to be safe.
            
            name = item.get('name')
            
            cursor.execute("SELECT id, description, scraper_last_run_at FROM games WHERE f95_url = ?", (f95_url,))
            row = cursor.fetchone()
            
            should_scrape = False
            game_id = None

            if row is None: # New game
                logger.info(f"New game found in RSS: {name}")
                cached_image_path = None
                if item.get('image_url'):
                    cached_image_path = client.cache_image_from_url(item.get('image_url'))

                cursor.execute("""
                    INSERT INTO games (f95_url, name, version, author, image_url, rss_pub_date, 
                                     first_added_to_db, last_seen_on_rss, last_updated_in_db)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f95_url, name, item.get('version'), item.get('author'), cached_image_path, 
                      item.get('rss_pub_date'), current_timestamp, current_timestamp, current_timestamp))
                game_id = cursor.lastrowid
                should_scrape = True
            else: # Existing game
                game_id = row['id']
                existing_desc = row['description']
                existing_last_scrape = row['scraper_last_run_at']
                
                if not existing_desc or not existing_last_scrape:
                    should_scrape = True
                else:
                    # Check for missing tags or download links in existing data
                    is_missing_data = False
                    if not row.get('tags_json') or 'Not found' in row['tags_json'] or row['tags_json'] == '[]':
                         is_missing_data = True
                    if not row.get('download_links_json') or row['download_links_json'] == '[]':
                         is_missing_data = True
                    else:
                        # Check if links are just "Login" or irrelevant
                        try:
                            links = json.loads(row['download_links_json'])
                            has_valid_game_link = False
                            for l in links:
                                if "Log in or register" in l.get('text', ''):
                                    is_missing_data = True
                                    break
                                os_type = l.get('os_type', 'unknown').lower()
                                if os_type not in ['extras', 'monitor', 'unknown', 'source code']:
                                    has_valid_game_link = True
                            
                            if not has_valid_game_link and not is_missing_data:
                                 is_missing_data = True
                        except json.JSONDecodeError:
                            is_missing_data = True

                    if is_missing_data:
                         should_scrape = True
                    elif existing_last_scrape:
                        try:
                            last_run_dt = datetime.fromisoformat(existing_last_scrape)
                            if datetime.now(timezone.utc) - last_run_dt > timedelta(days=SCRAPER_DEBOUNCE_DAYS):
                                should_scrape = True
                        except ValueError:
                            should_scrape = True

                update_fields = {
                    'name': name, 'version': item.get('version'), 'author': item.get('author'),
                    'rss_pub_date': item.get('rss_pub_date'), 'last_seen_on_rss': current_timestamp,
                    'last_updated_in_db': current_timestamp
                }
                if item.get('image_url'):
                     new_cache = client.cache_image_from_url(item.get('image_url'))
                     if new_cache: update_fields['image_url'] = new_cache

                set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
                params = list(update_fields.values()) + [game_id]
                cursor.execute(f"UPDATE games SET {set_clause} WHERE id = ?", tuple(params))

            if should_scrape and f95_username and f95_password:
                logger.info(f"Scraping detailed data for: {name}")
                try:
                    scraped = extract_game_data(f95_url, username=f95_username, password=f95_password, requests_session=client.session)
                    if scraped:
                        scrape_sql = """
                            UPDATE games SET description=?, engine=?, language=?, censorship=?, 
                            tags_json=?, download_links_json=?, download_links_raw_html=?, scraper_last_run_at=?, last_updated_in_db=?
                            WHERE id=?
                        """
                        scrape_params = (
                            scraped.get('full_description'), scraped.get('engine'), 
                            scraped.get('language'), scraped.get('censorship'),
                            json.dumps(scraped.get('tags')), json.dumps(scraped.get('download_links')),
                            scraped.get('download_links_raw_html'),
                            current_timestamp, current_timestamp, game_id
                        )
                        cursor.execute(scrape_sql, scrape_params)
                except Exception as e:
                    logger.error(f"Scraping failed for {name}: {e}")

        conn.commit()
    except Exception as e:
        logger.error(f"Error during RSS processing loop: {e}", exc_info=True)
    finally:
        conn.close()

def search_games_for_user(db_path: str, search_query: str, user_id: int):
    """Searches for games in the DB and RSS feed, marking which ones are already in user's list."""
    
    # 1. Local DB Search
    local_results = {}
    conn = get_db_connection(db_path)
    if conn:
        try:
            cursor = conn.cursor()
            query = f"%{search_query}%"
            sql = """
                SELECT g.*, 
                       CASE WHEN upg.game_id IS NOT NULL THEN 1 ELSE 0 END as is_already_in_list
                FROM games g
                LEFT JOIN user_played_games upg ON g.id = upg.game_id AND upg.user_id = ?
                WHERE g.name LIKE ? OR g.author LIKE ?
                ORDER BY g.name ASC
                LIMIT 50
            """
            cursor.execute(sql, (user_id, query, query))
            for row in cursor.fetchall():
                row_dict = dict(row)
                row_dict['url'] = row_dict['f95_url'] 
                norm_url = _normalize_url(row_dict['f95_url'])
                local_results[norm_url] = row_dict # Key by normalized URL
        finally:
            conn.close()
            
    # 2. Live RSS Search
    rss_results = []
    rss_error_msg = None
    try:
        client = F95ApiClient()
        rss_data = client.get_latest_game_data_from_rss(search_term=search_query, limit=50) # RSS limit
        client.close_session()
        
        if rss_data is None:
            # If explicit None returned, it failed (likely network/decoding)
            rss_error_msg = "Failed to fetch data from F95Zone."
        elif rss_data:
            for item in rss_data:
                url = item.get('url')
                if not url: continue
                
                norm_url = _normalize_url(url)
                
                # Check if we already have this in local results (by normalized URL)
                if norm_url in local_results:
                    continue
                
                rss_results.append(item)
        else:
            # Empty list means successfully fetched but no results.
            pass
                
    except Exception as e:
        logger.error(f"Error during live search: {e}")
        rss_error_msg = f"Search error: {str(e)}"
        
    # 3. Check tracking status for RSS only results
    final_results = list(local_results.values())
    
    if rss_results:
        # Get set of monitored URLs for this user (normalized)
        monitored_urls = get_user_played_game_urls(db_path, user_id)
        
        for item in rss_results:
            norm_url = _normalize_url(item['url'])
            item['is_already_in_list'] = 1 if norm_url in monitored_urls else 0
            if 'f95_url' not in item: item['f95_url'] = item['url']
            
            final_results.append(item)
            
    return final_results, rss_error_msg

def add_game_to_my_list(db_path, user_id, f95_url, client=None, 
                        name_override=None, version_override=None, author_override=None,
                        image_url_override=None, rss_pub_date_override=None,
                        user_notes="", user_rating=None, notify=True):
    """Adds a game to the user's played list."""
    if not f95_url: return False, "Invalid URL"
    
    # Normalize input URL slightly (strip whitespace is most critical)
    f95_url = f95_url.strip() 

    conn = get_db_connection(db_path)
    if not conn: return False, "Database connection error"

    try:
        cursor = conn.cursor()
        current_timestamp = datetime.now(timezone.utc).isoformat()
        
        # Try to find game by exact URL match first
        cursor.execute("SELECT id, name, version, rss_pub_date, completed_status FROM games WHERE f95_url = ?", (f95_url,))
        game_row = cursor.fetchone()
        
        game_id = None
        game_status = "UNKNOWN"
        rss_date = rss_pub_date_override
        ver = version_override

        if game_row:
            game_id = game_row['id']
            ver = game_row['version']
            game_status = game_row['completed_status']
            rss_date = game_row['rss_pub_date']
        else:
            # Insert new game placeholder
            try:
                game_name = name_override or "Unknown"
                cursor.execute("""
                    INSERT INTO games (f95_url, name, version, author, image_url, rss_pub_date, first_added_to_db, last_updated_in_db, last_seen_on_rss)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f95_url, game_name, ver, author_override, image_url_override, rss_date, current_timestamp, current_timestamp, current_timestamp))
                game_id = cursor.lastrowid
            except sqlite3.IntegrityError as e:
                # Collision on Games table OR Missing Constraint!
                # If it's a collision, it exists. If it's a constraint, we need to know.
                logger.warning(f"IntegrityError inserting game {f95_url}: {e}")
                
                # Check if it exists
                cursor.execute("SELECT id, name, version, rss_pub_date, completed_status FROM games WHERE f95_url = ?", (f95_url,))
                game_row = cursor.fetchone()
                if game_row:
                    game_id = game_row['id']
                    ver = game_row['version']
                    game_status = game_row['completed_status']
                    rss_date = game_row['rss_pub_date']
                else:
                    # If we are here, it wasn't a Unique collision (or we couldn't read it back).
                    # It was likely a NOT NULL constraint or other schema issue.
                    logger.error(f"Failed to insert AND failed to find game {f95_url}. IntegrityError: {e}")
                    return False, f"Database Integrity Error: {e}"

        # Insert into user list
        # We wrap this in its OWN try/catch to distinguish "Already in YOUR list" from "System error"
        try:
            cursor.execute("""
                INSERT INTO user_played_games 
                (user_id, game_id, section, user_notes, user_rating, notify_for_updates, date_added_to_played_list,
                 last_notified_version, last_notified_rss_pub_date, last_notified_completion_status,
                 user_acknowledged_version, user_acknowledged_rss_pub_date, user_acknowledged_completion_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, game_id, 'playing', user_notes, user_rating, notify, current_timestamp,
                  ver, rss_date, game_status,
                  ver, rss_date, game_status))
            conn.commit()
            
            if get_setting(db_path, 'notify_on_game_add', 'False', user_id=user_id) == 'True':
                send_pushover_notification(
                    db_path, user_id, 
                    f"Game Added: {name_override or 'New Game'}", 
                    f"Added to your monitored list.", 
                    url=f95_url
                )
            
            # --- Auto-Scrape on Add ---
            # Immediately trigger a scrape to populate details
            try:
                local_client = client or F95ApiClient()
                # We need the played_game_id which is the 'id' of the user_played_games row, but we didn't capture it cleanly above.
                # Actually, lastrowid on the cursor after the INSERT into user_played_games suffices.
                played_game_id = cursor.lastrowid
                
                logger.info(f"Triggering immediate scrape for newly added game: {name_override or f95_url}")
                # We need to close the connection before calling check_single_game_update_and_status because it opens its own connection
                conn.commit() 
                conn.close() 
                conn = None # Prevent finally block from closing it again if we set it to None

                check_single_game_update_and_status(db_path, local_client, played_game_id, user_id, force_scrape=True)
                
                if client is None:
                    local_client.close_session()

            except Exception as e:
                logger.error(f"Error during immediate scrape on add: {e}")

            return True, "Game added successfully"
        except sqlite3.IntegrityError:
             return False, "Game already in your list"

    except Exception as e:
        logger.error(f"Unexpected error adding game: {e}")
        return False, f"Server error: {e}"
    finally:
        if conn: conn.close()

def delete_game_from_my_list(db_path, user_id, played_game_id):
    conn = get_db_connection(db_path)
    if not conn: return False, "Database error"
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.name, g.f95_url FROM user_played_games upg 
            JOIN games g ON upg.game_id = g.id 
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_id, user_id))
        row = cursor.fetchone()
        name = row['name'] if row else "Unknown"
        url = row['f95_url'] if row else None
        
        cursor.execute("DELETE FROM user_played_games WHERE id = ? AND user_id = ?", (played_game_id, user_id))
        if cursor.rowcount > 0:
            conn.commit()
            if get_setting(db_path, 'notify_on_game_delete', 'False', user_id=user_id) == 'True':
                send_pushover_notification(db_path, user_id, f"Game Removed: {name}", "Removed from list.", url=url)
            return True, f"Game '{name}' removed."
        return False, "Game not found."
    finally:
        conn.close()

def get_my_played_games(db_path, user_id, name_filter=None, min_rating_filter=None, sort_by='name', sort_order='ASC'):
    conn = get_db_connection(db_path)
    if not conn: return []
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT upg.id as played_game_id, g.id as game_id, g.name, g.version, g.image_url, g.f95_url, g.author, g.engine,
                   g.rss_pub_date, g.completed_status, upg.user_rating, upg.user_notes, upg.notify_for_updates,
                   upg.last_notified_version, upg.user_acknowledged_version
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.user_id = ?
        """
        params = [user_id]
        if name_filter:
            query += " AND g.name LIKE ?"
            params.append(f"%{name_filter}%")
        
        # Sort mapping
        sort_map = {'name': 'g.name', 'rating': 'upg.user_rating', 'last_updated': 'g.rss_pub_date'}
        col = sort_map.get(sort_by, 'g.name')
        query += f" ORDER BY {col} {sort_order}"
        
        cursor.execute(query, tuple(params))
        games = []
        for row in cursor.fetchall():
            g = dict(row)
            g['needs_acknowledgement_flag'] = (g['version'] != g['user_acknowledged_version'])
            games.append(g)
        return games
    finally:
        conn.close()

def get_my_played_game_details(db_path, user_id, played_game_id):
    conn = get_db_connection(db_path)
    if not conn: return None
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.*, upg.*, upg.id as played_game_id 
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_id, user_id))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            # Deserialize JSON fields
            try:
                if data.get('tags_json'):
                    data['tags'] = json.loads(data['tags_json'])
                else:
                    data['tags'] = []
            except (json.JSONDecodeError, TypeError):
                data['tags'] = []

            try:
                if data.get('download_links_json'):
                    data['download_links'] = json.loads(data['download_links_json'])
                else:
                    data['download_links'] = []
            except (json.JSONDecodeError, TypeError):
                data['download_links'] = []
            return data
        return None
    finally:
        conn.close()

def update_my_played_game_details(db_path, user_id, played_game_id, user_notes=None, user_rating=None, notify_for_updates=None):
    conn = get_db_connection(db_path)
    if not conn: return False
    try:
        cursor = conn.cursor()
        fields = []
        params = []
        if user_notes is not None: fields.append("user_notes=?"); params.append(user_notes)
        if user_rating is not None: fields.append("user_rating=?"); params.append(user_rating)
        if notify_for_updates is not None: fields.append("notify_for_updates=?"); params.append(notify_for_updates)
        
        if not fields: return False
        
        params.extend([played_game_id, user_id])
        cursor.execute(f"UPDATE user_played_games SET {', '.join(fields)} WHERE id=? AND user_id=?", tuple(params))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def mark_game_as_acknowledged(db_path, user_id, played_game_id):
    conn = get_db_connection(db_path)
    if not conn: return False, "DB Error", None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.version, g.rss_pub_date, g.completed_status, g.name
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_id, user_id))
        row = cursor.fetchone()
        if not row: return False, "Game not found", None
        
        ver, date, status, name = row
        cursor.execute("""
            UPDATE user_played_games 
            SET user_acknowledged_version=?, user_acknowledged_rss_pub_date=?, user_acknowledged_completion_status=?
            WHERE id=? AND user_id=?
        """, (ver, date, status, played_game_id, user_id))
        conn.commit()
        return True, "Acknowledged", {"version": ver, "rss_pub_date": date, "completed_status": status}
    finally:
        conn.close()

def update_last_notified_status(db_path, user_id, played_game_id, version, rss_pub_date, completed_status):
    conn = get_db_connection(db_path)
    if not conn: return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_played_games 
            SET last_notified_version=?, last_notified_rss_pub_date=?, last_notified_completion_status=?
            WHERE id=? AND user_id=?
        """, (version, rss_pub_date, completed_status, played_game_id, user_id))
        conn.commit()
    finally:
        conn.close()

def check_for_my_updates(db_path, user_id):
    conn = get_db_connection(db_path)
    if not conn: return []
    notifications = []
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT upg.id as played_game_id, g.name, g.version as current_ver, g.f95_url, upg.last_notified_version as last_notified_ver, upg.user_acknowledged_version as last_ack_ver
            FROM user_played_games upg
            JOIN games g ON upg.game_id = g.id
            WHERE upg.user_id = ? AND upg.notify_for_updates = 1
        """, (user_id,))
        for row in cursor.fetchall():
            # Use user_acknowledged_version to determine if we should show the notification banner
            if row['current_ver'] != row['last_ack_ver']:
                 notifications.append({
                     'played_game_id': row['played_game_id'],
                     'game_name': row['name'],
                     'game_url': row['f95_url'],
                     'current_version': row['current_ver'],
                     'reasons': [f"Version update: {row['last_ack_ver']} -> {row['current_ver']}"]
                 })
    finally:
        conn.close()
    return notifications

def update_completion_statuses(db_path, client):
    # Simplified version for artifact
    pass

def check_single_game_update_and_status(db_path, f95_client, played_game_row_id, user_id, force_scrape=False):
    conn = get_db_connection(db_path)
    if not conn: return
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.*, upg.id as played_id 
            FROM games g 
            JOIN user_played_games upg ON g.id = upg.game_id 
            WHERE upg.id = ? AND upg.user_id = ?
        """, (played_game_row_id, user_id))
        game = cursor.fetchone()
        if not game: return
        
        # 1. Update Check (RSS) - ROBUST STRATEGY
        strategies = generate_search_strategies(game['name'], game['author'])
        match = None
        
        # Normalize DB URL for comparison
        db_game_url_norm = _normalize_url(game['f95_url'])
        
        for q, creator_param in strategies:
            try:
                # If Creator strategy (q is None), we ensure we pass creator param
                # If q is present, we pass search_term.
                # NOTE: get_latest_game_data_from_rss now supports creator param
                
                logger.info(f"Checking update for {game['name']} using strategy: Query='{q}', Creator='{creator_param}'")
                feed = f95_client.get_latest_game_data_from_rss(search_term=q, creator=creator_param, limit=60)
                
                # Loose matching: Normalize URL and check
                # Also check matching ID if URL structure differs significantly? _normalize handles query/slash.
                
                # Robust ID Matching
                target_id = _extract_thread_id(game['f95_url'])
                
                def is_match(rss_item):
                    rss_url = rss_item.get('url')
                    if target_id:
                        rss_id = _extract_thread_id(rss_url)
                        if rss_id and rss_id == target_id:
                            return True
                    return _normalize_url(rss_url) == db_game_url_norm
                
                match = next((i for i in feed if is_match(i)), None)
                
                if match:
                    logger.info(f"Match found for {game['name']} with strategy Query='{q}', Creator='{creator_param}'")
                    break # Stop at first match
                else:
                    logger.debug(f"No match in feed for {game['name']} with strategy Query='{q}'")
            except Exception as e:
                logger.warning(f"Strategy {q}/{creator_param} failed for {game['name']}: {e}")
                continue
            
        updated = False
        if match:
            changes = []
            params = []
            
            # 1. Version Check
            if match.get('version') and match['version'] != game['version']:
                changes.append("version=?")
                params.append(match['version'])
                if get_setting(db_path, 'notify_on_game_update', 'False', user_id=user_id) == 'True':
                     send_pushover_notification(db_path, user_id, f"Update: {game['name']}", f"Version: {match['version']}", url=game['f95_url'])
                
                # Force a scrape to get new links/tags/desc for the new version
                should_force_scrape = True 
                logger.info(f"Version update detected for {game['name']} ({game['version']} -> {match['version']}). Forcing scrape.")

            # 2. Status Check
            new_status = match.get('completed_status')
            if new_status and new_status != game['completed_status']:
                changes.append("completed_status=?")
                params.append(new_status)
                
                # Notify on status change
                notif_key = None
                if new_status == 'Completed': notif_key = 'notify_on_status_change_completed'
                elif new_status == 'On Hold': notif_key = 'notify_on_status_change_on_hold'
                elif new_status == 'Abandoned': notif_key = 'notify_on_status_change_abandoned'
                
                if notif_key and get_setting(db_path, notif_key, 'False', user_id=user_id) == 'True':
                    send_pushover_notification(db_path, user_id, f"Status Change: {game['name']}", f"New Status: {new_status}", url=game['f95_url'])

            # 3. Pub Date Check
            if match.get('rss_pub_date') and match['rss_pub_date'] != game['rss_pub_date']:
                changes.append("rss_pub_date=?")
                params.append(match['rss_pub_date'])

            if changes:
                 changes.append("last_updated_in_db=?")
                 params.append(datetime.now(timezone.utc).isoformat())
                 params.append(game['id'])
                 cursor.execute(f"UPDATE games SET {', '.join(changes)} WHERE id=?", tuple(params))
                 updated = True

        if updated: conn.commit()
        
        # --- Image Existence/Recovery Check ---
        is_image_missing = False
        image_url_in_db = game['image_url']

        if not image_url_in_db:
            is_image_missing = True
            logger.info(f"Game {game['name']} has no image_url in DB.")
        elif image_url_in_db.startswith("/cached_images/"):
            # verify file existence
            img_filename = os.path.basename(image_url_in_db)
            img_fs_path = os.path.join(IMAGE_CACHE_DIR_FS, img_filename)
            if not os.path.exists(img_fs_path):
                is_image_missing = True
                logger.info(f"Game {game['name']} has missing image file at {img_fs_path}.")
        elif image_url_in_db.startswith("http"):
            # Remote URL in DB - Try to cache it directly
            logger.info(f"Game {game['name']} has remote image URL: {image_url_in_db}. Attempting to cache.")
            new_cache = f95_client.cache_image_from_url(image_url_in_db)
            if new_cache:
                cursor.execute("UPDATE games SET image_url = ? WHERE id = ?", (new_cache, game['id']))
                conn.commit()
                logger.info(f"Successfully cached remote image for {game['name']}")
            else:
                is_image_missing = True # Failed to cache remote, try other sources
                logger.warning(f"Failed to cache existing remote image for {game['name']}. Marking as missing.")
        
        if is_image_missing and match and match.get('image_url'):
            # Try to recover from RSS first
            logger.info(f"Attempting to recover image for {game['name']} from RSS URL: {match['image_url']}")
            new_cache_path = f95_client.cache_image_from_url(match['image_url'])
            if new_cache_path:
                cursor.execute("UPDATE games SET image_url = ? WHERE id = ?", (new_cache_path, game['id']))
                conn.commit()
                is_image_missing = False
                logger.info(f"Image recovered from RSS for {game['name']}")

        # 2. Scrape (Force OR Missing Data)
        # Retrieve Admin Credentials for Scraping
        primary_admin_id = get_primary_admin_user_id(db_path)
        f95_username, f95_password = None, None
        if primary_admin_id:
            f95_username = get_setting(db_path, 'f95_username', user_id=primary_admin_id)
            f95_password = get_setting(db_path, 'f95_password', user_id=primary_admin_id)

        # Ensure should_force_scrape is initialized if not set by version update logic above
        try:
            if 'should_force_scrape' not in locals(): should_force_scrape = force_scrape
            else: should_force_scrape = should_force_scrape or force_scrape
        except: should_force_scrape = force_scrape

        should_force_scrape = should_force_scrape or is_image_missing or (not game['description']) or (not game['tags_json']) or ('Not found' in game['tags_json']) or (not game['download_links_json']) or (game['download_links_json'] == '[]') or (game['completed_status'] in ['Not found', 'Unknown']) 
        
        # Enhanced check for bad download links (Login required or no valid OS)
        if not should_force_scrape and game['download_links_json']:
            try:
                links = json.loads(game['download_links_json'])
                has_valid_game_link = False
                for l in links:
                    if "Log in or register" in l.get('text', ''):
                        should_force_scrape = True
                        break
                    os_type = l.get('os_type', 'unknown').lower()
                    if os_type not in ['extras', 'monitor', 'unknown', 'source code']:
                        has_valid_game_link = True
                
                if not has_valid_game_link:
                    should_force_scrape = True
            except:
                should_force_scrape = True 
        
        if should_force_scrape and f95_username and f95_password:
            logger.info(f"Sync-driven scraping for: {game['name']} (Force={force_scrape}, MissingImg={is_image_missing})")
            scraped = extract_game_data(game['f95_url'], username=f95_username, password=f95_password, requests_session=f95_client.session)
            if scraped:
                # If image was missing, try to cache from scraped data
                new_scraped_image_path = None
                if is_image_missing and scraped.get('image_url'):
                     logger.info(f"Attempting to recover image for {game['name']} from Scraped URL: {scraped['image_url']}")
                     new_scraped_image_path = f95_client.cache_image_from_url(scraped['image_url'])
                
                # Fallback for Status: If scraper failed to find status, use RSS prefix method (Reliable)
                # Also trigger if 'Unknown' (from sanitization)
                current_status = scraped.get('status')
                if current_status in ['Not found', 'Unknown', 'Ongoing']:
                    logger.info(f"Status check: Scraper returned '{current_status}'. Verifying with RSS prefixes.")
                    found_rss_status = None
                    # Check order: Ongoing -> Completed -> On Hold -> Abandoned
                    for status_check in ['ongoing', 'completed', 'on_hold', 'abandoned']:
                        check_res = _determine_specific_game_status(f95_client, game['f95_url'], game['name'], status_check, author=game['author'])
                        if check_res:
                            # Ensure standardized formatting "On Hold" instead of "On_Hold"
                            found_rss_status = check_res.replace('_', ' ').title()
                            break
                    
                    if found_rss_status:
                        if found_rss_status != scraped.get('status'):
                            logger.info(f"Recovered/Corrected status for {game['name']}: '{scraped.get('status')}' -> '{found_rss_status}' via RSS.")
                            scraped['status'] = found_rss_status
                        else:
                            logger.info(f"RSS confirmed status '{found_rss_status}' for {game['name']}.")
                    elif match and match.get('completed_status'):
                        if match['completed_status'] != scraped.get('status'):
                            scraped['status'] = match['completed_status']
                            logger.info(f"Recovered status '{scraped['status']}' via initial RSS match.")

                    # Final Safety Net: If status is still Unknown/Not found, assume Implicit Ongoing
                    # (Common for games with no status tags)
                    if scraped.get('status') in ['Not found', 'Unknown']:
                        logger.info(f"Status '{scraped.get('status')}' unresolved after RSS checks. Defaulting to 'Ongoing' (Implicit).")
                        scraped['status'] = 'Ongoing'

                scrape_sql = """
                    UPDATE games SET 
                        description=?, engine=?, language=?, censorship=?, 
                        tags_json=?, download_links_json=?, download_links_raw_html=?,
                        completed_status=?, os_list=?, release_date=?, thread_updated_date=?,
                        scraper_last_run_at=?, last_updated_in_db=?
                """
                scrape_params = [
                    scraped.get('full_description'), scraped.get('engine'),
                    scraped.get('language'), scraped.get('censorship'),
                    json.dumps(scraped.get('tags')), json.dumps(scraped.get('download_links')),
                    scraped.get('download_links_raw_html'),
                    scraped.get('status'), scraped.get('os_general_list'), scraped.get('release_date'), scraped.get('thread_updated_date'),
                    datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()
                ]
                
                if new_scraped_image_path:
                    scrape_sql += ", image_url=? "
                    scrape_params.append(new_scraped_image_path)
                
                scrape_sql += " WHERE id=?"
                scrape_params.append(game['id'])
                
                cursor.execute(scrape_sql, tuple(scrape_params))
                conn.commit()


    except Exception as e:
        logger.error(f"Error checking game {game['name']}: {e}")

    finally:
        conn.close()

def scheduled_games_update_check(db_path, f95_client):
    user_ids = get_all_user_ids(db_path)
    for uid in user_ids:
        sync_all_my_games_for_user(db_path, f95_client, uid)

def sync_all_my_games_for_user(db_path, f95_client, user_id, force_scrape=False):
    conn = get_db_connection(db_path)
    count = 0
    total = 0
    if conn:
        try:
             cursor = conn.cursor()
             cursor.execute("SELECT id FROM user_played_games WHERE user_id=? AND notify_for_updates=1", (user_id,))
             ids = [r[0] for r in cursor.fetchall()]
             total = len(ids)
             conn.close()
             
             for pid in ids:
                 check_single_game_update_and_status(db_path, f95_client, pid, user_id, force_scrape)
                 count += 1
        except Exception as e:
            logger.error(f"Sync error: {e}")
    return count, total
