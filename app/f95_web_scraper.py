import requests
from bs4 import BeautifulSoup
import time # Added for potential waits
from playwright.sync_api import sync_playwright # Added for Playwright
import re # Added for regular expressions

# --- Playwright Login Function ---
def login_to_f95zone(page, username, password):
    """
    Logs into F95zone using Playwright.
    Assumes the page is already navigated to the login page or a page that redirects to login.
    """
    try:
        print("Attempting to log in...")
        page.fill("input[name='login']", username)
        print("Filled username.")
        page.fill("input[name='password']", password)
        print("Filled password.")

        login_button = page.locator("button.button--primary", has_text="Log in")
        
        if not login_button or login_button.count() == 0: 
            print("Primary login button (.button--primary with text 'Log in') not found. Trying fallback selector for form button...")
            login_button = page.locator("form.block[action='/login/login'] button[type='submit']")
        
        if not login_button or login_button.count() == 0:
            print("Fallback form button not found. Trying get_by_role('button', name=re.compile(r'log in', re.IGNORECASE))...")
            login_button = page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))

        if login_button.count() > 0:
            button_to_click = login_button.first
            try:
                print(f"Found login button. Waiting for it to be visible and enabled...")
                button_to_click.wait_for(state="visible", timeout=5000) 
                button_to_click.wait_for(state="enabled", timeout=5000) 
                print(f"Login button is visible and enabled. Attempting click now...")
                button_to_click.click(timeout=25000) # Increased timeout to 25 seconds for the click action
                print("Playwright click() call for login button completed. Page should have navigated or updated.")
            except Exception as e_click_wait:
                print(f"LOGIN ERROR: Error while waiting for login button state or during the click action itself: {e_click_wait}")
                return False
        else:
            print("LOGIN ERROR: Could not find a clickable login button on the page after all fallbacks.")
            print(f"Current URL when failing to find login button: {page.url}")
            return False

        print("Waiting for login result (e.g., navigation, specific elements changing)...")
        try:
            page.wait_for_selector(
                "a[href='/logout/'], .blockMessage.blockMessage--error, a.p-navgroup-link--username", 
                timeout=15000
            )
            print(f"Login result indicator found. Current URL: {page.url}")
        except Exception as e_wait_indicator:
            print(f"Timeout or error waiting for login result indicator. Error: {e_wait_indicator}")
            print(f"Current URL after login click attempt and wait for indicator: {page.url}")

        if page.query_selector("a[href='/logout/']") or page.query_selector(".p-account") or page.query_selector("a.p-navgroup-link--username"):
            print("Login check: Logout link or account element or username link found. Login appears successful.")
            print(f"Current URL after login attempt: {page.url}")
            return True
        else:
            print(f"Login failed. No specific error message or success indicator found on page. URL after attempt: {page.url}")
            return False

    except Exception as e:
        print(f"An error occurred during login: {e}")
        return False

def get_page_html_with_playwright(page, url):
    """Fetches HTML from a URL using an existing Playwright page object and returns its content."""
    try:
        print(f"Navigating to {url} with Playwright...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"Successfully navigated to {url}. Current Playwright page URL: {page.url}. Waiting for page to settle.")
        page.wait_for_timeout(3000)
        html_content = page.content()
        if not html_content:
            print(f"Warning: Fetched empty HTML content from {url}")
        return html_content
    except Exception as e:
        print(f"Error fetching URL {url} with Playwright: {e}")
        return None

def get_soup(url):
    """Fetches HTML from a URL and returns a BeautifulSoup object."""
    try:
        headers = { # Mimic a browser to avoid potential blocks
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return None

def extract_game_data(game_thread_url, username=None, password=None):
    """
    Extracts detailed information from an F95zone game thread page.
    Uses Playwright for navigation and login if credentials are provided.
    """
    print(f"Starting extraction for: {game_thread_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        page = context.new_page()

        logged_in = False
        if username and password:
            try:
                print("Navigating to login page for authentication...")
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=30000)
                print(f"On login page. Current URL: {page.url}")
                if login_to_f95zone(page, username, password):
                    print("LOGIN_F95_WEB_SCRAPER: Login function returned True.")
                    logged_in = True
                else:
                    print("LOGIN_F95_WEB_SCRAPER: Login function returned False. Scraping will proceed without authentication, which may fail for some content.")
            except Exception as e_login_nav:
                print(f"Error navigating to login page or during login process: {e_login_nav}")
                print("Scraping will proceed without authentication.")
        else:
            print("No credentials provided. Scraping as anonymous user.")

        print(f"Attempting to fetch game thread URL: {game_thread_url}")
        # html_content = get_page_html_with_playwright(page, game_thread_url) # Moved after spoiler clicks
        # print(f"After navigating to game thread. Current Playwright page URL: {page.url}")

        # Navigate to the game thread page first
        try:
            print(f"Navigating to {game_thread_url} with Playwright before spoiler clicks...")
            page.goto(game_thread_url, wait_until="domcontentloaded", timeout=30000)
            print(f"Successfully navigated to {game_thread_url}. Current URL: {page.url}")
            page.wait_for_timeout(2000) # Give page a moment to settle
        except Exception as e_nav_game_page:
            print(f"Error navigating to game page {game_thread_url} before spoiler interaction: {e_nav_game_page}")
            browser.close()
            return None

        # Attempt to click all spoiler buttons to reveal content
        print("Attempting to find and click spoiler buttons...")
        spoiler_buttons_selector = "button.bbCodeSpoiler-button"
        try:
            spoiler_buttons = page.query_selector_all(spoiler_buttons_selector)
            print(f"Found {len(spoiler_buttons)} spoiler buttons.")
            for i, button_element in enumerate(spoiler_buttons):
                try:
                    if button_element.is_visible() and button_element.is_enabled():
                        # print(f"Attempting to click spoiler button {i+1}") # Optional: Keep for super-detailed debugging
                        button_element.click(timeout=2000) # Click with a short timeout for the action itself
                        # print(f"Clicked spoiler button {i+1}.") # REDUCED VERBOSITY
                        
                        spoiler_container = button_element.query_selector("xpath=ancestor::div[contains(@class, 'bbCodeSpoiler')]")
                        if spoiler_container:
                            content_area = spoiler_container.query_selector("div.bbCodeSpoiler-content")
                            if content_area:
                                page.wait_for_timeout(750) 
                                # content_text = content_area.inner_text(timeout=1000) # REDUCED VERBOSITY
                                # print(f"  Spoiler {i+1} content snippet after click & wait: {(content_text[:70] + '...') if content_text and len(content_text) > 70 else content_text}") # REDUCED VERBOSITY
                            # else: # Optional: Keep for debugging specific spoiler structure issues
                                # print(f"  Could not find content area for spoiler {i+1} after click.")
                        # else: # Optional: Keep for debugging specific spoiler structure issues
                            # print(f"  Could not find parent spoiler container for button {i+1}.")
                            page.wait_for_timeout(500) # Fallback general pause if specific content area isn't found by the above logic

                    else:
                        # print(f"Spoiler button {i+1} is not visible or enabled, skipping.") # REDUCED VERBOSITY
                        pass 
                except Exception as e_click_spoiler:
                    print(f"Could not click or process spoiler button {i+1}: {e_click_spoiler}")
            print("Finished attempting to click spoiler buttons.")
        except Exception as e_find_spoilers:
            print(f"Error finding or interacting with spoiler buttons: {e_find_spoilers}")

        # Add a more substantial overall wait here for any final JS updates after all spoiler interactions
        # print("Waiting a bit longer for all spoiler content to potentially load (increased wait)...") # REDUCED VERBOSITY
        page.wait_for_timeout(2500) # Reduced from 5000, individual waits are now more targeted

        # Now get the HTML content after attempting to click spoilers
        # print(f"Getting HTML content after spoiler clicks. Current URL: {page.url}") # REDUCED VERBOSITY
        html_content = page.content()
        
        if not html_content:
            print(f"Failed to get HTML content for {game_thread_url} using Playwright.")
            browser.close()
            return None

        soup = BeautifulSoup(html_content, 'html.parser')
        browser.close()

        data = {
            "url": game_thread_url,
            "title": None, "version": None, "author": None, "tags": [],
            "full_description": None, "changelog": None, "download_links": [],
            "engine": None, "language": None, "status": None, "censorship": None,
        }

        # --- Title ---
        if title_tag := soup.find('h1', class_='p-title-value'):
            data['title'] = title_tag.get_text(strip=True)
        elif page_title_element := soup.find('title'):
            data['title'] = page_title_element.get_text(strip=True).replace(" | F95zone", "")
        # print(f"SCRAPER_DEBUG: Extracted title: {data['title']}") # REDUCED VERBOSITY

        # --- Author (Thread Starter) ---
        # data['author'] is initialized to None in the data dictionary.
        first_post_article = soup.find('article', class_='message--post') # Find the first post
        if first_post_article:
            user_details_div = first_post_article.find('div', class_='message-userDetails')
            if user_details_div:
                author_link_tag = user_details_div.find('a', class_='username')
                if author_link_tag:
                    data['author'] = author_link_tag.get_text(strip=True)
                else:
                    print(f"Warning: For URL {game_thread_url}, author link not found within first post's userDetails.")
            else:
                print(f"Warning: For URL {game_thread_url}, userDetails div not found in the first post.")
        else:
            print(f"Warning: For URL {game_thread_url}, first post article not found for author extraction.")
        
        # Fallback or alternative author scraping logic (from dt/dd pairs) is handled later in the script.

        # print(f"SCRAPER_DEBUG: Extracted author (after first post check): {data['author']}") # REDUCED VERBOSITY

        # --- Main content of the first post ---
        first_post_article_content = soup.find('article', class_='message--post')
        bb_wrapper = first_post_article_content.find('div', class_='bbWrapper') if first_post_article_content else None

        if bb_wrapper:
            # --- Full Game Description/Overview ---
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

            # Limit description length for logging to avoid flooding logs
            # description_snippet = (data['full_description'][:200] + '...') if data['full_description'] and len(data['full_description']) > 200 else data['full_description'] # REDUCED VERBOSITY
            # print(f"SCRAPER_DEBUG: Description snippet: {description_snippet}") # REDUCED VERBOSITY

            # --- Changelog ---
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

            # --- Download Links ---
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

        # --- Tags/Categories ---
        if tags_container := soup.find('div', class_='tagGroup'):
            tag_links = tags_container.find_all('a', class_='tagItem')
            for tag_link in tag_links:
                data['tags'].append(tag_link.get_text(strip=True))
        elif tags_dt := soup.find('dt', string=lambda t: t and 'tags' in t.lower()):
            if tags_dd := tags_dt.find_next_sibling('dd'): 
                tag_links = tags_dd.find_all('a')
                for tag_link in tag_links:
                    data['tags'].append(tag_link.get_text(strip=True))

        # --- Game Engine, Language, Status, Censorship ---
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
                    data['status'] = dd_text
                elif 'censorship' in dt_text and not data['censorship']:
                    data['censorship'] = dd_text
                elif 'developer' in dt_text and not data['author']:
                    data['author'] = dd_text
                elif 'version' in dt_text and not data['version']:
                     data['version'] = dd_text

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

        for key, value in data.items():
            if value is None:
                data[key] = "Not found"
            elif isinstance(value, list) and not value:
                data[key] = ["Not found"] if key in ["tags", "download_links"] else "Not found"

    print(f"SCRAPER_DEBUG: Final data dictionary before return: {data}")
    return data

if __name__ == '__main__':
    import os
    f95_username = os.environ.get("F95ZONE_USERNAME")
    f95_password = os.environ.get("F95ZONE_PASSWORD")

    if not (f95_username and f95_password):
        print("WARNING: F95ZONE_USERNAME and/or F95ZONE_PASSWORD environment variables not set.")
        print("Login functionality will not be tested. Scraping will be anonymous.")

    example_urls = [
        "https://f95zone.to/threads/takeis-journey-v0-30-ferrum.82236/",
    ]

    all_games_data = []
    print(f"Attempting to scrape {len(example_urls)} game pages.\n")

    for i, url in enumerate(example_urls):
        print(f"--- Processing game {i+1}/{len(example_urls)} ---")
        extracted_info = extract_game_data(url, username=f95_username, password=f95_password)
        if extracted_info:
            all_games_data.append(extracted_info)
            for key, value in extracted_info.items():
                display_key = key.replace('_', ' ').title()
                if isinstance(value, list):
                    print(f"{display_key}:")
                    if not value or value == ["Not found"]:
                        print("  - Not found")
                    else:
                        for item in value:
                            if isinstance(item, dict):
                                print(f"  - Text: {item.get('text', 'N/A')}, URL: {item.get('url', 'N/A')}")
                            else:
                                print(f"  - {item}")
                else:
                    print(f"{display_key}: {value}")
            print("=" * 70 + "\n")
    
    print(f"\nSuccessfully processed {len(all_games_data)} games.")
    if len(all_games_data) < len(example_urls):
        print(f"Note: {len(example_urls) - len(all_games_data)} game(s) could not be processed (check for network errors above).") 