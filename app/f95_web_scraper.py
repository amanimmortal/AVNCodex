import requests
from bs4 import BeautifulSoup
import time # Added for potential waits
from playwright.sync_api import sync_playwright # Added for Playwright
import re # Added for regular expressions
import logging
from datetime import datetime

# Create a logger specific to this module
logger_scraper = logging.getLogger(__name__) # Use __name__ for module-level logger

# --- Playwright Login Function ---
def login_to_f95zone(page, username, password, target_url_after_login=None):
    """
    Logs into F95zone using Playwright.
    Assumes the page is already navigated to the login page.
    If target_url_after_login is provided, navigates there and checks login status on that page.
    """
    try:
        logger_scraper.info("Login Attempt: Initiated.")
        
        page.fill("input[name='login']", username)
        logger_scraper.info("Login Attempt: Filled username.")
        page.fill("input[name='password']", password)
        logger_scraper.info("Login Attempt: Filled password.")

        # --- ADDED SCREENSHOT: After fields are filled ---
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            screenshot_path = f"/data/debug_screenshot_02_login_fields_filled_{timestamp}.png"
            page.screenshot(path=screenshot_path, full_page=True)
            logger_scraper.info(f"Login Attempt: Saved screenshot (fields filled) to '{screenshot_path}'")
        except Exception as e_screenshot:
            logger_scraper.error(f"Login Attempt: Failed to take screenshot (fields filled): {e_screenshot}")
        # --- END SCREENSHOT ---

        login_button = page.locator("button.button--primary", has_text="Log in")
        
        if not login_button or login_button.count() == 0: 
            logger_scraper.warning("Login Attempt: Primary login button not found. Trying fallback selector for form button...")
            login_button = page.locator("form.block[action='/login/login'] button[type='submit']")
        
        if not login_button or login_button.count() == 0:
            logger_scraper.warning("Login Attempt: Fallback form button not found. Trying get_by_role('button', name=re.compile(r'log in', re.IGNORECASE))...")
            login_button = page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))

        if login_button.count() > 0:
            button_to_click = login_button.first
            try:
                logger_scraper.info("Login Attempt: Found login button. Attempting click now...")
                button_to_click.click(timeout=25000) 
                logger_scraper.info("Login Attempt: Playwright click() call for login button completed.")
                # It's good to wait for some navigation or indicator that the login click has had an effect.
                # This could be a specific element, or a general load state change.
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000) # Wait for DOM after click
                    logger_scraper.info(f"Login Attempt: DOM loaded after login click. Current URL: {page.url}")
                    # --- ADDED SCREENSHOT: After login click and DOM load ---
                    try:
                        timestamp = time.strftime("%Y%m%d-%H%M%S")
                        screenshot_path = f"/data/debug_screenshot_03_post_login_click_landing_{timestamp}.png"
                        page.screenshot(path=screenshot_path, full_page=True)
                        logger_scraper.info(f"Login Attempt: Saved screenshot (post-click landing) to '{screenshot_path}'")
                    except Exception as e_screenshot:
                        logger_scraper.error(f"Login Attempt: Failed to take screenshot (post-click landing): {e_screenshot}")
                    # --- END SCREENSHOT ---
                except Exception as e_dom_wait:
                    logger_scraper.warning(f"Login Attempt: Timeout waiting for DOM load after login click. Current URL: {page.url}. Error: {e_dom_wait}")

            except Exception as e_click_wait:
                logger_scraper.error(f"LOGIN ERROR: Error during the click action itself: {e_click_wait}")
                return False
        else:
            logger_scraper.error("LOGIN ERROR: Could not find a clickable login button on the page after all fallbacks.")
            logger_scraper.error(f"LOGIN ERROR: Current URL when failing to find login button: {page.url}")
            return False

        # Check for initial login success indicators on the page we landed on (often the homepage or a redirect)
        logger_scraper.info(f"Login Attempt: Checking for login indicators on current page ({page.url}) after form submission.")
        
        # Check for username on the current page (which should be f95zone.to general site after login)
        username_element_on_redirect = page.query_selector(f"div.p-account.p-navgroup--member span.p-navgroup-linkText:text-matches('{re.escape(username)}')")
        
        if username_element_on_redirect:
            logger_scraper.info(f"Login Attempt: Initial indicators (username: '{username}') suggest login successful on {page.url}.")
            if target_url_after_login:
                logger_scraper.info(f"Login Attempt: Initial login successful. Navigating to target URL: {target_url_after_login}")
                try:
                    page.goto(
                        target_url_after_login,
                        timeout=60000,  # MODIFIED
                        wait_until="domcontentloaded"  # MODIFIED
                    )
                    current_url_after_target_nav = page.url
                    logger_scraper.info(f"Login Attempt: Navigation to target URL {target_url_after_login} complete. Current URL: {current_url_after_target_nav}")
                    page.wait_for_load_state("domcontentloaded", timeout=15000) # ensure DOM is ready
                    page.wait_for_timeout(3000) # give a bit of settle time
                    
                    # Now, definitively check for login on the target page
                    username_element_on_target = page.query_selector(f"div.p-account.p-navgroup--member span.p-navgroup-linkText:text-matches('{re.escape(username)}')")
                    if username_element_on_target:
                        username_text_on_target = username_element_on_target.inner_text()
                        logger_scraper.info(f"Login Attempt: CONFIRMED LOGGED IN on target page {target_url_after_login} based on username text: '{username_text_on_target}'")
                        
                        # Save screenshot of the successfully loaded and logged-in target page
                        timestamp_final_target = datetime.now().strftime("%Y%m%d-%H%M%S")
                        final_target_screenshot_path = f"/data/debug_screenshot_03a_target_page_login_confirmed_{timestamp_final_target}.png"
                        try:
                            page.screenshot(path=final_target_screenshot_path)
                            logger_scraper.info(f"Login Attempt: Saved screenshot (target page login confirmed) to '{final_target_screenshot_path}'")
                        except Exception as e:
                            logger_scraper.error(f"Login Attempt: Error saving final target page screenshot: {e}")
                        
                        return True # Successfully logged in and on target page
                    else:
                        logger_scraper.warning(f"Login Attempt: COULD NOT CONFIRM LOGIN on target page {target_url_after_login}. Username element not found after navigation.")
                        # Save screenshot for debugging this specific failure case
                        timestamp_target_fail = datetime.now().strftime("%Y%m%d-%H%M%S")
                        target_fail_screenshot_path = f"/data/debug_screenshot_03b_target_page_login_FAIL_{timestamp_target_fail}.png"
                        try:
                            page.screenshot(path=target_fail_screenshot_path)
                            logger_scraper.info(f"Login Attempt: Saved screenshot (target page login fail) to '{target_fail_screenshot_path}'")
                        except Exception as e:
                            logger_scraper.error(f"Login Attempt: Error saving target page failure screenshot: {e}")
                        return False
                except TimeoutError as e:
                    logger_scraper.error(f"Login Attempt: Timeout navigating to or checking target URL {target_url_after_login}: {e}")
                    return False
                except Exception as e:
                    logger_scraper.error(f"Login Attempt: Error navigating to or checking target URL {target_url_after_login}: {e}")
                    # You might want to save a screenshot here too
                    timestamp_nav_error = datetime.now().strftime("%Y%m%d-%H%M%S")
                    nav_error_screenshot_path = f"/data/debug_screenshot_03c_target_page_nav_ERROR_{timestamp_nav_error}.png"
                    try:
                        page.screenshot(path=nav_error_screenshot_path)
                        logger_scraper.info(f"Login Attempt: Saved screenshot (target page navigation error) to '{nav_error_screenshot_path}'")
                    except Exception as se:
                        logger_scraper.error(f"Login Attempt: Error saving navigation error screenshot: {se}")
                    return False
            else:
                # No target URL, so initial login success is enough
                logger_scraper.info("Login Attempt: Login successful on main page, no target_url_after_login provided.")
                return True 
        else:
            # Attempt to find "Login / Register" button as a sign of NOT being logged in
            login_register_button_after_redirect = page.query_selector("a.p-navgroup-link--logIn") # More specific selector
            if login_register_button_after_redirect:
                logger_scraper.warning(f"Login Attempt: Login FAILED. 'Login / Register' button found on {page.url} after login attempt.")
            else:
                logger_scraper.warning(f"Login Attempt: Login FAILED. Username element not found on {page.url}, and 'Login / Register' button also not found. Unknown state.")
            
            # Save screenshot for debugging login failure on redirect page
            timestamp_redirect_fail = datetime.now().strftime("%Y%m%d-%H%M%S")
            redirect_fail_screenshot_path = f"/data/debug_screenshot_03d_redirect_page_login_FAIL_{timestamp_redirect_fail}.png"
            try:
                page.screenshot(path=redirect_fail_screenshot_path)
                logger_scraper.info(f"Login Attempt: Saved screenshot (redirect page login fail) to '{redirect_fail_screenshot_path}'")
            except Exception as e:
                logger_scraper.error(f"Login Attempt: Error saving redirect page failure screenshot: {e}")
            return False

    except TimeoutError as e:
        logger_scraper.error(f"LOGIN ERROR: Timeout during login attempt: {e}")
        return False
    except Exception as e:
        logger_scraper.error(f"LOGIN ERROR: An unexpected error occurred during login: {e}", exc_info=True)
        return False

def get_page_html_with_playwright(page, url):
    """Fetches HTML from a URL using an existing Playwright page object and returns its content."""
    try:
        logger_scraper.info(f"Playwright Nav: Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        logger_scraper.info(f"Playwright Nav: Successfully navigated to {url}. Current URL: {page.url}. Waiting for page to settle.")
        page.wait_for_timeout(3000) # Give page time for JS rendering after DOM load
        html_content = page.content()
        if not html_content:
            logger_scraper.warning(f"Playwright Nav: Fetched empty HTML content from {url}")
        return html_content
    except Exception as e:
        logger_scraper.error(f"Playwright Nav: Error fetching URL {url}: {e}", exc_info=True)
        return None

def get_soup(url):
    # This function is not currently used when Playwright is active for the main extraction.
    # Kept for potential direct BS4 usage or other utilities.
    try:
        headers = { # Mimic a browser to avoid potential blocks
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        logger_scraper.error(f"Error fetching URL {url}: {e}", exc_info=True)
        return None

def extract_game_data(game_thread_url, username=None, password=None):
    """
    Extracts detailed information from an F95zone game thread page.
    Uses Playwright for navigation and login if credentials are provided.
    """
    logger_scraper.info(f"EXTRACT_GAME_DATA: Entered function. Initial game_thread_url='{game_thread_url}', Username provided: {'Yes' if username else 'No'}.")
    logger_scraper.info(f"EXTRACT_GAME_DATA: Starting extraction for: {game_thread_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            # Add viewport settings if needed, e.g., viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        final_page_logged_in_status = False

        if username and password:
            try:
                logger_scraper.info("EXTRACT_GAME_DATA: Navigating to login page (https://f95zone.to/login/login) to ensure fresh login attempt.")
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=30000)
                logger_scraper.info(f"EXTRACT_GAME_DATA: On login page. Current URL: {page.url}. Attempting login via login_to_f95zone function, targeting game thread url directly.")
                
                try:
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    screenshot_path = f"/data/debug_screenshot_01_initial_login_page_{timestamp}.png"
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger_scraper.info(f"EXTRACT_GAME_DATA: Saved screenshot (initial login page) to '{screenshot_path}'")
                except Exception as e_screenshot:
                    logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take screenshot (initial login page): {e_screenshot}")

                final_page_logged_in_status = login_to_f95zone(page, username, password, target_url_after_login=game_thread_url)
                logger_scraper.info(f"EXTRACT_GAME_DATA: login_to_f95zone (targeting game page) returned: {final_page_logged_in_status}. Current URL: {page.url}")

            except Exception as e_login_nav:
                logger_scraper.error(f"EXTRACT_GAME_DATA: Error during the overall login and navigation process: {e_login_nav}", exc_info=True)
                final_page_logged_in_status = False
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                error_screenshot_path = f"/data/debug_screenshot_EXTRACT_error_{timestamp}.png"
                try:
                    page.screenshot(path=error_screenshot_path, full_page=True)
                    logger_scraper.info(f"EXTRACT_GAME_DATA: Saved error screenshot to '{error_screenshot_path}'")
                except Exception as es_err:
                    logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take error screenshot during EXCEPTION: {es_err}")
        else:
            logger_scraper.info("EXTRACT_GAME_DATA: No credentials provided. Proceeding as anonymous.")
            try:
                logger_scraper.info(f"EXTRACT_GAME_DATA: Navigating to {game_thread_url} (anonymous).")
                page.goto(game_thread_url, wait_until="networkidle", timeout=45000) # networkidle might be better for complex pages
                logger_scraper.info(f"EXTRACT_GAME_DATA: Successfully navigated to {game_thread_url}. Current URL: {page.url}")
                page.wait_for_load_state("domcontentloaded", timeout=10000) 
                page.wait_for_timeout(3000) # Increased settle time
            except Exception as e_anon_nav:
                logger_scraper.error(f"EXTRACT_GAME_DATA: Error navigating to game page {game_thread_url} (anonymous): {e_anon_nav}", exc_info=True)
                browser.close()
                return None
        
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            screenshot_filename = f"debug_screenshot_04_gamepage_FINAL_{timestamp}.png"
            screenshot_path = f"/data/{screenshot_filename}" 
            page.screenshot(path=screenshot_path, full_page=True)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Saved FINAL debug screenshot to '{screenshot_path}'. Logged in: {final_page_logged_in_status}")
        except Exception as e_screenshot:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take FINAL debug screenshot: {e_screenshot}")

        if not final_page_logged_in_status and (username and password):
             logger_scraper.warning(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url}, but login was NOT confirmed on the game page. Data might be incomplete.")
        elif final_page_logged_in_status:
             logger_scraper.info(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url} with confirmed login.")
        else: # Anonymous
             logger_scraper.info(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url} as anonymous user.")

        logger_scraper.info("EXTRACT_GAME_DATA: Attempting to find and click spoiler buttons...")
        spoiler_buttons_selector = "button.bbCodeSpoiler-button"
        try:
            # It's better to wait for the buttons to be present before trying to query them all
            page.wait_for_selector(spoiler_buttons_selector, timeout=10000) # Wait up to 10s for first spoiler button
            spoiler_buttons = page.query_selector_all(spoiler_buttons_selector)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Found {len(spoiler_buttons)} spoiler buttons.")
            for i, button_element in enumerate(spoiler_buttons):
                try:
                    # Scroll into view if necessary, then click.
                    button_element.scroll_into_view_if_needed(timeout=5000)
                    if button_element.is_visible() and button_element.is_enabled():
                        button_element.click(timeout=5000) 
                        page.wait_for_timeout(1500) # Increased wait after each spoiler click for content to load
                        logger_scraper.debug(f"EXTRACT_GAME_DATA: Clicked spoiler button {i+1}.")
                    else:
                        logger_scraper.debug(f"EXTRACT_GAME_DATA: Spoiler button {i+1} is not visible or enabled, skipping.")
                except Exception as e_click_spoiler:
                    logger_scraper.warning(f"EXTRACT_GAME_DATA: Could not click or process spoiler button {i+1}: {e_click_spoiler}")
            logger_scraper.info("EXTRACT_GAME_DATA: Finished attempting to click spoiler buttons.")
            page.wait_for_timeout(3000) # General wait after all spoiler clicks
        except Exception as e_find_spoilers:
            logger_scraper.info(f"EXTRACT_GAME_DATA: No spoiler buttons found or error interacting with them: {e_find_spoilers}") # Info level if none found

        logger_scraper.debug(f"EXTRACT_GAME_DATA: Getting HTML content after spoiler clicks. Current URL: {page.url}")
        html_content = page.content()
        
        if not html_content:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to get HTML content for {game_thread_url} using Playwright.")
            browser.close()
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        browser.close()
        logger_scraper.info(f"EXTRACT_GAME_DATA: Browser closed for {game_thread_url}.")

        # --- Initialize Data Dictionary ---
        data = {
            "url": game_thread_url,
            "title_full_raw": None, # Store the raw full title string
            "name": "Not found", # Game Name
            "version_from_title": "Not found",
            "author_from_title": "Not found",
            "version_from_post": "Not found",
            "author_from_post_label": "Not found", # For "Developer: [Name]" in post
            "author_from_dl_list": "Not found",
            "author_from_thread_starter": "Not found",
            "version_from_dl_list": "Not found",
            "final_game_name": "Not found",
            "final_version": "Not found",
            "final_author": "Not found",
            "tags": [],
            "full_description": "Not found",
            "changelog": "Not found",
            "download_links": [], # Will be list of dicts: {'text': str, 'url': str, 'os_type': str} after filtering
            "engine": "Not found",
            "language": "Not found",
            "status": "Not found",
            "censorship": "Not found",
            "release_date": "Not found",
            "thread_updated_date": "Not found",
            "os_general_list": "Not found", # For "Platform: Win, Lin, Mac"
            "other_header_info": {} # For any other distinct Author/GameType from header
        }

        # --- I. Header Information Extraction ---
        raw_title_h1 = soup.find('h1', class_='p-title-value')
        if raw_title_h1:
            data['title_full_raw'] = raw_title_h1.get_text(strip=True)
        elif page_title_element := soup.find('title'): # Fallback to <title> tag
            data['title_full_raw'] = page_title_element.get_text(strip=True).replace(" | F95zone", "")
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Raw Title String: {data['title_full_raw']}")

        # 1. Robust Title String Parsing (Name, Version, Author from h1.p-title-value)
        if data['title_full_raw']:
            title_str = data['title_full_raw']
            # Regex to capture Name, Version, and Author from typical F95Zone title format
            # Example: "Game Name [Version Info] [Author Name]"
            # Example: "Another Game (Version) (Author)"
            # Example: "Game Title [v1.0 Public] [Dev Group]"
            # Example: "Game [Ch.1 Remake / v0.25] [NeonGhosts]"
            
            # This regex attempts to find the last two bracketed/parenthesized groups for version and author
            # and assumes the rest at the beginning is the game name.
            # It tries to be flexible with brackets [] or parentheses ()
            # It handles version prefixes like v, Ep, Ch.
            # It tries to avoid capturing simple year numbers as versions if they are part of the name.

            name_part = title_str
            version_part = "Not found"
            author_part = "Not found"

            # Try to match bracketed/parenthesized parts from right to left
            # Pattern: (Anything)[Bracketed/Parenthesized Group1][Bracketed/Parenthesized Group2]
            # Or      (Anything)[Bracketed/Parenthesized Group1]
            
            # Regex to find potential version and author in brackets/parentheses at the end
            # (?i) for case-insensitive matching of v, ep, ch etc.
            # (\[|\() - matches opening bracket or parenthesis
            # ([^\[\]()]+) - captures content inside (group 1 for version, group 3 for author)
            # (?:\]|\)) - matches closing bracket or parenthesis
            # \s* - optional spaces
            # $ - end of string for author, or before author for version
            
            # Regex to find author (last group)
            author_match = re.search(r"(?i)(?:\[|\()([^\[\]()]+?)(?:\]|\))\s*$", title_str)
            if author_match:
                potential_author = author_match.group(1).strip()
                # Avoid matching typical version patterns as author if it's the only bracketed group
                is_likely_version = re.fullmatch(r"(?i)(v|ver|ep|episode|ch|chapter|season|book|part|pt|alpha|beta|rc|final|public|demo|preview|build|update|upd|\d*([.]\d+)+[a-z]?)\w*", potential_author, re.IGNORECASE)
                
                # Heuristic: if it doesn't look like a version and is reasonably long OR there are other brackets
                # A more complex check might involve looking if there's ANOTHER bracket before it
                
                # Simple check: if it contains digits but also letters and isn't a pure version pattern
                if not is_likely_version or len(potential_author) > 15 or any(c.isalpha() for c in potential_author): # Allow if it's long or has letters and isn't purely version-like
                    # Check if this author candidate itself looks like a version number
                    # We want to avoid stripping a version number if it's the only thing in brackets.
                    # This is tricky. If there's only one bracketed item, and it looks like a version, it's probably the version.
                    
                    # Let's assume for now the last bracket is author unless it's VERY clearly a version AND there are no other brackets
                    # This part is simplified for now; complex disambiguation needs more rules
                    
                    # If the potential author looks like a version, and it's the only bracketed group,
                    # it's more likely the version. This needs to be refined.
                    # For now, let's just grab it if it has letters or is long.
                    if len(potential_author) > 1 and (any(c.isalpha() for c in potential_author) or len(potential_author) > 6 or '.' in potential_author): # Basic check to avoid short numbers as authors
                         author_part = potential_author
                         name_part = title_str[:author_match.start()].strip() # Text before author match


            # Regex to find version (last group, if author wasn't found, or the one before author)
            # Needs to search on `name_part` if author was already stripped
            version_search_string = name_part if author_part != "Not found" else title_str
            version_match = re.search(r"(?i)(?:\[|\()([^\[\]()]+?)(?:\]|\))\s*$", version_search_string)
            if version_match:
                potential_version = version_match.group(1).strip()
                # Check if it actually looks like a version (more lenient here)
                if re.search(r"(\d|v|ep|ch|upd|final|public|beta|alpha)", potential_version, re.IGNORECASE):
                    version_part = potential_version
                    if name_part == version_search_string : #
                         name_part = version_search_string[:version_match.start()].strip()
                    elif author_part != "Not found" and name_part != title_str : # version was found in the name_part that already had author stripped
                         name_part = name_part[:version_match.start()].strip()


            # Clean up game name by removing trailing hyphens, colons, or spaces
            name_part = re.sub(r"[\s:-]+$", "", name_part).strip()
            if not name_part and data['title_full_raw']: # If name part became empty, use original title as a fallback
                name_part = data['title_full_raw']
                # If the full title was used, try to re-evaluate author/version if they were "Not found"
                # This can happen if title is JUST "[Author]" or "[Version]"
                if author_part == "Not found" and version_part != "Not found" and name_part.endswith(f"[{version_part}]"): name_part = name_part[:-len(f"[{version_part}]")].strip()
                if version_part == "Not found" and author_part != "Not found" and name_part.endswith(f"[{author_part}]"): name_part = name_part[:-len(f"[{author_part}]")].strip()


            data['name'] = name_part if name_part else data['title_full_raw'] # Fallback if name is empty
            data['version_from_title'] = version_part
            data['author_from_title'] = author_part

            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Parsed from Title - Name: {data['name']}, Version: {data['version_from_title']}, Author: {data['author_from_title']}")

        # 2. Author/GameType from Header (Distinct Field) - placeholder for future if specific patterns found
        # Example: Look for <div class="someSpecificHeaderClass">Author: DevName</div> - currently no known reliable general selector

        # 3. Tags (`div.tagGroup a.tagItem`) - THIS IS HANDLED LATER, but keep in mind it's header info.

        # --- II. Main Post Content Extraction (`article.message--post div.bbWrapper`) ---
        first_post_article_content = soup.find('article', class_='message--post')
        bb_wrapper = first_post_article_content.find('div', class_='bbWrapper') if first_post_article_content else None

        if not bb_wrapper:
            logger_scraper.error(f"EXTRACT_GAME_DATA: bbWrapper not found for {game_thread_url}. Cannot extract most post details.")
            # Return partial data or None - for now, let it continue and other fields will be "Not found"
        else:
            # 1. Developer/Author (from post body label, DL list, then thread starter)
            #   a. Explicitly labeled Developer in post body
            strong_tags = bb_wrapper.find_all(['strong', 'b'])
            for tag in strong_tags:
                if tag.get_text(strip=True).lower().startswith("developer:"):
                    dev_name_candidate = tag.next_sibling
                    if dev_name_candidate and isinstance(dev_name_candidate, str) and dev_name_candidate.strip():
                        data['author_from_post_label'] = dev_name_candidate.strip()
                        break
                    elif dev_name_candidate and dev_name_candidate.name == 'a' and dev_name_candidate.get_text(strip=True): # Link after "Developer:"
                        data['author_from_post_label'] = dev_name_candidate.get_text(strip=True)
                        break
                    # Look further if it's wrapped in more tags like a span or another strong
                    elif dev_name_candidate and dev_name_candidate.find(string=True, recursive=False) and dev_name_candidate.find(string=True, recursive=False).strip():
                         data['author_from_post_label'] = dev_name_candidate.find(string=True, recursive=False).strip() # Get text from first child
                         break
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from post label ('Developer:'): {data['author_from_post_label']}")

            #   b. Developer from DL list - Handled later in DL parsing section, result stored in data['author_from_dl_list']
            
            #   c. Thread starter's F95Zone username
            if first_post_article_content: # Re-check first_post_article_content
                user_details_div = first_post_article_content.find('div', class_='message-userDetails')
                if user_details_div:
                    author_link_tag = user_details_div.find('a', class_='username')
                    if author_link_tag:
                        data['author_from_thread_starter'] = author_link_tag.get_text(strip=True)
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from thread starter: {data['author_from_thread_starter']}")


            # 2. Version (from post body label, then DL list)
            #   a. Explicitly labeled Version in post body
            for tag in strong_tags: # Reuse strong_tags from author search
                tag_text_lower = tag.get_text(strip=True).lower()
                if any(kw in tag_text_lower for kw in ["version:", "current version:", "latest release:"]) and len(tag_text_lower) < 30:
                    version_candidate_text = ""
                    # Try to get text from the next sibling or a child link more robustly
                    next_elem = tag.next_sibling
                    while next_elem and (isinstance(next_elem, str) and not next_elem.strip()): # Skip empty strings
                        next_elem = next_elem.next_sibling
                    
                    if next_elem:
                        if isinstance(next_elem, str) and next_elem.strip():
                            version_candidate_text = next_elem.strip().splitlines()[0].strip() # Take first line
                        elif next_elem.name == 'a' and next_elem.get_text(strip=True):
                            version_candidate_text = next_elem.get_text(strip=True)
                        elif next_elem.name and next_elem.find(string=True, recursive=False) and next_elem.find(string=True, recursive=False).strip():
                             version_candidate_text = next_elem.find(string=True, recursive=False).strip()

                    if version_candidate_text:
                         data['version_from_post'] = version_candidate_text
                         break 
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Version from post label: {data['version_from_post']}")
            #   b. Version from DL list - Handled later in DL parsing, result stored in data['version_from_dl_list']

            # 3. Overview/Full Description
            desc_elements = []
            stop_keywords = ['download', 'changelog', "what's new", "what is new", "version history", "updates", "installation", "preview", "screenshots", "spoiler:", "support the dev", "developer", "author", "version", "engine", "language", "status", "censorship", "release date", "thread updated", "os", "platform", "system", "genre", "tags"] # EXPANDED
            for elem in bb_wrapper.children:
                elem_text_lower = ""
                if elem.name and (elem.name.startswith('h') or \
                                  elem.name == 'dl' or # ADDED: Stop if we hit a definition list
                                  (elem.name == 'div' and any(cls in elem.get('class', []) for cls in ['bbCodeSpoiler', 'bbCodeBlock--download', 'bbCodeBlock--changelog'])) or \
                                  (elem.name == 'button' and 'bbCodeSpoiler-button' in elem.get('class',[])) or \
                                  (elem.name in ['strong','b'])): # Check strong/b tags as section headers too
                    elem_text_lower = elem.get_text(strip=True).lower()
                
                # More robust stop condition
                if (elem_text_lower and any(kw in elem_text_lower for kw in stop_keywords) and len(elem_text_lower) < 70) or elem.name == 'dl': # If header contains stop keyword or element is a DL
                    is_likely_section_header = True
                    # Exception: allow "Overview" or "Description" headers themselves.
                    if "overview" in elem_text_lower or "description" in elem_text_lower or "plot" in elem_text_lower or "story" in elem_text_lower:
                         is_likely_section_header = False # Don't stop for these, they are part of description
                    if is_likely_section_header:
                        break
                
                if isinstance(elem, str):
                    if elem.strip(): desc_elements.append(elem.strip())
                elif elem.name not in ['script', 'style', 'iframe', 'form', 'input', 'textarea', 'select', 'button']: # Filter out more non-content tags
                    # Avoid extracting text from known non-description blocks like full spoiler contents here
                    # if it's a spoiler, only take its button text if it's not a stop keyword
                    if elem.name == 'div' and 'bbCodeSpoiler' in elem.get('class', []):
                        button_text_spoiler = elem.find('button', class_='bbCodeSpoiler-button')
                        if button_text_spoiler and not any(kw in button_text_spoiler.get_text(strip=True).lower() for kw in stop_keywords):
                             desc_elements.append(button_text_spoiler.get_text(strip=True)) # Add button text if not a stop word
                        # Do NOT add the spoiler content itself here; it's handled by changelog/download logic later
                    else:
                        desc_elements.append(elem.get_text(separator='\\n', strip=True))
            
            data['full_description'] = "\\n".join(filter(None, desc_elements)).strip()
            if not data['full_description']: # Fallback if above logic yields nothing
                 data['full_description'] = bb_wrapper.get_text(separator='\\n', strip=True)
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Description snippet: {(data['full_description'][:200] + '...') if data['full_description'] and len(data['full_description']) > 200 else data['full_description']}")

            # 4. Release Date
            # Search for patterns like "Release Date: YYYY-MM-DD", "Released: ...", etc.
            # This is a simple text search in the bbWrapper for now.
            release_date_patterns = [
                r"(?:Release Date|Released|Initial Release|First Release)\s*[:\-]?\s*([^\n]+)",
                r"<strong>(?:Release Date|Released|Initial Release|First Release)\s*[:\-]?\s*</strong>\s*([^\n]+)" # If bolded label
            ]
            bb_wrapper_text_for_dates = bb_wrapper.get_text(separator="\\n") # Get text with newlines for better context
            for pattern in release_date_patterns:
                match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                if match and match.group(1).strip():
                    # Basic cleaning for the date string - try to avoid grabbing too much following text
                    potential_date_str = match.group(1).strip()
                    # Basic cleaning for the date string - try to avoid grabbing too much following text
                    cleaned_val = re.sub(r"^\\s*[:\\-\\s]\\s*", "", potential_date_str).strip()
                    if cleaned_val and len(cleaned_val) < 50 and any(c.isdigit() for c in cleaned_val):
                        data['release_date'] = cleaned_val.split('\\n')[0].strip() # Take first line of match
                        break
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Release Date from post: {data['release_date']}")
            # TODO: Consider parsing with dateutil.parser if a more structured date is needed.

            # 5. Thread Updated Date (from post metadata, outside bbWrapper)
            if first_post_article_content:
                time_tag = first_post_article_content.find('time', class_='u-dt')
                if time_tag and time_tag.has_attr('datetime'):
                    data['thread_updated_date'] = time_tag['datetime']
                elif time_tag: # Fallback to text if datetime attr not present
                    data['thread_updated_date'] = time_tag.get_text(strip=True)
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Thread Updated Date: {data['thread_updated_date']}")


            # 6. OS Listing (General Platform Information from post body)
            os_patterns = [
                r"(?:Platform|OS|Systems|Support[s]?)\s*[:\-]?\s*([^\n]+)",
                r"<strong>(?:Platform|OS|Systems|Support[s]?)\s*[:\-]?\s*</strong>\s*([^\n]+)"
            ]
            for pattern in os_patterns:
                match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE) # Use bb_wrapper_text_for_dates again
                if match and match.group(1).strip():
                    os_list_str_raw = match.group(1).strip()
                    cleaned_os_list_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", os_list_str_raw).strip().split('\\n')[0].strip()
                    # Avoid overly long strings that might not be just the OS list
                    if cleaned_os_list_str and len(cleaned_os_list_str) < 100: # Arbitrary limit
                        data['os_general_list'] = cleaned_os_list_str
                        break
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): OS General List from post: {data['os_general_list']}")

            # Extract Language from post body
            language_patterns = [
                r"(?:Language[s]?)\s*[:\-]?\s*([^\n]+)",
                r"<strong>(?:Language[s]?)\s*[:\-]?\s*</strong>\s*([^\n]+)"
            ]
            if data['language'] == "Not found": # Only if not already found (e.g. by DL list if that runs first)
                for pattern in language_patterns:
                    match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                    if match and match.group(1).strip():
                        lang_str_raw = match.group(1).strip()
                        cleaned_lang_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", lang_str_raw).strip().split('\\n')[0].strip()
                        if cleaned_lang_str and len(cleaned_lang_str) < 150: # Arbitrary limit
                            data['language'] = cleaned_lang_str
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Language from post: {data['language']}")
                            break
            
            # Extract Status from post body
            status_patterns = [
                r"(?:Status)\s*[:\-]?\s*([^\n]+)",
                r"<strong>(?:Status)\s*[:\-]?\s*</strong>\s*([^\n]+)"
            ]
            if data['status'] == "Not found":
                for pattern in status_patterns:
                    match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                    if match and match.group(1).strip():
                        status_str_raw = match.group(1).strip()
                        cleaned_status_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", status_str_raw).strip().split('\\n')[0].strip()
                        if cleaned_status_str and len(cleaned_status_str) < 100: # Arbitrary limit
                            data['status'] = cleaned_status_str
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Status from post: {data['status']}")
                            break

            # Extract Censorship from post body
            censorship_patterns = [
                r"(?:Censorship|Censored)\s*[:\-]?\s*([^\n]+)",
                r"<strong>(?:Censorship|Censored)\s*[:\-]?\s*</strong>\s*([^\n]+)"
            ]
            if data['censorship'] == "Not found":
                for pattern in censorship_patterns:
                    match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                    if match and match.group(1).strip():
                        cen_str_raw = match.group(1).strip()
                        cleaned_cen_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", cen_str_raw).strip().split('\\n')[0].strip()
                        if cleaned_cen_str and len(cleaned_cen_str) < 50: # Arbitrary limit
                            data['censorship'] = cleaned_cen_str
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Censorship from post: {data['censorship']}")
                            break
            
            # 7. Changelog
            changelog_text_parts = []
            possible_changelog_headers = ['changelog', "what's new", "update notes", "version history", "updates", "latest changes"]
            
            spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            found_changelog_primary = False
            for spoiler_idx, spoiler in enumerate(spoilers):
                button = spoiler.find('button', class_='bbCodeSpoiler-button')
                content = spoiler.find('div', class_='bbCodeSpoiler-content')
                if button and content and any(ch_kw in button.get_text(strip=True).lower() for ch_kw in possible_changelog_headers):
                    changelog_text_parts.append(content.get_text(separator='\\n', strip=True))
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog from spoiler (button: '{button.get_text(strip=True)}').")
                    found_changelog_primary = True # Prioritize specific changelog spoilers
                    # Consider breaking if it's a very specific "Changelog" spoiler, or collect all matching
            
            if not found_changelog_primary: # Fallback to searching headers if no direct spoiler match
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No primary 'Changelog' spoiler found. Searching for headers: {possible_changelog_headers}")
                header_tags_to_check = ['strong', 'b', 'h2', 'h3', 'h4', 'p']
                
                all_potential_header_elements = bb_wrapper.find_all(header_tags_to_check)
                for header_el in all_potential_header_elements:
                    header_text_lower = header_el.get_text(strip=True).lower()
                    
                    if any(ch_kw in header_text_lower for ch_kw in possible_changelog_headers) and len(header_text_lower) < 70:
                        # Skip if this header itself is inside a spoiler button we might have processed or will process
                        if header_el.find_parent('button', class_='bbCodeSpoiler-button'):
                            continue

                        # Try to get content from an adjacent spoiler
                        next_sibling_spoiler = header_el.find_next_sibling('div', class_='bbCodeSpoiler')
                        if next_sibling_spoiler:
                            spoiler_content_div = next_sibling_spoiler.find('div', class_='bbCodeSpoiler-content')
                            if spoiler_content_div:
                                changelog_text_parts.append(spoiler_content_div.get_text(separator='\\n', strip=True))
                                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog from spoiler adjacent to header '{header_el.get_text(strip=True)}'.")
                                found_changelog_primary = True # Ensure no break here

                        # If no adjacent spoiler, collect text from subsequent siblings until a new major header
                        if not changelog_text_parts or not found_changelog_primary: # only if not already populated by adjacent spoiler
                            current_content_sibling = header_el.next_sibling
                            temp_changelog_sibling_text = []
                            while current_content_sibling:
                                if current_content_sibling.name and \
                                   (current_content_sibling.name.startswith('h') or \
                                    (current_content_sibling.name in header_tags_to_check and any(kw in current_content_sibling.get_text(strip=True).lower() for kw in stop_keywords + possible_changelog_headers) and len(current_content_sibling.get_text(strip=True)) < 70) or \
                                    (current_content_sibling.name == 'div' and any(cls in current_content_sibling.get('class', []) for cls in ['bbCodeSpoiler', 'bbCodeBlock--download']))):
                                    break # Stop at next major section (this break is for the WHILE loop, which is correct)
                                
                                if isinstance(current_content_sibling, str) and current_content_sibling.strip():
                                    temp_changelog_sibling_text.append(current_content_sibling.strip())
                                elif current_content_sibling.name not in ['script', 'style', 'iframe']:
                                    if current_content_sibling.name == 'div' and 'bbCodeSpoiler' in current_content_sibling.get('class', []):
                                        spoiler_button = current_content_sibling.find('button', class_='bbCodeSpoiler-button')
                                        spoiler_content = current_content_sibling.find('div', class_='bbCodeSpoiler-content')
                                        if spoiler_button and spoiler_content and not any(kw in spoiler_button.get_text(strip=True).lower() for kw in stop_keywords):
                                            temp_changelog_sibling_text.append(spoiler_content.get_text(separator='\\n', strip=True))
                                    else:
                                        temp_changelog_sibling_text.append(current_content_sibling.get_text(separator='\\n', strip=True))

                                current_content_sibling = current_content_sibling.next_sibling
                            
                            if temp_changelog_sibling_text:
                                changelog_text_parts.append("\\n".join(filter(None, temp_changelog_sibling_text)).strip())
                                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog from content following header '{header_el.get_text(strip=True)}'.")
                                found_changelog_primary = True # Ensure no break here
                                
                    if found_changelog_primary: # This break is for the `for header_el in all_potential_header_elements:` loop
                        break # Correctly placed break for the outer loop
            
            if changelog_text_parts:
                data['changelog'] = "\\n---\\n".join(filter(None, changelog_text_parts)).strip()
            else:
                data['changelog'] = "Not found" # Changed from "Not clearly identified"
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog (first 100 chars): {data['changelog'][:100] if data['changelog'] and data['changelog'] != 'Not found' else 'None'}")

            # 8. Language / Censorship / Status / Engine (from post body - these are fallbacks or supplements to DL/Tags)
            # These are usually in <dl> lists, handled later. This section is for text patterns if not in <dl>.
            # Example: <strong>Language:</strong> English
            # This is implicitly covered by strong_tags iteration if those terms appear in a label.
            # For now, rely on DL parsing and later consolidation.

            # 9. Download Links & OS-Specific Filtering/Prioritization
            # CRITICAL OVERHAUL
            raw_download_links = [] # Temporary list to hold all found links with potential OS info
            support_link_domains = ['patreon.com', 'subscribestar.adult', 'discord.gg', 'discord.com', 'itch.io', 'buymeacoffee.com', 'ko-fi.com', 'store.steampowered.com', 'paypal.com', 'subscribestar.com'] # Added .com for subscribestar, paypal
            
            # Strategy 1: Find sections explicitly marked "DOWNLOAD" or similar
            download_section_headers_texts = ['download', 'links', 'files'] # Broader terms for section headers
            # More specific OS related terms that might indicate a download section if followed by links
            os_section_keywords = ['windows', 'pc', 'linux', 'mac', 'macos', 'osx', 'android'] 
            
            # Search for headers first (h1-h4, strong, b)
            potential_dl_section_elements = []
            all_header_like_tags = bb_wrapper.find_all(['h1','h2','h3','h4','strong','b', 'p']) # p for paragraph headers
            
            current_section_os = None # Track OS for links under a specific OS header
            
            for elem_idx, elem in enumerate(bb_wrapper.children): # Iterate through all direct children of bbWrapper
                current_element_text_lower = ""
                is_header_like = False
                
                if isinstance(elem, str): continue # Skip plain strings at this level

                if elem.name in ['h1','h2','h3','h4','strong','b','p']:
                    current_element_text_lower = elem.get_text(strip=True).lower()
                    is_header_like = True

                # Check if this element is a download section header
                if is_header_like and any(hdr_kw in current_element_text_lower for hdr_kw in download_section_headers_texts) and len(current_element_text_lower) < 50:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Identified download section header: '{elem.get_text(strip=True)}'")
                    current_section_os = None # Reset section OS
                    # Add this element and subsequent siblings until next major header as a search area
                    potential_dl_section_elements.append(elem)
                
                # Check for OS-specific section headers
                elif is_header_like and any(os_kw in current_element_text_lower for os_kw in os_section_keywords) and len(current_element_text_lower) < 30:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Identified OS-specific section header: '{elem.get_text(strip=True)}'")
                    current_section_os = None # Reset first
                    if any(kw in current_element_text_lower for kw in ['windows', 'pc']): current_section_os = 'win'
                    elif 'linux' in current_element_text_lower: current_section_os = 'linux'
                    elif any(kw in current_element_text_lower for kw in ['mac', 'osx', 'macos']): current_section_os = 'mac'
                    elif 'android' in current_element_text_lower: current_section_os = 'android'
                    potential_dl_section_elements.append(elem) # Also treat as a dl section start

                # Find <a> tags within this element or its direct children if it's a container, or in siblings if it's a header
                links_to_check = []
                if elem.name == 'a' and elem.get('href'):
                    links_to_check.append(elem)
                else: # Search within the element (e.g. if elem is a div or p containing links)
                    links_to_check.extend(elem.find_all('a', href=True))
                
                for link_tag in links_to_check:
                    href = link_tag.get('href')
                    text = link_tag.get_text(strip=True)
                    
                    # Basic filtering for non-download links
                    if not href or href.startswith(('#', 'mailto:', 'javascript:')) or "f95zone.to/account/" in href or "f95zone.to/members/" in href :
                        continue
                    
                    # Filter out attachment (image) links
                    if "attachments.f95zone.to" in href.lower():
                        logger_scraper.debug(f"SCRAPER_DATA (URL: {game_thread_url}): Skipping attachment link: '{text}' -> '{href}'")
                        continue

                    # Filter out support/social links from primary download list
                    try:
                        link_domain = re.match(r"https://?([^/]+)", href).group(1).replace("www.", "")
                        if any(support_domain in link_domain for support_domain in support_link_domains):
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Identified support/social link (will not be in main downloads): '{text}' -> '{href}'")
                            # Optionally, collect these separately: data['support_links'].append({'text':text,'url':href})
                            continue
                    except: # If regex fails for some reason, proceed with it
                        pass

                    # Allow f95zone thread links if they seem like mod/patch download pages
                    if "f95zone.to/threads/" in href and not any(ext in href.lower() for ext in ['.zip', '.rar', '.apk', '.7z', '.exe', '.patch', '.mod']):
                        if not any(kw in text.lower() for kw in ['mod', 'patch', 'translation', 'download', 'fix', 'guide']):
                            continue # Skip if it's just a link to another general thread

                    # OS Detection for this specific link
                    link_os = 'unknown'
                    if current_section_os: # OS from current section header
                        link_os = current_section_os
                    else: # Infer from link text or href
                        text_lower = text.lower()
                        href_lower = href.lower()
                        if any(kw in text_lower for kw in ['win ', ' pc ', '.exe', '[win]', '(win)', '_pc.']) or any(kw in href_lower for kw in ['_pc.', '.exe']): link_os = 'win'
                        elif any(kw in text_lower for kw in ['linux', '.deb', '.sh', '[linux]', '(linux)', '_linux.']) or any(kw in href_lower for kw in ['_linux.', '.sh']): link_os = 'linux'
                        elif any(kw in text_lower for kw in ['mac', 'osx', '.dmg', '[mac]', '(mac)', '_mac.']) or any(kw in href_lower for kw in ['_mac.', '.dmg']): link_os = 'mac'
                        elif any(kw in text_lower for kw in ['android', '.apk', '[android]', '(android)', '_apk.']) or any(kw in href_lower for kw in ['_apk.', '.apk']): link_os = 'android'
                        elif any(kw in text_lower for kw in ['extra', 'patch', 'mod', 'dlc', 'optional', 'bonus', 'soundtrack', 'guide']): link_os = 'extras'
                    
                    raw_download_links.append({'text': text, 'url': href, 'os_determined': link_os, 'source_element_text': elem.name}) # Store for debugging source
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found raw download link: '{text}' -> '{href}' (OS: {link_os}, Section OS: {current_section_os})")

            # Consolidate and filter duplicates from raw_download_links
            unique_links_map = {}
            for link_info in raw_download_links:
                key = (link_info['url'], link_info['text']) # Use URL and text to define uniqueness
                if key not in unique_links_map:
                    unique_links_map[key] = link_info
            
            final_raw_links_with_os = list(unique_links_map.values())
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found {len(final_raw_links_with_os)} unique raw download links with OS determined.")

            # Implement OS-based prioritization
            has_win_links = any(link['os_determined'] == 'win' for link in final_raw_links_with_os)
            has_linux_links = any(link['os_determined'] == 'linux' for link in final_raw_links_with_os)

            if has_win_links or has_linux_links:
                for link in final_raw_links_with_os:
                    if link['os_determined'] in ['win', 'linux', 'extras']:
                        data['download_links'].append({'text': link['text'], 'url': link['url'], 'os_type': link['os_determined']})
            else: # No Win or Linux links, take all
                for link in final_raw_links_with_os:
                    data['download_links'].append({'text': link['text'], 'url': link['url'], 'os_type': link['os_determined']})
            
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Final {len(data['download_links'])} download links after OS prioritization.")


        # --- Tags, DL List items (Author, Version, Engine, Language, Status, Censorship) ---
        # This part consolidates info from various sources including specific DL list parsing.

        # Tags (Genre from spoiler, then div.tagGroup, then dt "tags")
        data['tags'] = [] # Reset
        genre_spoiler_found_tags = False
        tags_found_by_js_taglist = False

        if bb_wrapper: # Check within bbWrapper first for genre spoiler
            spoilers_for_tags = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            for spoiler in spoilers_for_tags:
                button = spoiler.find('button', class_='bbCodeSpoiler-button')
                content_div = spoiler.find('div', class_='bbCodeSpoiler-content')
                if button and content_div and "genre" in button.get_text(strip=True).lower():
                    raw_tags_text = content_div.get_text(separator=',', strip=True)
                    if raw_tags_text:
                        parsed_tags = [tag.strip() for tag in raw_tags_text.split(',') if tag.strip()]
                        data['tags'].extend(parsed_tags)
                        genre_spoiler_found_tags = True
                    break
        
        # New: Check for span.js-tagList a.tagItem (usually outside bbWrapper, so check soup)
        if not genre_spoiler_found_tags:
            if tags_span_container := soup.find('span', class_='js-tagList'):
                tag_links = tags_span_container.find_all('a', class_='tagItem')
                if tag_links:
                    for tag_link in tag_links:
                        tag_text = tag_link.get_text(strip=True)
                        if tag_text not in data['tags']: data['tags'].append(tag_text)
                    if data['tags']: # If we found tags here, mark it
                        tags_found_by_js_taglist = True

        # Fallback to standard tag locations if no genre spoiler AND no js-tagList tags found
        if not genre_spoiler_found_tags and not tags_found_by_js_taglist: 
            if tags_container := soup.find('div', class_='tagGroup'): # Often at top of page, outside bbWrapper
                tag_links = tags_container.find_all('a', class_='tagItem')
                for tag_link in tag_links:
                    tag_text = tag_link.get_text(strip=True)
                    if tag_text not in data['tags']: data['tags'].append(tag_text)
            elif bb_wrapper : # Check within bbWrapper if not found above
                if tags_dt := bb_wrapper.find('dt', string=lambda t: t and 'tags' in t.lower()):
                    if tags_dd := tags_dt.find_next_sibling('dd'): 
                        tag_links = tags_dd.find_all('a')
                        for tag_link in tag_links:
                            tag_text = tag_link.get_text(strip=True)
                            if tag_text not in data['tags']: data['tags'].append(tag_text)
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted tags (final): {data['tags']}")

        # Parse <dl> lists (Definition Lists for structured data)
        # These can be anywhere, typically in the first post. Search entire soup.
        dls = soup.find_all('dl', class_=lambda x: x and any(c in x for c in ['pairs--columns', 'block-body-infoPairs', 'pairs--justified', 'pairs'])) # More general DL classes
        for dl_element in dls:
            dt_elements = dl_element.find_all('dt')
            for dt in dt_elements:
                dt_text_lower = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling('dd')
                if not dd: continue
                
                dd_text = dd.get_text(strip=True)
                dd_html = dd.decode_contents() # Get HTML for potential links

                if 'developer' in dt_text_lower or 'author' in dt_text_lower:
                    # Prefer text from a link if present
                    link_in_dd = dd.find('a')
                    if link_in_dd and link_in_dd.get_text(strip=True):
                        data['author_from_dl_list'] = link_in_dd.get_text(strip=True)
                    elif dd_text:
                        data['author_from_dl_list'] = dd_text
                elif 'version' in dt_text_lower:
                    data['version_from_dl_list'] = dd_text
                elif 'engine' in dt_text_lower or 'game engine' in dt_text_lower:
                    data['engine'] = dd_text # DL list is high priority for engine
                elif 'language' in dt_text_lower:
                    data['language'] = dd_text
                elif 'status' in dt_text_lower:
                    data['status'] = dd_text
                elif 'censorship' in dt_text_lower or 'censor' in dt_text_lower:
                    data['censorship'] = dd_text
                # Add other DL fields if needed, e.g., OS, Release Date
                elif ('os' in dt_text_lower or 'platform' in dt_text_lower) and data['os_general_list'] == "Not found":
                    data['os_general_list'] = dd_text


        # Infer Engine/Status/Censorship from Tags if not found yet
        if isinstance(data['tags'], list) and data['tags'] != ["Not found"]:
            for tag_text_original in data['tags']:
                tag_text_lower = tag_text_original.lower()
                if data['engine'] == "Not found" and any(eng_name in tag_text_lower for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal', 'qsp', 'tyrano', 'wolf rpg']):
                    data['engine'] = tag_text_original # Use original casing
                if data['status'] == "Not found" and any(st_name in tag_text_lower for st_name in ['completed', 'ongoing', 'on hold', 'on-hold', 'abandoned', 'hiatus']):
                    data['status'] = tag_text_original
                if data['censorship'] == "Not found" and any(cen_kw in tag_text_lower for cen_kw in ['uncensored', 'censored']):
                    data['censorship'] = tag_text_original
        
        # Infer Engine from Title if still not found (lower priority)
        if data['engine'] == "Not found" and data['title_full_raw']:
            title_lower_for_engine = data['title_full_raw'].lower()
            engine_keywords_title = ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal engine', 'qsp', 'tyranobuilder', 'wolf rpg']
            for eng_key in engine_keywords_title:
                if eng_key in title_lower_for_engine:
                    try:
                        start_index = title_lower_for_engine.find(eng_key)
                        data['engine'] = data['title_full_raw'][start_index : start_index + len(eng_key)]
                        break
                    except: pass


        # --- CONSOLIDATE FINAL Author, Version, Game Name ---
        # Priority for Author:
        # 1. Explicit "Developer: [Name]" in post body (`author_from_post_label`)
        # 2. Author/Developer from `<dl>` list (`author_from_dl_list`)
        # 3. Author parsed from title string (`author_from_title`)
        # 4. Thread starter's F95Zone username (`author_from_thread_starter`)
        if data['author_from_post_label'] != "Not found": data['final_author'] = data['author_from_post_label']
        elif data['author_from_dl_list'] != "Not found": data['final_author'] = data['author_from_dl_list']
        elif data['author_from_title'] != "Not found": data['final_author'] = data['author_from_title']
        elif data['author_from_thread_starter'] != "Not found": data['final_author'] = data['author_from_thread_starter']
        else: data['final_author'] = "Not found" # Default if all else fails

        # Priority for Version:
        # 1. Version parsed from title string (`version_from_title`)
        # 2. Explicit "Version: [Number]" in post body (`version_from_post`)
        # 3. Version from `<dl>` list (`version_from_dl_list`)
        if data['version_from_title'] != "Not found": data['final_version'] = data['version_from_title']
        elif data['version_from_post'] != "Not found": data['final_version'] = data['version_from_post']
        elif data['version_from_dl_list'] != "Not found": data['final_version'] = data['version_from_dl_list']
        else: data['final_version'] = "Not found"

        # Final Game Name (already parsed from title as `data['name']`)
        data['final_game_name'] = data['name']
        
        # Clean final game name if engine prefix exists and name is not just the engine
        if data['final_game_name'] and data['engine'] and data['engine'] != "Not found":
            engine_lower = data['engine'].lower()
            game_name_lower = data['final_game_name'].lower()
            if game_name_lower.startswith(engine_lower) and game_name_lower != engine_lower:
                try:
                    match_engine_prefix = re.match(re.escape(data['engine']), data['final_game_name'], re.IGNORECASE)
                    if match_engine_prefix:
                        engine_len_in_title = len(match_engine_prefix.group(0))
                        if len(data['final_game_name']) > engine_len_in_title:
                            original_title_for_log = data['final_game_name']
                            data['final_game_name'] = data['final_game_name'][engine_len_in_title:].lstrip(' -:[]()').strip()
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Cleaned final game name from '{original_title_for_log}' to '{data['final_game_name']}' by removing engine prefix '{data['engine']}'.")
                except re.error:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Regex error cleaning engine from final game name.")
        
        # If final_game_name is empty after cleaning, revert to raw title or "Not found"
        if not data['final_game_name'] or data['final_game_name'].lower() == data['engine'].lower():
            data['final_game_name'] = data['title_full_raw'] if data['title_full_raw'] else "Not found"


        # --- Final Cleanup of data dictionary before returning ---
        # Create the final dictionary with desired field names
        result_data = {
            "url": data['url'],
            "title": data['final_game_name'], # Use the cleaned game name as 'title'
            "version": data['final_version'],
            "author": data['final_author'],
            "tags": data['tags'] if data['tags'] else ["Not found"],
            "full_description": data['full_description'],
            "changelog": data['changelog'],
            "download_links": data['download_links'] if data['download_links'] else [], # Empty list if none
            "engine": data['engine'],
            "language": data['language'],
            "status": data['status'],
            "censorship": data['censorship'],
            "release_date": data['release_date'],
            "thread_updated_date": data['thread_updated_date'],
            "os_general_list": data['os_general_list'],
            # Include raw extracted fields for debugging if needed, e.g.
            # "raw_title_string": data['title_full_raw'],
            # "raw_version_from_title": data['version_from_title'],
            # "raw_author_from_title": data['author_from_title'],
        }

        for key, value in result_data.items():
            if value is None: # Ensure None becomes "Not found" for string fields
                result_data[key] = "Not found"
            # Lists are handled by defaulting to empty list or ["Not found"] earlier

    logger_scraper.info(f"SCRAPER_RETURN (URL: {game_thread_url}): Final data dictionary: {result_data}")
    return result_data

if __name__ == '__main__':
    import os
    # Setup basic logging for standalone script testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s', handlers=[logging.StreamHandler()])
    
    f95_username = os.environ.get("F95ZONE_USERNAME")
    f95_password = os.environ.get("F95ZONE_PASSWORD")

    if not (f95_username and f95_password):
        logger_scraper.warning("WARNING: F95ZONE_USERNAME and/or F95ZONE_PASSWORD environment variables not set for standalone test.")
        logger_scraper.warning("Login functionality will not be tested. Scraping will be anonymous.")

    example_urls = [
        "https://f95zone.to/threads/takeis-journey-v0-30-ferrum.82236/",
        # "https://f95zone.to/threads/eternum-v0-7-public-caribdis.93340/" # Example of another URL
    ]

    all_games_data = []
    logger_scraper.info(f"STANDALONE_TEST: Attempting to scrape {len(example_urls)} game pages.\n")

    for i, url in enumerate(example_urls):
        logger_scraper.info(f"--- STANDALONE_TEST: Processing game {i+1}/{len(example_urls)} ---")
        extracted_info = extract_game_data(url, username=f95_username, password=f95_password)
        if extracted_info:
            all_games_data.append(extracted_info)
            for key, value in extracted_info.items():
                display_key = key.replace('_', ' ').title()
                if isinstance(value, list):
                    logger_scraper.info(f"{display_key}:")
                    if not value or value == ["Not found"]:
                        logger_scraper.info("  - Not found")
                    else:
                        for item in value:
                            if isinstance(item, dict):
                                logger_scraper.info(f"  - Text: {item.get('text', 'N/A')}, URL: {item.get('url', 'N/A')}")
                            else:
                                logger_scraper.info(f"  - {item}")
                else:
                    logger_scraper.info(f"{display_key}: {value}")
            logger_scraper.info("=" * 70 + "\n")
    
    logger_scraper.info(f"\nSTANDALONE_TEST: Successfully processed {len(all_games_data)} games.")
    if len(all_games_data) < len(example_urls):
        logger_scraper.warning(f"STANDALONE_TEST: Note: {len(example_urls) - len(all_games_data)} game(s) could not be processed.") 