import requests
from bs4 import BeautifulSoup
import time # Added for potential waits
from playwright.sync_api import sync_playwright # Added for Playwright

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

        login_button_selector = "button.button--primary:has-text('Log in')"
        if not page.query_selector(login_button_selector):
            login_button_selector = "form.block[action='/login/login'] button[type='submit']"
            print(f"Primary login button selector not found, trying fallback: {login_button_selector}")

        page.click(login_button_selector)
        print("Clicked login button.")
        # Wait for navigation to complete or for a login success/failure indicator
        # Increased timeout slightly and wait for a more definitive state like networkidle or specific selectors
        try:
            page.wait_for_load_state('networkidle', timeout=7000) # Wait for network to be idle
        except Exception as e_wait_idle:
            print(f"Network did not become idle after login click, proceeding with checks. Error: {e_wait_idle}")
            page.wait_for_timeout(3000) # Fallback fixed wait if networkidle times out

        # Check for successful login indicators
        if page.query_selector("a[href='/logout/']") or page.query_selector(".p-account") or page.query_selector("//a[contains(@class, 'p-navgroup-link--username')]"): # Added XPath for username link
            print("Login check: Logout link or account element or username link found. Login appears successful.")
            print(f"Current URL after login attempt: {page.url}")
            return True
        elif error_block := page.query_selector(".blockMessage.blockMessage--error"):
            error_text = error_block.inner_text()
            print(f"Login failed. Error message found: {error_text}")
            print(f"Current URL after login failure: {page.url}")
            return False
        else:
            print(f"Login failed. No specific error message or success indicator found on page. URL after attempt: {page.url}")
            # Potentially take a screenshot for debugging if login is consistently problematic
            # page.screenshot(path='login_failure_debug.png')
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
        html_content = get_page_html_with_playwright(page, game_thread_url)
        print(f"After navigating to game thread. Current Playwright page URL: {page.url}")
        
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
        print(f"SCRAPER_DEBUG: Extracted title: {data['title']}")

        # --- Author (Thread Starter) ---
        author_tag = soup.find('a', class_='username')
        first_post_article_for_author = soup.find('article', class_='message--post')
        
        # data['author'] is initialized to None in the data dictionary.
        # It will only be updated if this specific logic succeeds, 
        # or by other more general author extraction logic later in the function.

        if author_tag and first_post_article_for_author:
            author_confirmed_in_first_post = False
            # Safely check if author_tag.closest is a callable method
            if hasattr(author_tag, 'closest') and callable(author_tag.closest):
                # Call .closest() and check its return value
                closest_article = author_tag.closest('article', class_='message--post')
                # Check if the found closest article is the same as the first_post_article_for_author
                if closest_article and closest_article is first_post_article_for_author:
                    author_confirmed_in_first_post = True
                # else: # Optional: Add logging here if closest_article is found but isn't the first post, or not found at all
                #     print(f"DEBUG: For {game_thread_url}, author_tag.closest check: closest_article is {closest_article is not None}, is_first_post: {closest_article is first_post_article_for_author}")
            else:
                # This case handles if author_tag.closest is not a callable method (e.g., it's None or not present on the tag)
                print(f"Warning: For URL {game_thread_url}, 'author_tag.closest' is not a callable method or does not exist. Author tag details: Tag name='{author_tag.name if author_tag else 'N/A'}', Type of 'closest' attr='{type(getattr(author_tag, 'closest', None))}'. Author might not be correctly identified from the first post.")

            if author_confirmed_in_first_post:
                data['author'] = author_tag.get_text(strip=True)
        # else: # Optional: Add logging if author_tag or first_post_article_for_author is not found
            # print(f"DEBUG: For {game_thread_url}, author_tag found: {author_tag is not None}, first_post_article_for_author found: {first_post_article_for_author is not None}")
        print(f"SCRAPER_DEBUG: Extracted author: {data['author']}")

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
            description_snippet = (data['full_description'][:200] + '...') if data['full_description'] and len(data['full_description']) > 200 else data['full_description']
            print(f"SCRAPER_DEBUG: Description snippet: {description_snippet}")

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