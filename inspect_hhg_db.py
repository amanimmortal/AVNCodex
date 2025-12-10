import sqlite3
import re
from urllib.parse import urlparse

DB_PATH = '/data/f95_games.db'

def _extract_thread_id(url):
    """(Copy of logic from services.py)"""
    if not url: return None
    match = re.search(r"\.(\d+)/?$", url)
    if match: return match.group(1)
    match = re.search(r"threads/.*?\.(\d+)", url)
    if match: return match.group(1)
    return None

def normalize_url(url):
    if not url: return ""
    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return clean.rstrip('/')

try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- Searching for Hero's Harem Guild ---")
    cursor.execute("SELECT * FROM games WHERE name LIKE '%Hero%'")
    rows = cursor.fetchall()
    
    for row in rows:
        print(f"ID: {row['id']}")
        print(f"Name: {row['name']}")
        print(f"URL: {row['f95_url']}")
        print(f"Version: {row['version']}")
        print(f"Status: {row['completed_status']}")
        
        tid = _extract_thread_id(row['f95_url'])
        print(f"Extracted Thread ID: {tid}")
        print(f"Normalized URL: {normalize_url(row['f95_url'])}")
        print("-" * 30)

except Exception as e:
    print(f"Error: {e}")
finally:
    if conn: conn.close()
