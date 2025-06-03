import requests
from bs4 import BeautifulSoup
import time # Added for potential waits
from playwright.sync_api import sync_playwright # Added for Playwright
import re # Added for regular expressions
import logging

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
        initial_login_success = False
        # More specific check based on user-provided HTML for logged-in state
        if page.query_selector("div.p-account span.p-navgroup-linkText") and page.query_selector("div.p-account span.p-navgroup-linkText").is_visible():
            username_text = page.query_selector("div.p-account span.p-navgroup-linkText").text_content()
            logger_scraper.info(f"Login Attempt: Initial indicators (username: '{username_text}') suggest login successful on {page.url}.")
            initial_login_success = True
        elif page.query_selector("a[href='/logout/']"):
            logger_scraper.info(f"Login Attempt: Initial indicators (logout link) suggest login successful on {page.url}.")
            initial_login_success = True
        else:
            logger_scraper.warning(f"Login Attempt: Initial login indicators NOT found on {page.url} after form submission. Checking for error messages.")
            # Check for common error messages like "Incorrect password" or "User not found"
            error_message_selectors = [
                ".blockMessage.blockMessage--error", # General error block
                "//div[contains(@class, 'blockMessage--error') and (contains(.,'Incorrect password') or contains(.,'not found'))]", # More specific XPath
                "li.formRow-explain", # Sometimes errors appear in form explainers
            ]
            error_found = False
            for selector in error_message_selectors:
                error_element = None
                if selector.startswith("//"):
                    error_element = page.query_selector(selector) #bs4 like
                else:
                    error_element = page.locator(selector).first if page.locator(selector).count() > 0 else None
                
                if error_element and error_element.is_visible():
                    error_text = error_element.text_content() # playwright way
                    logger_scraper.error(f"LOGIN ERROR: Detected error message after login attempt: {error_text[:100]}")
                    error_found = True
                    break
            if error_found:
                return False # Definite login failure due to error message
            # If no specific error message, but also no success indicators, it's ambiguous, but we'll treat as fail for now
            logger_scraper.error(f"Login Attempt: Login failed on {page.url}. No specific error message, but no success indicators either.")
            return False

        if not initial_login_success:
            # This case should ideally be caught by the error message check above, but as a fallback:
            logger_scraper.error(f"Login Attempt: Initial login indicators were not found on {page.url}, and no specific error message was caught. Assuming failure.")
            return False

        # If a target URL is provided, navigate there and re-verify login status
        if target_url_after_login:
            logger_scraper.info(f"Login Attempt: Initial login successful. Navigating to target URL: {target_url_after_login}")
            try:
                page.goto(target_url_after_login, wait_until="networkidle", timeout=45000)
                logger_scraper.info(f"Login Attempt: Reached target URL. Current URL: {page.url}. Verifying login status.")
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                page.wait_for_timeout(3000) # Settle time

                # Definitive check on the target page using refined selectors
                logged_in_on_target = False
                not_logged_in_on_target = False

                # Check for positive login indicators first
                if page.query_selector("div.p-account span.p-navgroup-linkText") and page.query_selector("div.p-account span.p-navgroup-linkText").is_visible():
                    username_text_target = page.query_selector("div.p-account span.p-navgroup-linkText").text_content()
                    logger_scraper.info(f"Login Attempt: CONFIRMED LOGGED IN on target page ({page.url}) based on username text: '{username_text_target}'.")
                    logged_in_on_target = True
                elif page.query_selector("a[href='/logout/']"):
                    logger_scraper.info(f"Login Attempt: CONFIRMED LOGGED IN on target page ({page.url}) based on presence of logout link.")
                    logged_in_on_target = True
                
                # If not confirmed logged in, check for explicit not logged in indicators
                if not logged_in_on_target:
                    if page.query_selector("a[href*='/login']") or page.query_selector("a[href*='/register']"):
                        logger_scraper.warning(f"Login Attempt: DEFINITIVELY NOT LOGGED IN on target page ({page.url}). Found Login/Register buttons.")
                        not_logged_in_on_target = True
                
                if logged_in_on_target:
                    return True
                elif not_logged_in_on_target:
                    return False
                else:
                    logger_scraper.warning(f"Login Attempt: LOGIN INDETERMINATE on target page ({page.url}). No specific username/logout AND no Login/Register buttons. Assuming NOT logged in.")
                    return False
            except Exception as e_target_nav:
                logger_scraper.error(f"Login Attempt: Error navigating to or checking target URL {target_url_after_login}: {e_target_nav}")
                return False
        else:
            # If no target URL, success is based on initial indicators post-form submission
            logger_scraper.info("Login Attempt: No target_url_after_login provided. Login success based on indicators on landing page after form submission.")
            return True # initial_login_success was already true to reach here

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
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        page = context.new_page()
        final_page_logged_in_status = False # Track if we are logged in on the GAME page

        if username and password:
            try:
                logger_scraper.info("EXTRACT_GAME_DATA: Navigating to login page (https://f95zone.to/login/login) to ensure fresh login attempt.")
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=30000)
                logger_scraper.info(f"EXTRACT_GAME_DATA: On login page. Current URL: {page.url}. Attempting login via login_to_f95zone function, targeting game thread url directly.")
                
                # --- ADDED SCREENSHOT: Initial Login Page (before calling login_to_f95zone) ---
                try:
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    screenshot_path = f"/data/debug_screenshot_01_initial_login_page_{timestamp}.png"
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger_scraper.info(f"EXTRACT_GAME_DATA: Saved screenshot (initial login page) to '{screenshot_path}'")
                except Exception as e_screenshot:
                    logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take screenshot (initial login page): {e_screenshot}")
                # --- END SCREENSHOT ---

                # Call login_to_f95zone, passing the game_thread_url as the target for final login verification.
                # The function will navigate to game_thread_url if initial login actions seem successful.
                final_page_logged_in_status = login_to_f95zone(page, username, password, target_url_after_login=game_thread_url)
                logger_scraper.info(f"EXTRACT_GAME_DATA: login_to_f95zone (targeting game page) returned: {final_page_logged_in_status}. Current URL: {page.url}")

                # The following blocks are now handled within login_to_f95zone or are no longer needed:
                # - POST-LOGIN_FUNC CHECK (verification is now on target_url_after_login)
                # - Navigate to base URL to help session cookies settle (target_url_after_login handles navigation)
                # - Cookie saving/loading (direct navigation to target is preferred)
                # - Separate navigation to game_thread_url (done by login_to_f95zone if target is provided)
                # - Separate login check on game page (done by login_to_f95zone if target is provided)

                # We should already be on the game page if login_to_f95zone navigated there.
                # If final_page_logged_in_status is false, it means login failed even on the target game page.

            except Exception as e_login_nav: # This might catch errors from login_to_f95zone if it raises something unexpected
                logger_scraper.error(f"EXTRACT_GAME_DATA: Error during the overall login and navigation process: {e_login_nav}", exc_info=True)
                final_page_logged_in_status = False # Ensure status reflects failure
                # Try to take a screenshot even on error here to see the page state
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                error_screenshot_path = f"/data/debug_screenshot_EXTRACT_error_{timestamp}.png"
                try:
                    page.screenshot(path=error_screenshot_path, full_page=True)
                    logger_scraper.info(f"EXTRACT_GAME_DATA: Saved error screenshot to '{error_screenshot_path}'")
                except Exception as es_err:
                    logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take error screenshot during EXCEPTION: {es_err}")
                # browser.close() # Don't close here yet, screenshot below might still be useful
                # return None # Let it proceed to screenshot and then return None if html_content is bad
        else:
            logger_scraper.info("EXTRACT_GAME_DATA: No credentials provided. Proceeding as anonymous.")
            # Navigate to game page directly if no creds
            try:
                logger_scraper.info(f"EXTRACT_GAME_DATA: Navigating to {game_thread_url} (anonymous). waited for networkidle")
                page.goto(game_thread_url, wait_until="networkidle", timeout=45000)
                logger_scraper.info(f"EXTRACT_GAME_DATA: Successfully navigated to {game_thread_url}. Current URL: {page.url}")
                page.wait_for_load_state("domcontentloaded", timeout=10000) 
                page.wait_for_timeout(2000) 
            except Exception as e_anon_nav:
                logger_scraper.error(f"EXTRACT_GAME_DATA: Error navigating to game page {game_thread_url} (anonymous): {e_anon_nav}", exc_info=True)
                # browser.close() # Screenshot below
                # return None
        
        # --- Debug Screenshot (Taken on the page state after login attempt and navigation to game thread) ---
        # This will show the state of game_thread_url, regardless of login success path.
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            screenshot_filename = f"debug_screenshot_04_gamepage_FINAL_{timestamp}.png" # Renamed for consistency
            screenshot_path = f"/data/{screenshot_filename}" 
            page.screenshot(path=screenshot_path, full_page=True)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Saved FINAL debug screenshot to '{screenshot_path}'. Logged in: {final_page_logged_in_status}")
        except Exception as e_screenshot:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to take FINAL debug screenshot: {e_screenshot}")
        # --- END Screenshot ---

        if not final_page_logged_in_status and (username and password):
             logger_scraper.warning(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url}, but login was NOT confirmed on the game page. Data might be incomplete.")
        elif final_page_logged_in_status:
             logger_scraper.info(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url} with confirmed login.")
        else: # Anonymous
             logger_scraper.info(f"EXTRACT_GAME_DATA: Proceeding with scrape on {game_thread_url} as anonymous user.")


        logger_scraper.info("EXTRACT_GAME_DATA: Attempting to find and click spoiler buttons...")
        spoiler_buttons_selector = "button.bbCodeSpoiler-button"
        try:
            spoiler_buttons = page.query_selector_all(spoiler_buttons_selector)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Found {len(spoiler_buttons)} spoiler buttons.")
            for i, button_element in enumerate(spoiler_buttons):
                try:
                    if button_element.is_visible() and button_element.is_enabled():
                        button_element.click(timeout=2000) 
                        page.wait_for_timeout(1000) # ADDED: Wait after each spoiler click
                        
                        # Minimal logging for spoiler clicks unless debugging specific spoiler issues
                        # logger_scraper.debug(f"EXTRACT_GAME_DATA: Clicked spoiler button {i+1}.")
                        
                        spoiler_container = button_element.query_selector("xpath=ancestor::div[contains(@class, 'bbCodeSpoiler')]")
                        if spoiler_container:
                            content_area = spoiler_container.query_selector("div.bbCodeSpoiler-content")
                            if content_area:
                                page.wait_for_timeout(750) 
                            # else:
                                # logger_scraper.debug(f"  Could not find content area for spoiler {i+1} after click.")
                        # else:
                            # logger_scraper.debug(f"  Could not find parent spoiler container for button {i+1}.")
                            page.wait_for_timeout(500) 
                    # else:
                        # logger_scraper.debug(f"EXTRACT_GAME_DATA: Spoiler button {i+1} is not visible or enabled, skipping.")
                except Exception as e_click_spoiler:
                    logger_scraper.warning(f"EXTRACT_GAME_DATA: Could not click or process spoiler button {i+1}: {e_click_spoiler}")
            logger_scraper.info("EXTRACT_GAME_DATA: Finished attempting to click spoiler buttons.")
        except Exception as e_find_spoilers:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Error finding or interacting with spoiler buttons: {e_find_spoilers}", exc_info=True)

        page.wait_for_timeout(5000) # Wait after all spoiler clicks

        logger_scraper.debug(f"EXTRACT_GAME_DATA: Getting HTML content after spoiler clicks. Current URL: {page.url}")
        html_content = page.content()
        
        if not html_content:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Failed to get HTML content for {game_thread_url} using Playwright.")
            browser.close()
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        browser.close()
        logger_scraper.info(f"EXTRACT_GAME_DATA: Browser closed for {game_thread_url}.")


        data = {
            "url": game_thread_url, # Store the URL that was *actually processed* by this instance
            "title": None, "version": None, "author": "Not found", "tags": [], # Initialize author to "Not found"
            "full_description": None, "changelog": None, "download_links": [],
            "engine": None, "language": None, "status": None, "censorship": None,
        }

        if title_tag := soup.find('h1', class_='p-title-value'):
            data['title'] = title_tag.get_text(strip=True)
        elif page_title_element := soup.find('title'):
            data['title'] = page_title_element.get_text(strip=True).replace(" | F95zone", "")
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted title: {data['title']}")

        # --- Author Extraction - Step 1: Attempt inference from title (will be lowest priority) ---
        inferred_author_from_title = "Not found"
        if data['title']:
            author_match_title = re.search(r'(?:\[|\()([^\[\]()]*?)(?:\]|\))\s*$', data['title'])
            if author_match_title:
                potential_author_title = author_match_title.group(1).strip()
                if not re.fullmatch(r'v?\d+(\.\d+)*\w*', potential_author_title, re.IGNORECASE) and len(potential_author_title) > 2:
                    inferred_author_from_title = potential_author_title
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Tentatively inferred author from title: {inferred_author_from_title}")
        # --- End Author Title Inference ---
            
        # --- Engine: Look for common engine names (moved before title-based author to avoid conflict) ---
        # This is a simplified check; more robust would list known engines
        engine_keywords = ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal engine', 'qsp', 'tyranobuilder', 'wolf rpg']
        title_lower = data['title'].lower()
        for eng_key in engine_keywords:
            if eng_key in title_lower:
                # Try to extract the exact casing from original title if found in brackets/parentheses
                engine_match_in_brackets = re.search(r'(?:\[|\()(' + re.escape(eng_key) + r')(?:\]|\))', data['title'], re.IGNORECASE)
                if engine_match_in_brackets and (not data['engine'] or data['engine'] == 'Not found'):
                    data['engine'] = engine_match_in_brackets.group(1)
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred engine from title (in brackets): {data['engine']}")
                    break
                # Else, use the keyword itself if found and no engine yet
                elif (not data['engine'] or data['engine'] == 'Not found'):
                    # Find the original casing if possible
                    try:
                        start_index = title_lower.find(eng_key)
                        original_casing_engine = data['title'][start_index : start_index + len(eng_key)]
                        data['engine'] = original_casing_engine
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred engine from title (substring): {data['engine']}")
                        break
                    except: # Should not happen with `in` check, but as a safeguard
                        pass
        # --- END Engine from Title ---

        # --- Author Extraction - Step 2: From first post userDetails (after title inference, before DL/Desc) ---
        author_from_post_details = "Not found"
        first_post_article = soup.find('article', class_='message--post') 
        if first_post_article:
            user_details_div = first_post_article.find('div', class_='message-userDetails')
            if user_details_div:
                author_link_tag = user_details_div.find('a', class_='username')
                if author_link_tag:
                    author_from_post_details = author_link_tag.get_text(strip=True)
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from post details: {author_from_post_details}")
                else:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Author link not found within first post's userDetails.")
            else:
                logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): userDetails div not found in the first post.")
        else:
            logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): First post article not found for author extraction.")
        
        # Assign from post details if current data['author'] is "Not found" or if post author is not numeric
        # while inferred_from_title might be better than a numeric ID.
        if data['author'] == "Not found":
            if author_from_post_details != "Not found":
                data['author'] = author_from_post_details
        elif author_from_post_details != "Not found" and not author_from_post_details.isdigit():
             data['author'] = author_from_post_details
        elif author_from_post_details != "Not found" and author_from_post_details.isdigit() and inferred_author_from_title != "Not found":
            # If post author is numeric, but we have a non-numeric title inference, prefer title inference over numeric ID
            data['author'] = inferred_author_from_title
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Post author ('{author_from_post_details}') is numeric. Using inferred author from title ('{inferred_author_from_title}') instead.")
        elif author_from_post_details != "Not found" and author_from_post_details.isdigit() and inferred_author_from_title == "Not found":
            # If post author is numeric and no title inference, use numeric post author for now
            data['author'] = author_from_post_details


        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author after post/title check: {data['author']}")
        # --- End Author Post Details ---

        first_post_article_content = soup.find('article', class_='message--post')
        bb_wrapper = first_post_article_content.find('div', class_='bbWrapper') if first_post_article_content else None

        if bb_wrapper:
            desc_elements = []
            for elem in bb_wrapper.children:
                if elem.name and (elem.name.startswith('h') or (elem.name == 'div' and 'Spoiler' in elem.get('class', []))):
                    text_check = elem.get_text(strip=True).lower()
                    if any(kw in text_check for kw in ['download', 'changelog', 'what\'s new', 'version history', 'updates']):
                        break
                if isinstance(elem, str):
                    desc_elements.append(elem.strip())
                elif elem.name not in ['script', 'style']:
                    desc_elements.append(elem.get_text(separator='\n', strip=True))
            
            data['full_description'] = "\n".join(filter(None, desc_elements)).strip() or \
                                       bb_wrapper.get_text(separator='\n', strip=True)

            description_snippet_log = (data['full_description'][:200] + '...') if data['full_description'] and len(data['full_description']) > 200 else data['full_description']
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Description snippet: {description_snippet_log}")

            # --- Refined Changelog Extraction from Spoiler ---
            changelog_text_parts = []
            possible_changelog_headers = ['changelog', "what's new", "update notes", "version history", "updates"] # Keep this broad for headers
            
            # First, specifically look for a spoiler with "Changelog" in its button text
            spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            found_changelog_spoiler = False
            for spoiler in spoilers:
                button = spoiler.find('button', class_='bbCodeSpoiler-button')
                content = spoiler.find('div', class_='bbCodeSpoiler-content')
                if button and content and "changelog" in button.get_text(strip=True).lower():
                    changelog_text_parts.append(content.get_text(separator='\n', strip=True))
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog directly from 'Changelog' spoiler.")
                    found_changelog_spoiler = True
                    break # Found the primary changelog spoiler

            # Fallback to searching headers if no specific "Changelog" spoiler was found
            if not found_changelog_spoiler:
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No specific 'Changelog' spoiler found. Searching for headers: {possible_changelog_headers}")
                for header_tag_name in ['strong', 'h2', 'h3', 'h4', 'p']: # Added 'p' for cases where it might be a paragraph header
                    headers = bb_wrapper.find_all(header_tag_name)
                    for header in headers:
                        header_text_lower = header.get_text(strip=True).lower()
                        if any(ch_kw in header_text_lower for ch_kw in possible_changelog_headers) and len(header_text_lower) < 50: # Avoid very long paragraph matches
                            # Check if the header itself is inside a spoiler button, if so, skip (already handled or will be by spoiler logic)
                            if header.find_parent('button', class_='bbCodeSpoiler-button'):
                                continue

                            next_content_elements = []
                            # Try to get content from an adjacent spoiler if the header is right before it
                            next_sibling_spoiler = header.find_next_sibling('div', class_='bbCodeSpoiler')
                            if next_sibling_spoiler:
                                spoiler_content_div = next_sibling_spoiler.find('div', class_='bbCodeSpoiler-content')
                                if spoiler_content_div:
                                    next_content_elements.append(spoiler_content_div.get_text(separator='\n', strip=True))
                                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog from spoiler adjacent to header '{header.get_text(strip=True)}'.")

                            # If no adjacent spoiler, collect text from subsequent siblings
                            if not next_content_elements:
                                for sibling in header.find_next_siblings():
                                    if sibling.name and (sibling.name.startswith('h') or (sibling.name == 'div' and 'Spoiler' in sibling.get('class', [])) or \
                                                        any(ch_kw in sibling.get_text(strip=True).lower() for ch_kw in possible_changelog_headers if len(sibling.get_text(strip=True)) < 50 ) ): # Stop at next major section or another changelog-like header
                                        break
                                    next_content_elements.append(sibling.get_text(separator='\n', strip=True))
                                if next_content_elements:
                                     logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog from content following header '{header.get_text(strip=True)}'.")
                            
                            if next_content_elements:
                                changelog_text_parts.append("\n".join(filter(None, next_content_elements)).strip())
                                found_changelog_spoiler = True # Mark as found to stop searching other header types
                                break 
                    if found_changelog_spoiler:
                        break
            
            if changelog_text_parts:
                data['changelog'] = "\n---\n".join(changelog_text_parts).strip()
            else:
                data['changelog'] = "Not clearly identified"
            # --- End Refined Changelog Extraction ---
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog (first 100 chars): {data['changelog'][:100] if data['changelog'] else 'None'}")

            # --- Enhanced Download Link Extraction ---
            data['download_links'] = [] # Reset before populating
            
            # Strategy 1: Find sections explicitly marked "DOWNLOAD" or similar
            download_section_headers = bb_wrapper.find_all(['strong', 'b', 'h1', 'h2', 'h3', 'h4', 'p'])
            potential_download_areas = []

            for header in download_section_headers:
                header_text_lower = header.get_text(strip=True).lower()
                if "download" in header_text_lower and len(header_text_lower) < 30: # Avoid matching long paragraphs
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found potential download section header: '{header.get_text(strip=True)}'")
                    # Try to find a container element for this download section
                    # This could be the header's parent, or siblings until the next major header
                    current_element = header
                    while current_element and current_element.name not in ['article', 'div', 'section', 'ul', 'ol', 'p'] : # Common block containers
                        current_element = current_element.parent
                    if current_element and current_element not in potential_download_areas :
                         potential_download_areas.append(current_element) # Add the container
                    else: # Fallback: just take a few next siblings if no clear container
                        sibling_area = []
                        for sib in header.find_next_siblings(limit=5): # Limit to avoid grabbing too much
                            if sib.name and (sib.name.startswith('h') or (sib.name == 'div' and 'Spoiler' in sib.get('class', []))): # Stop at next major section
                                break
                            sibling_area.append(sib)
                        if sibling_area:
                             # Create a temporary BeautifulSoup object from these siblings to search within them
                            temp_soup_str = "".join(str(s) for s in sibling_area)
                            potential_download_areas.append(BeautifulSoup(temp_soup_str, 'html.parser'))


            if not potential_download_areas: # If no specific download headers found, search the whole bbWrapper
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No specific 'DOWNLOAD' headers found. Searching entire bbWrapper for links.")
                potential_download_areas.append(bb_wrapper)

            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Identified {len(potential_download_areas)} potential areas to search for download links.")

            for area_idx, search_area in enumerate(potential_download_areas):
                if not search_area: continue # Should not happen, but safeguard
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Searching for links in area {area_idx + 1}...")
                
                # Look for <a> tags with href
                links_in_area = search_area.find_all('a', href=True)
                for link in links_in_area:
                    href = link['href']
                    text = link.get_text(strip=True)

                    # Filter out common non-download links more aggressively
                    if not href or href.startswith('#') or href.startswith('mailto:') or "javascript:void" in href:
                        continue
                    if "f95zone.to/threads/" in href and not any(ext in href.lower() for ext in ['.zip', '.rar', '.apk', '.7z', '.exe']): # Allow thread links if they point to files
                        if not ("mod" in text.lower() or "patch" in text.lower() or "translation" in text.lower()): # but not if they are just other threads without clear indication
                            continue
                    if "members/" in href or "login" in href or "register" in href or "account" in href: # Skip profile/login links
                        continue
                    
                    # If link text is generic like "you must be registered", try to find more context
                    # For now, we'll accept them if they are under a "DOWNLOAD" header,
                    # as the login should have made them real.
                    
                    # Avoid duplicates
                    is_duplicate = any(dl['url'] == href and dl['text'] == text for dl in data['download_links'])
                    if not is_duplicate:
                        data['download_links'].append({"text": text, "url": href})
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Added download link from area {area_idx + 1}: '{text}' -> '{href}'")

            # Strategy 2: Button-based links (keep existing logic but apply to identified areas if possible)
            # This might be redundant if the above captures them, but can be a fallback.
            # For now, let's simplify and rely on the <a> tag search in identified areas.
            # (Original button logic could be re-added here if needed, scoped to search_area)

            # --- Fallback: Original broad search if no links found in specific sections and section search was attempted ---
            if not data['download_links'] and len(potential_download_areas) > 1 : # More than 1 means specific areas were tried
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No links found in specific download sections, doing a broader search in bbWrapper for <a> tags.")
                original_links = bb_wrapper.find_all('a', href=True)
                for link in original_links:
                    href = link['href']
                    text = link.get_text(strip=True)
                    dl_keywords = ['download', 'mega', 'mediafire', 'zippy', 'gdrive', 'google drive', 'pixeldrain', 'workupload', 'itch.io/']
                    file_exts = ['.zip', '.rar', '.apk', '.7z', '.exe']
                    
                    is_dl_link_text = any(keyword in text.lower() for keyword in dl_keywords)
                    is_dl_link_href = any(keyword in href.lower() for keyword in dl_keywords)
                    is_file_ext_in_href = any(ext in href.lower() for ext in file_exts)
                    is_not_mailto = not href.startswith('mailto:')
                    # Allow internal links if they contain file extensions or known DL keywords in text/href
                    is_relevant_internal_link = 'f95zone.to/threads/' not in href or is_file_ext_in_href or is_dl_link_href or "mod" in text.lower()

                    if (is_dl_link_text or is_dl_link_href or is_file_ext_in_href) and is_not_mailto and is_relevant_internal_link:
                        is_duplicate = any(dl['url'] == href and dl['text'] == text for dl in data['download_links'])
                        if not is_duplicate:
                            data['download_links'].append({"text": text, "url": href})
                            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Added download link (fallback broad search): '{text}' -> '{href}'")
            
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found {len(data['download_links'])} download links after all strategies.")
            # --- End Enhanced Download Link Extraction ---

        # --- Refined Tags (Genre) Extraction from Spoiler ---
        data['tags'] = [] # Initialize/reset
        genre_spoiler_found = False
        if bb_wrapper: # Ensure bb_wrapper exists
            spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            for spoiler in spoilers:
                button = spoiler.find('button', class_='bbCodeSpoiler-button')
                content_div = spoiler.find('div', class_='bbCodeSpoiler-content')
                if button and content_div and "genre" in button.get_text(strip=True).lower():
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found 'Genre' spoiler: '{button.get_text(strip=True)}'")
                    raw_tags_text = content_div.get_text(separator=',', strip=True) # Get text, using comma as a hopeful separator
                    if raw_tags_text:
                        # Split by comma, then strip each item. Filter out empty strings.
                        parsed_tags = [tag.strip() for tag in raw_tags_text.split(',') if tag.strip()]
                        data['tags'].extend(parsed_tags)
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted tags from 'Genre' spoiler: {data['tags']}")
                        genre_spoiler_found = True
                    else:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): 'Genre' spoiler content was empty.")
                    break # Found the genre spoiler

        # Fallback to existing tag extraction if Genre spoiler not found or empty
        if not genre_spoiler_found:
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): 'Genre' spoiler not found or empty. Falling back to original tag selectors.")
            if tags_container := soup.find('div', class_='tagGroup'):
                tag_links = tags_container.find_all('a', class_='tagItem')
                for tag_link in tag_links:
                    tag_text = tag_link.get_text(strip=True)
                    if tag_text not in data['tags']: data['tags'].append(tag_text)
            elif tags_dt := soup.find('dt', string=lambda t: t and 'tags' in t.lower()):
                if tags_dd := tags_dt.find_next_sibling('dd'): 
                    tag_links = tags_dd.find_all('a')
                    for tag_link in tag_links:
                        tag_text = tag_link.get_text(strip=True)
                        if tag_text not in data['tags']: data['tags'].append(tag_text)
        # --- End Refined Tags Extraction ---
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted tags (final): {data['tags']}")


        prefix_elements = soup.find_all('span', class_=lambda x: x and x.startswith('label'))
        for prefix_el in prefix_elements:
            text = prefix_el.get_text(strip=True).lower()
            if not data['engine'] and any(eng_name in text for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'tyranobuilder', 'wolf rpg', 'unreal engine', 'qsp', 'rags']):
                data['engine'] = prefix_el.get_text(strip=True)
            if not data['status'] and any(st_name in text for st_name in ['completed', 'ongoing', 'on hold', 'abandoned', 'hiatus']):
                data['status'] = prefix_el.get_text(strip=True)

        dls = soup.find_all('dl', class_=['pairs--columns', 'block-body-infoPairs', 'pairs--justified'])
        for dl_element in dls:
            dt_elements = dl_element.find_all('dt')
            for dt in dt_elements:
                dt_text = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling('dd')
                if not dd:
                    continue
                
                dd_text = dd.get_text(strip=True)
                if 'engine' in dt_text and not data['engine']:
                    data['engine'] = dd_text
                elif 'language' in dt_text and not data['language']:
                    data['language'] = dd_text
                elif 'status' in dt_text and (not data['status'] or data['status'] == "Not found"): # Allow DL to set status if not already set well
                    data['status'] = dd_text
                elif 'censorship' in dt_text and not data['censorship']:
                    data['censorship'] = dd_text
                elif 'developer' in dt_text : # Capture developer from DL list
                    if dd_text and dd_text != "Not found":
                        author_from_dl_list = dd_text
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author found in DL list: '{author_from_dl_list}' (under 'developer' dt).")
                elif 'version' in dt_text and (not data['version'] or data['version'] == "Not found"):
                     data['version'] = dd_text
        
        # Consolidate Author based on priority:
        # 1. Developer from description (developer_from_description_text)
        # 2. Developer from DL list (author_from_dl_list)
        # 3. Author from post details (already in data['author'] or refined with title inference)
        # 4. Author inferred from title (only if data['author'] is still "Not found" or numeric post author was placeholder)

        developer_from_description_text = "Not found"
        if data['author'] != developer_from_description_text:
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Prioritizing Developer from description ('{developer_from_description_text}') for Author over current ('{data['author']}').")
            data['author'] = developer_from_description_text
        elif author_from_dl_list != "Not found":
            if data['author'] == "Not found" or data['author'].isdigit() or data['author'] == inferred_author_from_title: 
                # Use DL if current is placeholder, numeric, or just the title inference
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Using Author from DL list ('{author_from_dl_list}') as current is ('{data['author']}').")
                data['author'] = author_from_dl_list
            else:
                 logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from DL list ('{author_from_dl_list}') found, but keeping current non-placeholder author ('{data['author']}').")
        elif data['author'] == "Not found" and inferred_author_from_title != "Not found":
            # Last resort: if nothing else and title inference exists
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Using Author from title inference ('{inferred_author_from_title}') as last resort.")
            data['author'] = inferred_author_from_title

        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Final Author after all checks: {data['author']}")
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): After dls & final author - Engine: {data['engine']}, Lang: {data['language']}, Status: {data['status']}, Cens: {data['censorship']}, Version: {data['version']}")

        # --- Clean title if engine name is a prefix (ensure this runs after final engine is set) ---
        if data['title'] and data['engine'] and data['engine'] != "Not found":
            if data['title'].lower().startswith(data['engine'].lower()):
                # Find the length of the engine string in the title to slice accurately
                # This handles cases where engine is 'Ren'Py' and title is 'Ren'PyGame Name'
                engine_len_in_title = -1
                try:
                    # re.escape to handle special characters in engine name like in Ren'Py
                    match_engine_prefix = re.match(re.escape(data['engine']), data['title'], re.IGNORECASE)
                    if match_engine_prefix:
                        engine_len_in_title = len(match_engine_prefix.group(0))
                except re.error:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Regex error trying to match engine '{data['engine']}' in title for cleaning. Skipping title clean for engine prefix.")

                if engine_len_in_title > 0 and len(data['title']) > engine_len_in_title:
                    original_title_for_log = data['title']
                    data['title'] = data['title'][engine_len_in_title:].lstrip(' -:') # Remove engine and any leading separators
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Cleaned title from '{original_title_for_log}' to '{data['title']}' by removing engine prefix '{data['engine']}'.")
                elif engine_len_in_title > 0 and len(data['title']) == engine_len_in_title:
                     logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Title '{data['title']}' seems to be only the engine name '{data['engine']}'. Not cleaning.")
        # --- END Clean title if engine name is a prefix ---

        if isinstance(data['tags'], list):
            for tag_text_lower in [t.lower() for t in data['tags']]:
                if not data['engine'] and any(eng_name in tag_text_lower for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal']):
                    for original_tag in data['tags']:
                        if original_tag.lower() == tag_text_lower:
                            data['engine'] = original_tag
                            break
                if not data['status'] and any(st_name in tag_text_lower for st_name in ['completed', 'ongoing', 'on-hold', 'abandoned']):
                    for original_tag in data['tags']:
                        if original_tag.lower() == tag_text_lower:
                            data['status'] = original_tag
                            break
                if not data['censorship'] and any(cen_kw in tag_text_lower for cen_kw in ['uncensored', 'censored']):
                    for original_tag in data['tags']:
                        if original_tag.lower() == tag_text_lower:
                            data['censorship'] = original_tag
                            break
        
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): After tags inference - Engine: {data['engine']}, Status: {data['status']}, Cens: {data['censorship']}")

        # --- ADDED: Parse full_description for more details as a fallback ---
        developer_from_description_text = "Not found"
        if data['full_description']:
            desc_text_to_search = data['full_description'] # Use original casing for extraction, lower for matching
            desc_text_lower = desc_text_to_search.lower()
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Attempting to parse details from full_description. Snippet: {desc_text_to_search[:300]}")

            # Language
            if not data['language'] or data['language'] == "Not found":
                # Regex: "language" (optional 's'), optional colon, optional spaces/newlines, then capture group.
                # Capture group: word characters, spaces, commas, 'and'.
                lang_match = re.search(r"language(?:s)?\\s*\\n*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
                if lang_match:
                    try:
                        original_lang_text = desc_text_to_search[lang_match.start(1):lang_match.end(1)]
                        data['language'] = original_lang_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred language from description: '{data['language']}'")
                    except Exception as e_lang_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original language casing: {e_lang_extract}, using lower: '{lang_match.group(1).strip()}'")
                        data['language'] = lang_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Language pattern not found in description.")
            
            # Censorship
            if not data['censorship'] or data['censorship'] == "Not found":
                # Regex: "censored" (optional 'd'), optional colon, optional spaces/newlines, then capture group for the value.
                # Capture group: one or more word characters (e.g., "Yes", "No", "Partial")
                censorship_match = re.search(r"censor(?:ed)?\\s*\\n*:\\s*([\\w\\-]+)", desc_text_lower, re.IGNORECASE)
                if censorship_match:
                    try:
                        original_cens_text = desc_text_to_search[censorship_match.start(1):censorship_match.end(1)]
                        data['censorship'] = original_cens_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred censorship from description: '{data['censorship']}'")
                    except Exception as e_cens_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original censorship casing: {e_cens_extract}, using lower: '{censorship_match.group(1).strip()}'")
                        data['censorship'] = censorship_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Censorship pattern not found in description.")

            # Version (if not found by title or dl list)
            if not data['version'] or data['version'] == "Not found":
                # Regex: "version", optional colon, optional spaces/newlines, then capture group.
                # Capture group: word chars, dots, hyphens (e.g., "0.1.2b", "1.0-final")
                version_desc_match = re.search(r"version\\s*:\\s*([\\w\\.\\-]+)", desc_text_lower, re.IGNORECASE)
                if version_desc_match:
                    try:
                        original_ver_text = desc_text_to_search[version_desc_match.start(1):version_desc_match.end(1)]
                        data['version'] = original_ver_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred version from description: '{data['version']}'")
                    except Exception as e_ver_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original version casing: {e_ver_extract}, using lower: '{version_desc_match.group(1).strip()}'")
                        data['version'] = version_desc_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Version pattern not found in description.")
            
            # OS
            # Regex: "os", optional colon, optional spaces/newlines, then capture group.
            # Capture group: word characters, spaces, commas, 'and'.
            # MODIFIED to handle newline between keyword and colon
            os_match = re.search(r"os\\s*\\n*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
            if os_match:
                try:
                    original_os_text = desc_text_to_search[os_match.start(1):os_match.end(1)]
                    # This field is not directly stored in data['os'] yet, just logged for now.
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found OS info in description: '{original_os_text.strip()}'")
                except Exception as e_os_extract:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original OS casing: {e_os_extract}, using lower: '{os_match.group(1).strip()}'")
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found OS info in description (lower): '{os_match.group(1).strip()}'")
            else:
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): OS pattern not found in description.")

            # --- Author Extraction - Step 4 (was 1 before): Developer from description (Highest Priority) ---
            # This is parsed within the full_description block later on.
            # We will capture it there and then use it to finalize author at the end of all parsing.

            if not data['language'] or data['language'] == "Not found":
                # Regex: "language" (optional 's'), optional colon, optional spaces/newlines, then capture group.
                # Capture group: word characters, spaces, commas, 'and'.
                lang_match = re.search(r"language(?:s)?\\s*\\n*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
                if lang_match:
                    try:
                        original_lang_text = desc_text_to_search[lang_match.start(1):lang_match.end(1)]
                        data['language'] = original_lang_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred language from description: '{data['language']}'")
                    except Exception as e_lang_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original language casing: {e_lang_extract}, using lower: '{lang_match.group(1).strip()}'")
                        data['language'] = lang_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Language pattern not found in description.")
            
            # Censorship
            if not data['censorship'] or data['censorship'] == "Not found":
                # Regex: "censored" (optional 'd'), optional colon, optional spaces/newlines, then capture group for the value.
                # Capture group: one or more word characters (e.g., "Yes", "No", "Partial")
                censorship_match = re.search(r"censor(?:ed)?\\s*\\n*:\\s*([\\w\\-]+)", desc_text_lower, re.IGNORECASE)
                if censorship_match:
                    try:
                        original_cens_text = desc_text_to_search[censorship_match.start(1):censorship_match.end(1)]
                        data['censorship'] = original_cens_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred censorship from description: '{data['censorship']}'")
                    except Exception as e_cens_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original censorship casing: {e_cens_extract}, using lower: '{censorship_match.group(1).strip()}'")
                        data['censorship'] = censorship_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Censorship pattern not found in description.")

            # Version (if not found by title or dl list)
            if not data['version'] or data['version'] == "Not found":
                # Regex: "version", optional colon, optional spaces/newlines, then capture group.
                # Capture group: word chars, dots, hyphens (e.g., "0.1.2b", "1.0-final")
                version_desc_match = re.search(r"version\\s*:\\s*([\\w\\.\\-]+)", desc_text_lower, re.IGNORECASE)
                if version_desc_match:
                    try:
                        original_ver_text = desc_text_to_search[version_desc_match.start(1):version_desc_match.end(1)]
                        data['version'] = original_ver_text.strip()
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred version from description: '{data['version']}'")
                    except Exception as e_ver_extract:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original version casing: {e_ver_extract}, using lower: '{version_desc_match.group(1).strip()}'")
                        data['version'] = version_desc_match.group(1).strip()
                else:
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Version pattern not found in description.")
            
            # OS
            # Regex: "os", optional colon, optional spaces/newlines, then capture group.
            # Capture group: word characters, spaces, commas, 'and'.
            # MODIFIED to handle newline between keyword and colon
            os_match = re.search(r"os\\s*\\n*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
            if os_match:
                try:
                    original_os_text = desc_text_to_search[os_match.start(1):os_match.end(1)]
                    # This field is not directly stored in data['os'] yet, just logged for now.
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found OS info in description: '{original_os_text.strip()}'")
                except Exception as e_os_extract:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original OS casing: {e_os_extract}, using lower: '{os_match.group(1).strip()}'")
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found OS info in description (lower): '{os_match.group(1).strip()}'")
            else:
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): OS pattern not found in description.")

            # Developer (capture it here)
            dev_match = re.search(r"developer\\s*\\n*:\\s*([^\\n\\r<]+)", desc_text_lower, re.IGNORECASE)
            if dev_match:
                try:
                    original_dev_text = desc_text_to_search[dev_match.start(1):dev_match.end(1)].strip()
                    if len(original_dev_text) > 0 and len(original_dev_text) < 100 and '<' not in original_dev_text:
                        developer_from_description_text = original_dev_text
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Developer parsed from description: '{developer_from_description_text}'")
                    else:
                        logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Developer text from desc ('{original_dev_text}') invalid/long.")
                except Exception as e_dev_extract:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Error extracting original developer casing for desc: {e_dev_extract}")
                    dev_name_lower = dev_match.group(1).strip()
                    if len(dev_name_lower) > 0 and len(dev_name_lower) < 100 and '<' not in dev_name_lower:
                       developer_from_description_text = dev_name_lower
                       logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Developer parsed from description (fallback lower): '{developer_from_description_text}'")
            else:
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Developer pattern not found in description.")
            # --- End Developer from description capture ---

        else:
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No full_description available to parse for further details.")
        # --- END Description Parsing Fallbacks ---

        # --- Author Extraction - Step 3: From DL lists ---
        author_from_dl_list = "Not found"
        dls = soup.find_all('dl', class_=['pairs--columns', 'block-body-infoPairs', 'pairs--justified'])
        for dl_element in dls:
            dt_elements = dl_element.find_all('dt')
            for dt in dt_elements:
                dt_text = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling('dd')
                if not dd:
                    continue
                
                dd_text = dd.get_text(strip=True)
                if 'engine' in dt_text and not data['engine']:
                    data['engine'] = dd_text
                elif 'language' in dt_text and not data['language']:
                    data['language'] = dd_text
                elif 'status' in dt_text and (not data['status'] or data['status'] == "Not found"): # Allow DL to set status if not already set well
                    data['status'] = dd_text
                elif 'censorship' in dt_text and not data['censorship']:
                    data['censorship'] = dd_text
                elif 'developer' in dt_text : # Capture developer from DL list
                    if dd_text and dd_text != "Not found":
                        author_from_dl_list = dd_text
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author found in DL list: '{author_from_dl_list}' (under 'developer' dt).")
                elif 'version' in dt_text and (not data['version'] or data['version'] == "Not found"):
                     data['version'] = dd_text
        
        # Consolidate Author based on priority:
        # 1. Developer from description (developer_from_description_text)
        # 2. Developer from DL list (author_from_dl_list)
        # 3. Author from post details (already in data['author'] or refined with title inference)
        # 4. Author inferred from title (only if data['author'] is still "Not found" or numeric post author was placeholder)

        if developer_from_description_text != "Not found":
            if data['author'] != developer_from_description_text:
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Prioritizing Developer from description ('{developer_from_description_text}') for Author over current ('{data['author']}').")
                data['author'] = developer_from_description_text
        elif author_from_dl_list != "Not found":
            if data['author'] == "Not found" or data['author'].isdigit() or data['author'] == inferred_author_from_title: 
                # Use DL if current is placeholder, numeric, or just the title inference
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Using Author from DL list ('{author_from_dl_list}') as current is ('{data['author']}').")
                data['author'] = author_from_dl_list
            else:
                 logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from DL list ('{author_from_dl_list}') found, but keeping current non-placeholder author ('{data['author']}').")
        elif data['author'] == "Not found" and inferred_author_from_title != "Not found":
            # Last resort: if nothing else and title inference exists
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Using Author from title inference ('{inferred_author_from_title}') as last resort.")
            data['author'] = inferred_author_from_title

        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Final Author after all checks: {data['author']}")
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): After dls & final author - Engine: {data['engine']}, Lang: {data['language']}, Status: {data['status']}, Cens: {data['censorship']}, Version: {data['version']}")

        # --- Clean title if engine name is a prefix (ensure this runs after final engine is set) ---
        if data['title'] and data['engine'] and data['engine'] != "Not found":
            if data['title'].lower().startswith(data['engine'].lower()):
                # Find the length of the engine string in the title to slice accurately
                # This handles cases where engine is 'Ren'Py' and title is 'Ren'PyGame Name'
                engine_len_in_title = -1
                try:
                    # re.escape to handle special characters in engine name like in Ren'Py
                    match_engine_prefix = re.match(re.escape(data['engine']), data['title'], re.IGNORECASE)
                    if match_engine_prefix:
                        engine_len_in_title = len(match_engine_prefix.group(0))
                except re.error:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Regex error trying to match engine '{data['engine']}' in title for cleaning. Skipping title clean for engine prefix.")

                if engine_len_in_title > 0 and len(data['title']) > engine_len_in_title:
                    original_title_for_log = data['title']
                    data['title'] = data['title'][engine_len_in_title:].lstrip(' -:') # Remove engine and any leading separators
                    logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Cleaned title from '{original_title_for_log}' to '{data['title']}' by removing engine prefix '{data['engine']}'.")
                elif engine_len_in_title > 0 and len(data['title']) == engine_len_in_title:
                     logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Title '{data['title']}' seems to be only the engine name '{data['engine']}'. Not cleaning.")
        # --- END Clean title if engine name is a prefix ---

        for key, value in data.items():
            if value is None:
                data[key] = "Not found"
            elif isinstance(value, list) and not value:
                data[key] = ["Not found"] if key in ["tags", "download_links"] else "Not found"

    # CRITICAL LOG: Final dictionary to be returned, ensure it includes the URL it was for.
    logger_scraper.info(f"SCRAPER_RETURN (URL: {game_thread_url}): Final data dictionary after all processing including title inference: {data}")
    return data

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