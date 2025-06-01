import requests
from bs4 import BeautifulSoup

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

def extract_game_data(game_thread_url):
    """
    Extracts detailed information from an F95zone game thread page.
    """
    print(f"Fetching data for: {game_thread_url}")
    soup = get_soup(game_thread_url)
    if not soup:
        return None

    data = {
        "url": game_thread_url,
        "title": None,
        "version": None, # Often part of title or specific labels, can be hard to reliably parse generally
        "author": None,
        "tags": [],
        "full_description": None,
        "changelog": None,
        "download_links": [],
        "engine": None,
        "language": None,
        "status": None,
        "censorship": None,
    }

    # --- Title ---
    title_tag = soup.find('h1', class_='p-title-value')
    if title_tag:
        data['title'] = title_tag.get_text(strip=True)
    else: 
        page_title_tag = soup.find('title')
        if page_title_tag:
            data['title'] = page_title_tag.get_text(strip=True).replace(" | F95zone", "")

    # --- Author (Thread Starter) ---
    author_tag = soup.find('a', class_='username') 
    if author_tag and soup.find('article', class_='message--post'): # Check it's within the first post context
        if author_tag.closest('article', class_='message--post'):
             data['author'] = author_tag.get_text(strip=True)


    # --- Main content of the first post ---
    first_post_article = soup.find('article', class_='message--post')
    bb_wrapper = None
    if first_post_article:
        bb_wrapper = first_post_article.find('div', class_='bbWrapper')

    if bb_wrapper:
        # --- Full Game Description/Overview ---
        # Attempts to get text before sections like "Download", "Changelog", "Spoiler"
        desc_elements = []
        for elem in bb_wrapper.children:
            if elem.name and (elem.name.startswith('h') or (elem.name == 'div' and 'Spoiler' in elem.get('class', []))):
                text_check = elem.get_text(strip=True).lower()
                if any(kw in text_check for kw in ['download', 'changelog', 'what\'s new', 'version history', 'updates']):
                    break 
            if isinstance(elem, str):
                 desc_elements.append(elem.strip())
            elif elem.name not in ['script', 'style']:
                 desc_elements.append(elem.get_text(separator='\\n', strip=True))
        data['full_description'] = "\\n".join(filter(None, desc_elements)).strip()
        if not data['full_description']: # Fallback if above is too restrictive
            data['full_description'] = bb_wrapper.get_text(separator='\\n', strip=True)


        # --- Changelog ---
        changelog_text_parts = []
        possible_changelog_headers = ['changelog', "what's new", "update notes", "version history"]
        
        spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
        for spoiler in spoilers:
            button = spoiler.find('button', class_='bbCodeSpoiler-button')
            if button and any(ch_kw in button.get_text(strip=True).lower() for ch_kw in possible_changelog_headers):
                content = spoiler.find('div', class_='bbCodeSpoiler-content')
                if content:
                    changelog_text_parts.append(content.get_text(separator='\\n', strip=True))
                    
        if not changelog_text_parts: # Try finding strong/h tags
            for header_tag_name in ['strong', 'h2', 'h3', 'h4']:
                headers = bb_wrapper.find_all(header_tag_name)
                for header in headers:
                    if any(ch_kw in header.get_text(strip=True).lower() for ch_kw in possible_changelog_headers):
                        # Try to get content following the header until the next header or end of bbWrapper
                        next_content = []
                        for sibling in header.find_next_siblings():
                            if sibling.name and (sibling.name.startswith('h') or (sibling.name == 'div' and 'Spoiler' in sibling.get('class', []))):
                                break
                            next_content.append(sibling.get_text(separator='\\n', strip=True))
                        if next_content:
                            changelog_text_parts.append("\\n".join(next_content))
                        break # Found one header, assume it's the main changelog
                if changelog_text_parts:
                    break
        data['changelog'] = "\\n---\\n".join(changelog_text_parts) if changelog_text_parts else "Not clearly identified"


        # --- Download Links ---
        links = bb_wrapper.find_all('a', href=True)
        for link in links:
            href = link['href']
            text = link.get_text(strip=True)
            # Keywords for download links or file hosting services
            dl_keywords = ['download', 'mega', 'mediafire', 'zippy', 'gdrive', 'google drive', 'pixeldrain', 'workupload', 'itch.io/']
            file_exts = ['.zip', '.rar', '.apk', '.7z', '.exe']
            if any(keyword in text.lower() for keyword in dl_keywords) or \
               any(keyword in href.lower() for keyword in dl_keywords) or \
               any(ext in href.lower() for ext in file_exts):
                # Avoid mailto links or internal f95zone links that aren't game files
                if not href.startswith('mailto:') and ('f95zone.to/threads/' not in href or any(ext in href.lower() for ext in file_exts) ):
                    data['download_links'].append({"text": text, "url": href})
        
        # Check buttons too, as some download links are styled as buttons
        buttons = bb_wrapper.find_all('button')
        for button in buttons:
            onclick_attr = button.get('onclick', '')
            if "window.open" in onclick_attr or "location.href" in onclick_attr:
                # Extract URL from onclick attribute (this is a bit fragile)
                try:
                    url_in_onclick = onclick_attr.split("'")[1]
                    if not url_in_onclick.startswith('http'): # if relative, try to make it absolute
                        if game_thread_url.endswith('/'):
                             base_url_for_relative = game_thread_url.rsplit('/', 2)[0] + "/"
                        else:
                             base_url_for_relative = game_thread_url.rsplit('/', 1)[0] + "/"
                        if not url_in_onclick.startswith('/'):
                            url_in_onclick = '/' + url_in_onclick
                        # Simple concatenation, might need f95zone.to base if truly relative
                        # This part is very heuristic.
                    
                    # Check if this URL is already in download_links by its text or URL
                    # This is to avoid adding if an <a> tag for the same already exists
                    is_duplicate = False
                    for dl_link in data['download_links']:
                        if dl_link['url'] == url_in_onclick or dl_link['text'] == button.get_text(strip=True) :
                            is_duplicate = True
                            break
                    if not is_duplicate:
                         data['download_links'].append({"text": button.get_text(strip=True), "url": url_in_onclick})
                except IndexError:
                    pass # Could not parse URL from onclick

    # --- Tags/Categories ---
    tags_container = soup.find('div', class_='tagGroup') # New XenForo versions
    if tags_container:
        tag_links = tags_container.find_all('a', class_='tagItem')
        for tag_link in tag_links:
            data['tags'].append(tag_link.get_text(strip=True))
    else: # Fallback for older structures if any or different class names
        tags_dt = soup.find('dt', string=lambda t: t and 'tags' in t.lower())
        if tags_dt:
            tags_dd = tags_dt.find_next_sibling('dd')
            if tags_dd:
                tag_links = tags_dd.find_all('a')
                for tag_link in tag_links:
                    data['tags'].append(tag_link.get_text(strip=True))
    
    # --- Game Engine, Language, Status, Censorship ---
    # These details are often in a definition list or prefixed to the title, or in tags.
    
    # Try thread_marks / prefixes first (common for Engine, Status)
    prefix_elements = soup.find_all('span', class_=lambda x: x and x.startswith('label')) # General class for labels
    for prefix_el in prefix_elements:
        text = prefix_el.get_text(strip=True).lower()
        # Engine
        if not data['engine']:
            if any(eng_name in text for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'tyranobuilder', 'wolf rpg', 'unreal engine', 'qsp', 'rags']):
                data['engine'] = prefix_el.get_text(strip=True)
        # Status
        if not data['status']:
            if any(st_name in text for st_name in ['completed', 'ongoing', 'on hold', 'abandoned', 'hiatus']):
                data['status'] = prefix_el.get_text(strip=True)

    # Check definition lists (dl elements) for more structured info
    dls = soup.find_all('dl', class_=['pairs--columns', 'block-body-infoPairs', 'pairs--justified'])
    for dl_element in dls:
        dt_elements = dl_element.find_all('dt')
        for dt in dt_elements:
            dt_text = dt.get_text(strip=True).lower()
            dd = dt.find_next_sibling('dd')
            if dd:
                dd_text = dd.get_text(strip=True)
                if 'engine' in dt_text and not data['engine']:
                    data['engine'] = dd_text
                elif 'language' in dt_text and not data['language']:
                    data['language'] = dd_text
                elif 'status' in dt_text and not data['status']:
                    data['status'] = dd_text
                elif 'censorship' in dt_text and not data['censorship']:
                    data['censorship'] = dd_text
                elif 'developer' in dt_text and not data['author']: # Sometimes author is listed as developer
                    data['author'] = dd_text
                elif 'version' in dt_text and not data['version']:
                     data['version'] = dd_text


    # Infer from tags if still not found
    if isinstance(data['tags'], list):
        for tag_text_lower in [t.lower() for t in data['tags']]:
            if not data['engine'] and any(eng_name in tag_text_lower for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal']):
                # Find the original tag text for proper casing
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

    # Fill "Not found" for clarity if items are still None or empty lists
    for key, value in data.items():
        if value is None:
            data[key] = "Not found"
        elif isinstance(value, list) and not value:
            data[key] = ["Not found"]
            
    return data

if __name__ == '__main__':
    example_urls = [
        "https://f95zone.to/threads/takeis-journey-v0-30-ferrum.82236/",
        "https://f95zone.to/threads/a-series-of-changes-v0-04-0-farwest-studios-llc.238037/",
        "https://f95zone.to/threads/by-justice-or-mercy-v0-07d-public-nekomancer.58106/",
        "https://f95zone.to/threads/coffee-buns-v0-1-completed-gonzo.214495/",
        "https://f95zone.to/threads/boundaries-of-morality-v0-15-0-theaeon.251609/",
        "https://f95zone.to/threads/life-together-ch-1-v0-6-narca.254041/",
        "https://f95zone.to/threads/love-and-evil-things-v0-5-public-naughtycat.172695/",
        "https://f95zone.to/threads/motherless-v0-65c-thelonetraveler.48369/",
        "https://f95zone.to/threads/intertwined-v0-5-final-nyxee.53676/", # Example with "Final" status often in title
        "https://f95zone.to/threads/the-shrink-r-r-v0-7-5-mastermany.36610/",
        "https://f95zone.to/threads/hearts-of-the-city-v0-1-public-saltymeat.256799/",
        "https://f95zone.to/threads/girls-und-panzer-der-panzussy-die-film-v0-0-1-upforkilling.256458/",
        "https://f95zone.to/threads/lewd-souls-v2-3-0-xetrift-studios.194488/"
    ]

    all_games_data = []
    print(f"Attempting to scrape {len(example_urls)} game pages.\\n")

    for i, url in enumerate(example_urls):
        print(f"--- Processing game {i+1}/{len(example_urls)} ---")
        extracted_info = extract_game_data(url)
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
                            if isinstance(item, dict): # For download links
                                print(f"  - Text: {item.get('text', 'N/A')}, URL: {item.get('url', 'N/A')}")
                            else:
                                print(f"  - {item}")
                else:
                    print(f"{display_key}: {value}")
            print("=" * 70 + "\\n")

    # Option to save to JSON
    # import json
    # with open('f95_extracted_data_batch.json', 'w', encoding='utf-8') as f:
    #    json.dump(all_games_data, f, indent=4, ensure_ascii=False)
    # print(f"\\nSuccessfully processed {len(all_games_data)} games. Data saved to f95_extracted_data_batch.json")
    print(f"\\nSuccessfully processed {len(all_games_data)} games.")
    if len(all_games_data) < len(example_urls):
        print(f"Note: {len(example_urls) - len(all_games_data)} game(s) could not be processed (check for network errors above).") 