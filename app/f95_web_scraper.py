import requests
from bs4 import BeautifulSoup
import time # Added for potential waits
from playwright.sync_api import sync_playwright # Added for Playwright
import re # Added for regular expressions
import logging

# Create a logger specific to this module
logger_scraper = logging.getLogger(__name__) # Use __name__ for module-level logger

# --- Playwright Login Function ---
def login_to_f95zone(page, username, password):
    """
    Logs into F95zone using Playwright.
    Assumes the page is already navigated to the login page or a page that redirects to login.
    """
    try:
        logger_scraper.info("Login Attempt: Initiated.")
        
        # --- ADDED: Check if already logged in on the current page --- 
        # This check is done on the page provided to this function.
        logger_scraper.info(f"Login Attempt: Current URL at start of login_to_f95zone: {page.url}")
        if page.query_selector("a[href='/logout/']") or page.query_selector(".p-account") or page.query_selector("a.p-navgroup-link--username"):
            logger_scraper.info("Login Attempt: Already logged in (detected logout link, account element, or username link on current page). Skipping form fill/click.")
            return True
        # --- END ADDED CHECK ---

        page.fill("input[name='login']", username)
        logger_scraper.info("Login Attempt: Filled username.")
        page.fill("input[name='password']", password)
        logger_scraper.info("Login Attempt: Filled password.")

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
                logger_scraper.info(f"Login Attempt: Found login button. Attempting click now...")
                button_to_click.click(timeout=25000) 
                logger_scraper.info("Login Attempt: Playwright click() call for login button completed.")
            except Exception as e_click_wait:
                logger_scraper.error(f"LOGIN ERROR: Error during the click action itself: {e_click_wait}")
                return False
        else:
            logger_scraper.error("LOGIN ERROR: Could not find a clickable login button on the page after all fallbacks.")
            logger_scraper.error(f"LOGIN ERROR: Current URL when failing to find login button: {page.url}")
            return False

        logger_scraper.info("Login Attempt: Waiting for login result indicator...")
        try:
            page.wait_for_selector(
                "a[href='/logout/'], .blockMessage.blockMessage--error, a.p-navgroup-link--username", 
                timeout=15000
            )
            logger_scraper.info(f"Login Attempt: Login result indicator found. Current URL: {page.url}")
        except Exception as e_wait_indicator:
            logger_scraper.warning(f"Login Attempt: Timeout or error waiting for login result indicator. Error: {e_wait_indicator}")
            logger_scraper.info(f"Login Attempt: Current URL after login click attempt and wait for indicator: {page.url}")
            # Even if wait times out, proceed to check selectors directly as a fallback

        if page.query_selector("a[href='/logout/']") or page.query_selector(".p-account") or page.query_selector("a.p-navgroup-link--username"):
            logger_scraper.info("Login Attempt: Logout link or account element or username link found. Login appears successful.")
            logger_scraper.info(f"Login Attempt: Current URL after successful login check: {page.url}")
            return True
        else:
            logger_scraper.error(f"Login Attempt: Login failed. No specific error message or success indicator found. URL after attempt: {page.url}")
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
    # CRITICAL LOG: Log the received game_thread_url AT THE VERY START
    logger_scraper.info(f"EXTRACT_GAME_DATA: Entered function. Initial game_thread_url='{game_thread_url}', Username provided: {'Yes' if username else 'No'}.")
    
    # This log was previously print(), now using logger.
    logger_scraper.info(f"EXTRACT_GAME_DATA: Starting extraction for: {game_thread_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        page = context.new_page()

        logged_in = False
        if username and password:
            try:
                logger_scraper.info("EXTRACT_GAME_DATA: Navigating to login page for authentication...")
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=30000)
                logger_scraper.info(f"EXTRACT_GAME_DATA: On login page. Current URL: {page.url}")
                if login_to_f95zone(page, username, password):
                    logger_scraper.info("EXTRACT_GAME_DATA: Login function returned True.")
                    logged_in = True
                else:
                    logger_scraper.warning("EXTRACT_GAME_DATA: Login function returned False. Scraping will proceed without authentication.")
            except Exception as e_login_nav:
                logger_scraper.error(f"EXTRACT_GAME_DATA: Error navigating to login page or during login process: {e_login_nav}", exc_info=True)
                logger_scraper.warning("EXTRACT_GAME_DATA: Scraping will proceed without authentication.")
        else:
            logger_scraper.info("EXTRACT_GAME_DATA: No credentials provided. Scraping as anonymous user.")

        logger_scraper.info(f"EXTRACT_GAME_DATA: Attempting to fetch game thread URL: {game_thread_url}")
        
        try:
            logger_scraper.info(f"EXTRACT_GAME_DATA: Navigating to {game_thread_url} with Playwright before spoiler clicks...")
            page.goto(game_thread_url, wait_until="domcontentloaded", timeout=30000)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Successfully navigated to {game_thread_url}. Current URL: {page.url}")
            page.wait_for_timeout(2000) 
        except Exception as e_nav_game_page:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Error navigating to game page {game_thread_url} before spoiler interaction: {e_nav_game_page}", exc_info=True)
            browser.close()
            return None

        logger_scraper.info("EXTRACT_GAME_DATA: Attempting to find and click spoiler buttons...")
        spoiler_buttons_selector = "button.bbCodeSpoiler-button"
        try:
            spoiler_buttons = page.query_selector_all(spoiler_buttons_selector)
            logger_scraper.info(f"EXTRACT_GAME_DATA: Found {len(spoiler_buttons)} spoiler buttons.")
            for i, button_element in enumerate(spoiler_buttons):
                try:
                    if button_element.is_visible() and button_element.is_enabled():
                        button_element.click(timeout=2000) 
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

        page.wait_for_timeout(2500) 

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
            "title": None, "version": None, "author": None, "tags": [],
            "full_description": None, "changelog": None, "download_links": [],
            "engine": None, "language": None, "status": None, "censorship": None,
        }

        if title_tag := soup.find('h1', class_='p-title-value'):
            data['title'] = title_tag.get_text(strip=True)
        elif page_title_element := soup.find('title'):
            data['title'] = page_title_element.get_text(strip=True).replace(" | F95zone", "")
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted title: {data['title']}")

        # --- ADDED: Attempt to parse Engine, Version, Author from title as a fallback ---
        if data['title']:
            # Version: Look for patterns like [v0.1.2], (v0.1.2), v0.1.2, ver 0.1.2, version 0.1.2
            version_match = re.search(r'(?:\[|\(|ver(?:sion)?\s*)\s*(v?(?:\d+\.)+\d+\w*)\s*(?:\]|\))?', data['title'], re.IGNORECASE)
            if version_match and not data['version']: # Only if not already found
                data['version'] = version_match.group(1)
                logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred version from title: {data['version']}")

            # Author: Look for pattern like [AuthorName] or (AuthorName) at the end of title
            # Avoid matching version numbers if they are also in brackets
            author_match = re.search(r'(?:\[|\()([^\[\]()]*?)(?:\]|\))\s*$', data['title'])
            if author_match:
                potential_author = author_match.group(1).strip()
                # Avoid using if it looks like a version number or is very short
                if not re.fullmatch(r'v?\d+(\.\d+)*\w*', potential_author, re.IGNORECASE) and len(potential_author) > 2:
                    if not data['author'] or data['author'] == 'Not found': # Only if not already found or is default 'Not found'
                        data['author'] = potential_author
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Inferred author from title: {data['author']}")
            
            # Engine: Look for common engine names at the start or in brackets/parentheses
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
        # --- END ADDED ---

        first_post_article = soup.find('article', class_='message--post') 
        if first_post_article:
            user_details_div = first_post_article.find('div', class_='message-userDetails')
            if user_details_div:
                author_link_tag = user_details_div.find('a', class_='username')
                if author_link_tag:
                    author_from_post = author_link_tag.get_text(strip=True)
                    # If data['author'] is already set (e.g. from title inference) and author_from_post is numeric, prefer existing.
                    # Otherwise, use author_from_post.
                    if data['author'] and author_from_post.isdigit():
                        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Author from post ('{author_from_post}') is numeric. Keeping existing inferred author: '{data['author']}'.")
                    else:
                        data['author'] = author_from_post
                else:
                    logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): Author link not found within first post's userDetails.")
            else:
                logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): userDetails div not found in the first post.")
        else:
            logger_scraper.warning(f"SCRAPER_DATA (URL: {game_thread_url}): First post article not found for author extraction.")
        
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted author (after first post check): {data['author']}")

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

            changelog_text_parts = []
            possible_changelog_headers = ['changelog', "what\'s new", "update notes", "version history"]
            spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            for spoiler in spoilers:
                button = spoiler.find('button', class_='bbCodeSpoiler-button')
                content = spoiler.find('div', class_='bbCodeSpoiler-content')
                if button and content and any(ch_kw in button.get_text(strip=True).lower() for ch_kw in possible_changelog_headers):
                    changelog_text_parts.append(content.get_text(separator='\n', strip=True))

            if not changelog_text_parts:
                for header_tag_name in ['strong', 'h2', 'h3', 'h4']:
                    headers = bb_wrapper.find_all(header_tag_name)
                    for header in headers:
                        if any(ch_kw in header.get_text(strip=True).lower() for ch_kw in possible_changelog_headers):
                            next_content = []
                            for sibling in header.find_next_siblings():
                                if sibling.name and (sibling.name.startswith('h') or (sibling.name == 'div' and 'Spoiler' in sibling.get('class', []))):
                                    break
                                next_content.append(sibling.get_text(separator='\n', strip=True))
                            if next_content:
                                changelog_text_parts.append("\n".join(next_content))
                            break 
                    if changelog_text_parts:
                        break
            data['changelog'] = "\n---\n".join(changelog_text_parts) or "Not clearly identified"
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted changelog (first 100 chars): {data['changelog'][:100] if data['changelog'] else 'None'}")


            links = bb_wrapper.find_all('a', href=True)
            for link in links:
                href = link['href']
                text = link.get_text(strip=True)
                dl_keywords = ['download', 'mega', 'mediafire', 'zippy', 'gdrive', 'google drive', 'pixeldrain', 'workupload', 'itch.io/']
                file_exts = ['.zip', '.rar', '.apk', '.7z', '.exe']
                
                is_dl_link_text = any(keyword in text.lower() for keyword in dl_keywords)
                is_dl_link_href = any(keyword in href.lower() for keyword in dl_keywords)
                is_file_ext_in_href = any(ext in href.lower() for ext in file_exts)
                is_not_mailto = not href.startswith('mailto:')
                is_not_internal_thread_link = 'f95zone.to/threads/' not in href

                if (is_dl_link_text or is_dl_link_href or is_file_ext_in_href) and \
                   is_not_mailto and (is_not_internal_thread_link or is_file_ext_in_href):
                    data['download_links'].append({"text": text, "url": href})

            buttons = bb_wrapper.find_all('button')
            for button in buttons:
                onclick_attr = button.get('onclick', '')
                if not ("window.open" in onclick_attr or "location.href" in onclick_attr):
                    continue

                try:
                    url_in_onclick = onclick_attr.split("'")[1]
                    if not url_in_onclick.startswith('http') and not url_in_onclick.startswith('/'):
                        url_in_onclick = '/' + url_in_onclick
                    
                    is_duplicate = any(dl_link['url'] == url_in_onclick or dl_link['text'] == button.get_text(strip=True) for dl_link in data['download_links'])
                    if not is_duplicate:
                         data['download_links'].append({"text": button.get_text(strip=True), "url": url_in_onclick})
                except IndexError:
                    pass 
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Found {len(data['download_links'])} download links.")

        if tags_container := soup.find('div', class_='tagGroup'):
            tag_links = tags_container.find_all('a', class_='tagItem')
            for tag_link in tag_links:
                data['tags'].append(tag_link.get_text(strip=True))
        elif tags_dt := soup.find('dt', string=lambda t: t and 'tags' in t.lower()):
            if tags_dd := tags_dt.find_next_sibling('dd'): 
                tag_links = tags_dd.find_all('a')
                for tag_link in tag_links:
                    data['tags'].append(tag_link.get_text(strip=True))
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Extracted tags: {data['tags']}")


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
                elif 'status' in dt_text and not data['status']:
                    # Check if the status from dls is more specific than one from title (if any)
                    # For now, dls source is more direct, so it can override title inference for status
                    data['status'] = dd_text
                elif 'censorship' in dt_text and not data['censorship']:
                    data['censorship'] = dd_text
                elif 'developer' in dt_text and (not data['author'] or data['author'] == 'Not found'): # Prioritize author from first post, then title, then this
                    data['author'] = dd_text
                elif 'version' in dt_text and (not data['version'] or data['version'] == 'Not found'): # Title inference can be overridden by more specific dl list
                     data['version'] = dd_text
        
        logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): After dls - Engine: {data['engine']}, Lang: {data['language']}, Status: {data['status']}, Cens: {data['censorship']}, Author: {data['author']}, Version: {data['version']}")


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
        if data['full_description']:
            desc_text_to_search = data['full_description'] # Use original casing for extraction, lower for matching
            desc_text_lower = desc_text_to_search.lower()
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): Attempting to parse details from full_description. Snippet: {desc_text_to_search[:300]}")

            # Language
            if not data['language'] or data['language'] == "Not found":
                # Regex: "language" (optional 's'), optional colon, optional spaces/newlines, then capture group.
                # Capture group: word characters, spaces, commas, 'and'.
                lang_match = re.search(r"language(?:s)?\\s*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
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
                censorship_match = re.search(r"censor(?:ed)?\\s*:\\s*([\\w\\-]+)", desc_text_lower, re.IGNORECASE)
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
            os_match = re.search(r"os\\s*:\\s*([\\w\\s,]+(?:and[\\w\\s,]+)*)", desc_text_lower, re.IGNORECASE)
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
        else:
            logger_scraper.info(f"SCRAPER_DATA (URL: {game_thread_url}): No full_description available to parse for further details.")
        # --- END ADDED ---

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