import sqlite3
import os
from run_app import DB_PATH
from app.database import get_db_connection

def simulate_update(game_name_query="Eternum"):
    print(f"Connecting to database at: {DB_PATH}")
    conn = get_db_connection(DB_PATH)
    if not conn:
        print("Failed to connect to database.")
        return

    try:
        cursor = conn.cursor()
        
        # 1. Find the game
        print(f"Searching for game matching '{game_name_query}'...")
        cursor.execute("SELECT id, name, version FROM games WHERE name LIKE ?", (f"%{game_name_query}%",))
        game = cursor.fetchone()
        
        if not game:
            print(f"No game found matching '{game_name_query}'. Please add it first.")
            return

        game_id = game['id']
        current_version = game['version']
        print(f"Found game: {game['name']} (ID: {game_id}) - Current Version: {current_version}")

        # 2. Downgrade the version
        print("Downgrading version to '0.0.0' to simulate an available update...")
        cursor.execute("UPDATE games SET version = '0.0.0' WHERE id = ?", (game_id,))
        
        # 3. reset notification flags for user
        # We also want to ensure the USER's last notified version is reset, otherwise they might not get notified again
        # if the system thinks they were already notified of '0.1' and the new one is '0.1'.
        # Actually, if we set game version to 0.0.0, and the RSS has 0.7, the system sees 0.7 != 0.0.0 -> UPDATE.
        # Then it checks if user was notified?
        # Let's peek at services.py logic:
        # if match.get('version') != game['version']: -> Update detected.
        #    send_pushover_notification(...)
        # It doesn't seem to explicitly check 'last_notified_version' inside check_single_game_update_and_status before sending?
        # It just sends it if 'notify_on_game_update' is True.
        # But to be safe, let's reset user's known version too.
        
        cursor.execute("UPDATE user_played_games SET last_notified_version = '0.0.0', user_acknowledged_version = '0.0.0' WHERE game_id = ?", (game_id,))
        
        conn.commit()
        print("Success! Version downgraded.")
        print("-" * 30)
        print(f"Now go to the Web UI -> My Games.")
        print(f"Click 'Sync All Monitored' (or Sync button on the card).")
        print(f"The system should detect the 'update' from 0.0.0 to {current_version} and send a notification.")
        print("-" * 30)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    game_name = input("Enter game name to simulate update for (default: Eternum): ").strip()
    if not game_name:
        game_name = "Eternum"
    simulate_update(game_name)
