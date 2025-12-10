import os
import sys
import logging
from app.f95_web_scraper import extract_game_data, login_to_f95zone
from app.database import get_primary_admin_user_id, get_setting, initialize_database
from playwright.sync_api import sync_playwright

# Setup minimal logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VERIFIER")

DB_PATH = "D:/data/f95_games.db"

import argparse

def verify_scraper():
    logger.info("--- Starting Scraper Robustness Verification ---")
    
    parser = argparse.ArgumentParser(description="Verify F95Zone Scraper")
    parser.add_argument("--username", help="F95Zone Username")
    parser.add_argument("--password", help="F95Zone Password")
    args = parser.parse_args()

    username = args.username
    password = args.password

    if not username or not password:
        # Get credentials from DB if not provided
        primary_admin_id = get_primary_admin_user_id(DB_PATH)
        if primary_admin_id:
            username = get_setting(DB_PATH, 'f95_username', user_id=primary_admin_id)
            password = get_setting(DB_PATH, 'f95_password', user_id=primary_admin_id)

    if not username or not password:
        logger.error("F95 credentials not found (in DB or CLI args). Usage: python verify_scraping.py --username U --password P")
        return

    # Test Cases: (URL, Expected Status or Feature)
    test_cases = [
        ("https://f95zone.to/threads/heros-harem-guild-v0-1-6-m-k-production.42173/", "Abandoned"), # "Abandoned"
        ("https://f95zone.to/threads/city-of-broken-dreamers-v1-01-phillygames.13645/", "Completed"), # "Completed" + Complex Downloads
        ("https://f95zone.to/threads/long-way-v0-14-ch-9-mrt.58622/", "Ongoing"), # Typical Layout
    ]

    for url, key_feature in test_cases:
        logger.info(f"\nTesting URL: {url} (Expect: {key_feature})")
        try:
            data = extract_game_data(url, username=username, password=password)
            
            if not data:
                logger.error("FAILED: No data returned.")
                continue

            # Verification Checks
            status = data.get('status')
            links = data.get('download_links')
            tags = data.get('tags')
            
            logger.info(f"  -> Detected Status: {status}")
            logger.info(f"  -> Found {len(links)} download links.")
            logger.info(f"  -> Found {len(tags) if isinstance(tags, list) else 0} tags.")

            success = True
            if status != key_feature:
                if key_feature == "Abandoned" and "abandoned" in str(status).lower(): pass # Close enough
                elif key_feature == "Completed" and "complete" in str(status).lower(): pass
                elif key_feature == "Ongoing" and "ongoing" in str(status).lower(): pass
                else:
                    logger.warning(f"  [!] Status mismatch: Expected ~'{key_feature}', got '{status}'")
                    # It might not match if the live status changed, so warning not error.

            if not links:
                logger.error("  [!] FAILED: No download links found!")
                success = False
            else:
                 # Check logic
                 for l in links:
                     logger.info(f"      - [{l.get('os_type')}] {l.get('text')[:30]}... -> {l.get('url')[:40]}...")

            if not tags or tags == ["Not found"]:
                 logger.warning("  [!] Warning: No tags found.")
            
            if success:
                logger.info("  [+] PASSED Basic Checks")

        except Exception as e:
            logger.error(f"  [!] EXCEPTION: {e}", exc_info=True)

    logger.info("\n--- Verification Complete ---")

if __name__ == "__main__":
    verify_scraper()
