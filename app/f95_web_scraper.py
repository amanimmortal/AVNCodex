import requests
from bs4 import BeautifulSoup
import time
from playwright.sync_api import sync_playwright
import re
import logging
from datetime import datetime

# Create a logger specific to this module
# Use the central logger
from app.logging_config import logger as logger_scraper

# --- Parsing Function (Shared by Requests and Playwright) ---
def parse_game_page_content(html_content, game_thread_url):
    """
    Parses the HTML content of a game thread page and extracts detailed information.
    Returns a dictionary of game data.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    
    # DEBUG: Log title to diagnose page load issues
    page_title = soup.title.string if soup.title else "No Title"
    logger_scraper.info(f"DEBUG: Parsed HTML Title: {page_title}")
    logger_scraper.info(f"DEBUG: HTML Start: {html_content[:200]}")

    # --- Initialize Data Dictionary ---
    data = {
        "url": game_thread_url,
        "title_full_raw": None, 
        "name": "Not found", 
        "version_from_title": "Not found",
        "author_from_title": "Not found",
        "version_from_post": "Not found",
        "author_from_post_label": "Not found", 
        "author_from_dl_list": "Not found",
        "author_from_thread_starter": "Not found",
        "version_from_dl_list": "Not found",
        "final_game_name": "Not found",
        "final_version": "Not found",
        "final_author": "Not found",
        "tags": [],
        "full_description": "Not found",
        "download_links": [], 
        "engine": "Not found",
        "language": "Not found",
        "status": "Not found",
        "censorship": "Not found",
        "release_date": "Not found",
        "thread_updated_date": "Not found",
        "os_general_list": "Not found", 
        "other_header_info": {},
        "download_links_raw_html": None,
        "image_url": None
    }
    
    # Debug dump for U4IA
    if "158858" in game_thread_url or "u4ia" in game_thread_url.lower():
        try:
            mode = 'wb'
            content_to_write = html_content
            if isinstance(html_content, str):
                mode = 'w'
                # Ensure utf-8 encoding if writing as text
                with open('u4ia_dump.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)
            else:
                with open('u4ia_dump.html', 'wb') as f:
                    f.write(html_content)
                    
            logger_scraper.info("DEBUG: Dumped u4ia_dump.html")
        except Exception as e:
            logger_scraper.error(f"DEBUG: Failed to dump html: {e}")
    raw_title_h1 = soup.find('h1', class_='p-title-value')
    if raw_title_h1:
        data['title_full_raw'] = raw_title_h1.get_text(strip=True)
    elif page_title_element := soup.find('title'):
        data['title_full_raw'] = page_title_element.get_text(strip=True).replace(" | F95zone", "")
    
    # 1. Robust Title String Parsing
    if data['title_full_raw']:
        title_str = data['title_full_raw']
        name_part = title_str
        version_part = "Not found"
        author_part = "Not found"

        author_match = re.search(r"(?i)(?:\[|\()([^\[\]()]+?)(?:\]|\))\s*$", title_str)
        if author_match:
            potential_author = author_match.group(1).strip()
            is_likely_version = re.fullmatch(r"(?i)(v|ver|ep|episode|ch|chapter|season|book|part|pt|alpha|beta|rc|final|public|demo|preview|build|update|upd|\d*([.]\d+)+[a-z]?)\w*", potential_author, re.IGNORECASE)
            
            if not is_likely_version or len(potential_author) > 15 or any(c.isalpha() for c in potential_author):
               if len(potential_author) > 1 and (any(c.isalpha() for c in potential_author) or len(potential_author) > 6 or '.' in potential_author):
                     author_part = potential_author
                     name_part = title_str[:author_match.start()].strip()

        version_search_string = name_part if author_part != "Not found" else title_str
        version_match = re.search(r"(?i)(?:\[|\()([^\[\]()]+?)(?:\]|\))\s*$", version_search_string)
        if version_match:
            potential_version = version_match.group(1).strip()
            if re.search(r"(\d|v|ep|ch|upd|final|public|beta|alpha)", potential_version, re.IGNORECASE):
                version_part = potential_version
                if name_part == version_search_string :
                     name_part = version_search_string[:version_match.start()].strip()
                elif author_part != "Not found" and name_part != title_str :
                     name_part = name_part[:version_match.start()].strip()

        name_part = re.sub(r"[\s:-]+$", "", name_part).strip()
        if not name_part and data['title_full_raw']: 
            name_part = data['title_full_raw']
            if author_part == "Not found" and version_part != "Not found" and name_part.endswith(f"[{version_part}]"): name_part = name_part[:-len(f"[{version_part}]")].strip()
            if version_part == "Not found" and author_part != "Not found" and name_part.endswith(f"[{author_part}]"): name_part = name_part[:-len(f"[{author_part}]")].strip()

        data['name'] = name_part if name_part else data['title_full_raw']
        data['version_from_title'] = version_part
        data['author_from_title'] = author_part

    # --- II. Main Post Content Extraction ---
    first_post_article_content = soup.find('article', class_='message--post')
    bb_wrapper = first_post_article_content.find('div', class_='bbWrapper') if first_post_article_content else None

    if bb_wrapper:
        # Developer/Author
        strong_tags = bb_wrapper.find_all(['strong', 'b'])
        for tag in strong_tags:
            if tag.get_text(strip=True).lower().startswith("developer:"):
                dev_name_candidate = tag.next_sibling
                if dev_name_candidate and isinstance(dev_name_candidate, str) and dev_name_candidate.strip():
                    data['author_from_post_label'] = dev_name_candidate.strip()
                    break
                elif dev_name_candidate and dev_name_candidate.name == 'a' and dev_name_candidate.get_text(strip=True):
                    data['author_from_post_label'] = dev_name_candidate.get_text(strip=True)
                    break
                elif dev_name_candidate and dev_name_candidate.find(string=True, recursive=False) and dev_name_candidate.find(string=True, recursive=False).strip():
                     data['author_from_post_label'] = dev_name_candidate.find(string=True, recursive=False).strip()
                     break

        # Thread starter
        if first_post_article_content:
            user_details_div = first_post_article_content.find('div', class_='message-userDetails')
            if user_details_div:
                author_link_tag = user_details_div.find('a', class_='username')
                if author_link_tag:
                    data['author_from_thread_starter'] = author_link_tag.get_text(strip=True)

        # Version
        for tag in strong_tags:
            tag_text_lower = tag.get_text(strip=True).lower()
            if any(kw in tag_text_lower for kw in ["version:", "current version:", "latest release:"]) and len(tag_text_lower) < 30:
                version_candidate_text = ""
                next_elem = tag.next_sibling
                while next_elem and (isinstance(next_elem, str) and not next_elem.strip()):
                    next_elem = next_elem.next_sibling
                
                if next_elem:
                    if isinstance(next_elem, str) and next_elem.strip():
                        version_candidate_text = next_elem.strip().splitlines()[0].strip()
                    elif next_elem.name == 'a' and next_elem.get_text(strip=True):
                        version_candidate_text = next_elem.get_text(strip=True)
                    elif next_elem.name and next_elem.find(string=True, recursive=False) and next_elem.find(string=True, recursive=False).strip():
                         version_candidate_text = next_elem.find(string=True, recursive=False).strip()

                if version_candidate_text:
                     data['version_from_post'] = version_candidate_text
                     break 

 

        # Image URL (Cover Image)
        # Usually the first image in the post
        img_tag = bb_wrapper.find('img', class_='bbImage')
        if img_tag and img_tag.get('src'):
             data['image_url'] = img_tag.get('src')
        elif img_tag and img_tag.get('data-url'):
             data['image_url'] = img_tag.get('data-url')
        else:
             # Fallback for lazy loaded or other images
             potential_imgs = bb_wrapper.find_all('img')
             for img in potential_imgs:
                 src = img.get('src') or img.get('data-src') or img.get('data-url')
                 # Filter out smilies/attachments if possible, though bbImage class usually handles it
                 if src and 'attachments' not in src and 'smilies' not in src:
                     data['image_url'] = src
                     break

        # Overview/Full Description
        desc_elements = []
        stop_keywords = ['download', 'changelog', "what's new", "what is new", "version history", "updates", "installation", "preview", "screenshots", "spoiler:", "support the dev", "developer", "author", "version", "engine", "language", "status", "censorship", "release date", "thread updated", "os", "platform", "system", "genre", "tags"]
        for elem in bb_wrapper.children:
            elem_text_lower = ""
            if elem.name and (elem.name.startswith('h') or elem.name == 'dl' or (elem.name == 'div' and any(cls in elem.get('class', []) for cls in ['bbCodeSpoiler', 'bbCodeBlock--download', 'bbCodeBlock--changelog'])) or (elem.name == 'button' and 'bbCodeSpoiler-button' in elem.get('class',[])) or (elem.name in ['strong','b'])):
                elem_text_lower = elem.get_text(strip=True).lower()
            
            if (elem_text_lower and any(kw in elem_text_lower for kw in stop_keywords) and len(elem_text_lower) < 70) or elem.name == 'dl':
                # Check for "Overview" header exception - if it's just "Overview" we might want to skip the header but continue content
                if "overview" in elem_text_lower or "description" in elem_text_lower or "plot" in elem_text_lower or "story" in elem_text_lower:
                     continue # Skip the header itself, but don't break the loop
                
                is_likely_section_header = True
                if is_likely_section_header:
                    break
            
            if isinstance(elem, str):
                cleaned_text = elem.strip()
                if cleaned_text: 
                     # Remove literal "\n" characters if they appear in text (common in some raw dumps) and standard newlines
                     cleaned_text = cleaned_text.replace("\\n", " ").replace("\n", " ")
                     desc_elements.append(cleaned_text)
            elif elem.name not in ['script', 'style', 'iframe', 'form', 'input', 'textarea', 'select', 'button']:
                if elem.name == 'div' and 'bbCodeSpoiler' in elem.get('class', []):
                    button_text_spoiler = elem.find('button', class_='bbCodeSpoiler-button')
                    if button_text_spoiler and not any(kw in button_text_spoiler.get_text(strip=True).lower() for kw in stop_keywords):
                         spoiler_text = button_text_spoiler.get_text(strip=True).replace("\\n", " ").replace("\n", " ")
                         desc_elements.append(spoiler_text)
                elif elem.name == 'br':
                    desc_elements.append("\n") # Mark paragraph breaks explicitly
                else:
                    text = elem.get_text(separator=' ', strip=True) # Use space separator for inline tags
                    if "You don't have permission to view the spoiler content" not in text and "Log in or register now" not in text:
                        text = text.replace("\\n", " ").replace("\n", " ")
                        desc_elements.append(text)
        
        # smart join: join with spaces, but respect explicit newlines we added for <br>
        full_desc_str = ""
        for item in desc_elements:
            if item == "\n":
                full_desc_str += "\n\n"
            else:
                # Collapse multiple spaces
                clean_item = re.sub(r'\s+', ' ', item).strip()
                if clean_item:
                    full_desc_str += clean_item + " "
        
        data['full_description'] = re.sub(r'\n{3,}', '\n\n', full_desc_str).strip()

        if not data['full_description']:
             data['full_description'] = bb_wrapper.get_text(separator='\n', strip=True)

        # Release Date
        release_date_patterns = [r"(?:Release Date|Released|Initial Release|First Release)\s*[:\-]?\s*([^\n]+)", r"<strong>(?:Release Date|Released|Initial Release|First Release)\s*[:\-]?\s*</strong>\s*([^\n]+)"]
        bb_wrapper_text_for_dates = bb_wrapper.get_text(separator="\\n")
        for pattern in release_date_patterns:
            match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
            if match and match.group(1).strip():
                potential_date_str = match.group(1).strip()
                cleaned_val = re.sub(r"^\\s*[:\\-\\s]\\s*", "", potential_date_str).strip()
                if cleaned_val and len(cleaned_val) < 50 and any(c.isdigit() for c in cleaned_val):
                    data['release_date'] = cleaned_val.split('\\n')[0].strip()
                    break

        # Thread Updated Date
        if first_post_article_content:
            time_tag = first_post_article_content.find('time', class_='u-dt')
            if time_tag and time_tag.has_attr('datetime'):
                data['thread_updated_date'] = time_tag['datetime']
            elif time_tag:
                data['thread_updated_date'] = time_tag.get_text(strip=True)

        # OS Listing
        os_patterns = [r"(?:Platform|OS|Systems|Support[s]?)\s*[:\-]?\s*([^\n]+)", r"<strong>(?:Platform|OS|Systems|Support[s]?)\s*[:\-]?\s*</strong>\s*([^\n]+)"]
        for pattern in os_patterns:
            match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
            if match and match.group(1).strip():
                os_list_str_raw = match.group(1).strip()
                cleaned_os_list_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", os_list_str_raw).strip().split('\\n')[0].strip()
                if cleaned_os_list_str and len(cleaned_os_list_str) < 100:
                    data['os_general_list'] = cleaned_os_list_str
                    break

        # Language
        language_patterns = [r"(?:Language[s]?)\s*[:\-]?\s*([^\n]+)", r"<strong>(?:Language[s]?)\s*[:\-]?\s*</strong>\s*([^\n]+)"]
        if data['language'] == "Not found":
            for pattern in language_patterns:
                match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                if match and match.group(1).strip():
                    lang_str_raw = match.group(1).strip()
                    cleaned_lang_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", lang_str_raw).strip().split('\\n')[0].strip()
                    if cleaned_lang_str and len(cleaned_lang_str) < 150:
                        data['language'] = cleaned_lang_str
        if data['status'] == "Not found" and data['title_full_raw']:
             # Fallback: Check Title for Status Prefixes (e.g. "Abandoned Game Name")
             lower_title = data['title_full_raw'].lower()
             if "abandoned" in lower_title: data['status'] = "Abandoned"
             elif "on hold" in lower_title: data['status'] = "On Hold"
             elif "completed" in lower_title: data['status'] = "Completed"
             elif "ongoing" in lower_title: data['status'] = "Ongoing"
        
        # Status
        # Priority 1: Check .js-threadStatusField (Dynamic/Structured)
        if data['status'] == "Not found":
            status_div = soup.select_one(".js-threadStatusField")
            if status_div:
                raw_val = status_div.get_text(strip=True)
                logger_scraper.warning(f"DEBUG: Found .js-threadStatusField. Raw content: '{raw_val}'")
                val = status_div.get_text(strip=True)
                # Cleanup "Status: Abandoned" -> "Abandoned"
                val = re.sub(r"^(?:Status)?\s*[:\-]?\s*", "", val, flags=re.IGNORECASE).strip()
                if val and len(val) < 50:
                     data['status'] = val
                     logger_scraper.warning(f"DEBUG: Extracted status '{val}' from js-threadStatusField")
            else:
                logger_scraper.warning("DEBUG: .js-threadStatusField NOT found in parsed HTML.")

        status_patterns = [r"(?:Status)\s*[:\-]?\s*([^\n]+)", r"<strong>(?:Status)\s*[:\-]?\s*</strong>\s*([^\n]+)"]
        if data['status'] == "Not found":
            for pattern in status_patterns:
                match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                if match and match.group(1).strip():
                    status_str_raw = match.group(1).strip()
                    cleaned_status_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", status_str_raw).strip().split('\\n')[0].strip()
                    if cleaned_status_str and len(cleaned_status_str) < 100:
                        data['status'] = cleaned_status_str
                        break
        
        if data['status'] == "Not found":
             for b_tag in bb_wrapper.find_all(['b', 'strong']):
                 if "status" in b_tag.get_text(strip=True).lower():
                     next_sib = b_tag.next_sibling
                     if next_sib:
                         val = next_sib.get_text(strip=True) if not isinstance(next_sib, str) else next_sib
                         val = val.strip().lstrip(':-').strip()
                         if val:
                             data['status'] = val
                             break

        # Censorship
        censorship_patterns = [r"(?:Censorship|Censored)\s*[:\-]?\s*([^\n]+)", r"<strong>(?:Censorship|Censored)\s*[:\-]?\s*</strong>\s*([^\n]+)"]
        if data['censorship'] == "Not found":
            for pattern in censorship_patterns:
                match = re.search(pattern, bb_wrapper_text_for_dates, re.IGNORECASE)
                if match and match.group(1).strip():
                    cen_str_raw = match.group(1).strip()
                    cleaned_cen_str = re.sub(r"^\\s*[:\\-\\s]\\s*", "", cen_str_raw).strip().split('\\n')[0].strip()
                    if cleaned_cen_str and len(cleaned_cen_str) < 50:
                        data['censorship'] = cleaned_cen_str
                        break
        
        # Download Links
        raw_download_links = []
        support_link_domains = ['patreon.com', 'subscribestar.adult', 'discord.gg', 'discord.com', 'itch.io', 'buymeacoffee.com', 'ko-fi.com', 'store.steampowered.com', 'paypal.com', 'subscribestar.com', 'gumroad.com', 'fanbox.cc', 'fantia.jp', 'boosty.to', 'youtube.com', 'twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'reddit.com']
        download_section_headers_texts = ['download', 'links', 'files']
        download_elements = bb_wrapper.descendants
        
        # Add 'win' to keywords list explicitly
        os_section_keywords = ['windows', 'pc', 'linux', 'mac', 'macos', 'osx', 'android', 'win']
        current_section_os = None
        
        for elem in download_elements:
             # Skip empty text or irrelevant tags
             if isinstance(elem, str):
                 text_content = str(elem).strip()
                 if not text_content: continue
                 # Text node analysis
                 current_element_text_lower = text_content.lower()
                 is_header_like = True # Treat significant text nodes as potential headers
             elif elem.name in ['h1','h2','h3','h4','strong','b','p','span','div','u','li']:
                 current_element_text_lower = elem.get_text(separator=' ', strip=True).lower()
                 if current_element_text_lower.startswith(('-', '|', '•')):
                      is_header_like = False
                 else:
                      is_header_like = True
             elif elem.name == 'a':
                 # Link processing happens below
                 current_element_text_lower = "" 
                 is_header_like = False
             else:
                 continue
            
             if is_header_like and len(current_element_text_lower) >= 2:
                 # Check for OS keywords
                 text_to_check = current_element_text_lower[:100] 
                 
                 found_os = False
                 # Only trigger OS detection if the element itself is likely a header (short)
                 if len(current_element_text_lower) < 100:
                     if any(os_kw in text_to_check for os_kw in os_section_keywords):
                         if any(kw in text_to_check for kw in ['windows', 'pc', 'win ', 'win/']): current_section_os = 'win'
                         elif 'linux' in text_to_check: current_section_os = 'linux'
                         elif any(kw in text_to_check for kw in ['mac', 'osx', 'macos']): current_section_os = 'mac'
                         elif 'android' in text_to_check: current_section_os = 'android'
                         
                         # Check if we are inside a restricted spoiler (Split/Update/Patch)
                         try:
                             parent = elem.parent if isinstance(elem, str) else elem
                             ancestor_spoilers = parent.find_parents('div', class_='bbCodeSpoiler')
                             for spoiler_div in ancestor_spoilers:
                                 btn = spoiler_div.find('button', class_='bbCodeSpoiler-button')
                                 if btn:
                                     btn_text = btn.get_text(strip=True).lower()
                                     if any(bad in btn_text for bad in ['split', 'update', 'part', 'extra', 'patch']):
                                         current_section_os = 'extras'
                                         break
                         except: pass
                         
                         found_os = True
                
                 # If valid OS found, we update. 
                 # If not, check if it's a generic "Download" header which should reset the OS
                 if not found_os:
                     if any(hdr_kw in text_to_check for hdr_kw in download_section_headers_texts) and len(text_to_check) < 50:
                         current_section_os = None
                     elif any(kw in text_to_check for kw in ['translation', 'patch', 'mod', 'extra', 'update', 'split', 'part ']):
                         current_section_os = 'extras'

             if elem.name == 'a' and elem.get('href'):
                 href = elem.get('href')
                 text = elem.get_text(strip=True)
                 
                 if not href or href.startswith(('#', 'mailto:', 'javascript:')) or "f95zone.to/account/" in href or "f95zone.to/members/" in href : 
                     continue
                 if "attachments.f95zone.to" in href.lower(): 
                     continue

                 try:
                     link_domain = re.match(r"https://?([^/]+)", href).group(1).replace("www.", "")
                     if any(support_domain in link_domain for support_domain in support_link_domains): 
                         continue
                 except: pass

                 if "f95zone.to/threads/" in href and not any(ext in href.lower() for ext in ['.zip', '.rar', '.apk', '.7z', '.exe', '.patch', '.mod']):
                     if not any(kw in text.lower() for kw in ['mod', 'patch', 'translation', 'download', 'fix', 'guide', 'update', 'part', 'unlocker']): 
                         continue

                 link_os = 'unknown'
                 
                 # Force 'extras' for specific keywords in link text or url (overrides section OS)
                 is_extra_content = False
                 lower_text = text.lower()
                 lower_href = href.lower()
                 
                 if any(kw in lower_text for kw in ['update', 'patch', 'fix', 'mod', 'translation', 'guide', 'walkthrough', 'part ', 'unlocker', 'cheat']) or \
                    any(kw in lower_href for kw in ['.part1', '.part2', '.part3', '.part4', '.part5']):
                     link_os = 'extras'
                     is_extra_content = True

                 if not is_extra_content:
                     if current_section_os: 
                         link_os = current_section_os
                     else:
                         if any(kw in lower_text for kw in ['win ', ' pc ', '.exe', '[win]', '(win)', 'windows', '(pc)', '[pc]']) or any(kw in lower_href for kw in ['_pc.', '.exe']): link_os = 'win'
                         elif any(kw in lower_text for kw in ['linux', '.deb', '.sh', '[linux]', '(linux)', '_linux.']) or any(kw in lower_href for kw in ['_linux.', '.sh']): link_os = 'linux'
                         elif any(kw in lower_text for kw in ['mac', 'osx', '.dmg', '[mac]', '(mac)', '_mac.']) or any(kw in lower_href for kw in ['_mac.', '.dmg']): link_os = 'mac'
                         elif any(kw in lower_text for kw in ['android', '.apk', '[android]', '(android)', '_apk.']) or any(kw in lower_href for kw in ['_apk.', '.apk']): link_os = 'android'
                         elif any(kw in lower_text for kw in ['extra', 'dlc', 'optional', 'bonus', 'soundtrack']): link_os = 'extras'
                 
                 raw_download_links.append({'text': text, 'url': href, 'os_determined': link_os})

        unique_links_map = {}
        for link_info in raw_download_links:
            key = (link_info['url'], link_info['text'])
            if key not in unique_links_map: unique_links_map[key] = link_info
        
        final_raw_links_with_os = list(unique_links_map.values())
        has_win_links = any(link['os_determined'] == 'win' for link in final_raw_links_with_os)
        has_linux_links = any(link['os_determined'] == 'linux' for link in final_raw_links_with_os)

        if has_win_links or has_linux_links:
            for link in final_raw_links_with_os:
                if link['os_determined'] in ['win', 'linux', 'mac', 'android', 'extras']:
                    data['download_links'].append({'text': link['text'], 'url': link['url'], 'os_type': link['os_determined']})
        else:
            for link in final_raw_links_with_os:
                data['download_links'].append({'text': link['text'], 'url': link['url'], 'os_type': link['os_determined']})

    # --- Raw Download Block Extraction (Hybrid HTML) ---
    if bb_wrapper:  
        try:
            # Pre-process: Globally Unwrap Spoilers in the wrapper
            # This ensures we catch them at any depth before we start linear scanning
            all_spoilers = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
            for sp in all_spoilers:
                content_div = sp.find('div', class_='bbCodeBlock-content')
                if content_div:
                    # Unwrap: Replace spoiler with the content div's children or the div itself
                    # Replacing with the div itself preserves the block structure which is usually good
                    sp.replace_with(content_div)
                else:
                    sp.decompose() # Remove empty/broken spoilers

            download_header_node = None
            keywords_for_header = ["download"]
            
            # 1. Find the "DOWNLOAD" header
            # It's usually a strong/b tag or h3/h4, sometimes just a text node that stands out.
            # We look for a node whose text is "DOWNLOAD" (case insensitive)
            for elem in bb_wrapper.descendants:
                 if isinstance(elem, str):
                     clean_text = elem.strip().lower()
                     if "download" in clean_text and len(clean_text) < 25:
                         # Ensure it's not just a sentence containing download
                         # Check if it has potential noise like "download :"
                         # Refinement: Only promote to parent if parent is plausibly just a header (short text)
                         if elem.parent and len(elem.parent.get_text(strip=True)) < 100:
                             download_header_node = elem.parent 
                         else:
                             download_header_node = elem # Just the text node
                         break
                 elif elem.name in ['strong', 'b', 'h1', 'h2', 'h3', 'div', 'span']:
                     clean_text = elem.get_text(strip=True).lower()
                     if "download" in clean_text and len(clean_text) < 25:
                         download_header_node = elem
                         break
            
            if download_header_node:
                # 2. Capture siblings until end condition
                # End condition: Thumbnails (class="lbContainer") or Attachment list
                # Or end of bbWrapper
                
                captured_html = ""
                # Start capturing FROM the header node itself to ensure we don't miss text inside it (e.g. "Download - Windows")
                current_node = download_header_node
                has_stepped_out = False
                
                while current_node:
                    should_stop = False
                    
                    if "42173" in game_thread_url:
                         logger_scraper.info(f"HHG_TRACE: Node: {current_node.name} Type: {type(current_node)}")
                         
                    # Check Stop Conditions
                    if hasattr(current_node, 'name') and current_node.name == 'div':
                         classes = current_node.get('class', [])
                         if 'lbContainer' in classes or 'js-lbContainer' in classes:
                             should_stop = True
                         # Attachments usually in a div with specific classes or structure
                         # if 'attachment' in str(classes):
                         #     should_stop = True

                    # Sometimes thumbnails are just images with specific src pattern if not lazy loaded differently
                    # But the user mentioned "set of thumbnails (from what I can see these always start with https://attachments.f95zone.to/)"
                    # Which might be links or imgs
                    # Relaxed: Do NOT stop on single attachment images (likely banners/buttons).
                    # Only stop on specific thumbnail containers (handled above with lbContainer)
                    if not should_stop and hasattr(current_node, 'find_all'):
                        imgs = current_node.find_all('img')
                        for img in imgs:
                            src = img.get('src', '') or img.get('data-url', '')
                            if "attachments.f95zone.to" in src:
                                 should_stop = True
                                 logger_scraper.info("DEBUG: Stopping on F95 attachment thumbnail.")
                                 break
                    
                    if should_stop:
                        break
                    
                    # 3. Process/Append Node
                    # (Spoilers are already unwrapped globally)

                    if hasattr(current_node, 'descendants'):
                         # It's a Tag
                         
                         # Recursive Text Cleanup (Clean text inside this container)
                         if hasattr(current_node, 'find_all'):
                             for text_node in current_node.find_all(string=True):
                                 # Skip text inside links or specific tags we want to preserve exactly
                                 if text_node.parent and text_node.parent.name in ['a', 'script', 'style', 'code', 'pre']:
                                     continue
                                 
                                 txt_val = str(text_node)
                                 # Clean noise
                                 cleaned_val = re.sub(r'[:*|]', '', txt_val)
                                 cleaned_val = re.sub(r'\s+-\s+', ' ', cleaned_val) # Remove separator hyphens
                                 cleaned_val = re.sub(r'\s+', ' ', cleaned_val) # Collapse spaces

                                 if txt_val != cleaned_val:
                                     text_node.replace_with(cleaned_val)

                         # We need to process links to add class='download-link-btn'
                         
                         # Parse the subtree as a new soup to modify safely? 
                         # Or just modify direct attributes if simple.
                         if current_node.name == 'a':
                              # processing single link
                              href = current_node.get('href', '')
                              if href and not href.startswith('#') and 'attachments.f95zone.to' not in href:
                                  if current_node.has_attr('style'): del current_node['style']
                                  existing_class = current_node.get('class', [])
                                  if 'download-link-btn' not in existing_class:
                                      existing_class.append('download-link-btn')
                                      current_node['class'] = existing_class
                         
                         elif hasattr(current_node, 'find_all'):
                              all_links = current_node.find_all('a')
                              for lnk in all_links:
                                   href = lnk.get('href', '')
                                   if href and not href.startswith('#') and 'attachments.f95zone.to' not in href:
                                       if lnk.has_attr('style'): del lnk['style']
                                       existing_class = lnk.get('class', [])
                                       if 'download-link-btn' not in existing_class:
                                           existing_class.append('download-link-btn')
                                           lnk['class'] = existing_class
                         
                         # Cleanup Headers
                         if current_node.name in ['b', 'strong']:
                             # Flatten and clean header text of trailing noise
                             txt = current_node.get_text()
                             cleaned_header = re.sub(r'[:*|]+$', '', txt).strip()
                             if cleaned_header:
                                 current_node.string = cleaned_header

                         captured_html += str(current_node)
                    else:
                         # NavigableString - Cleanup text
                         text = str(current_node)
                         # Remove noise characters: : * |
                         cleaned = re.sub(r'[:*|]', '', text)
                         # Remove hyphens that look like separators (surrounded by spaces)
                         cleaned = re.sub(r'\s+-\s+', ' ', cleaned)
                         # Collapse multiple spaces
                         cleaned = re.sub(r'\s+', ' ', cleaned)
                         
                         # Only add if there's meaningful content
                         if cleaned.strip():
                             captured_html += cleaned


                    # Step-Out Logic
                    next_node = current_node.next_sibling
                    
                    if next_node is None and not has_stepped_out:
                        # Dynamic check: Are we inside a wrapper we should escape?
                        parent = current_node.parent
                        # Don't escape if parent is the main bbWrapper or something invalid
                        if parent and hasattr(parent, 'get') and 'bbWrapper' not in parent.get('class', []):
                            logger_scraper.info(f"DEBUG: Scraper reached end of container {parent.name}. Stepping out to parent sibling.")
                            next_node = parent.next_sibling
                            has_stepped_out = True
                    
                    current_node = next_node
                
                # Cleanup
                if captured_html:
                     # Remove unsafe tags just in case
                     soup_clean = BeautifulSoup(captured_html, 'html.parser')
                     for unsafe in soup_clean.find_all(['script', 'iframe', 'object', 'embed', 'form', 'style']):
                         unsafe.decompose()
                     
                     data['download_links_raw_html'] = str(soup_clean)
                     logger_scraper.info("DEBUG: Successfully extracted raw download HTML block.")
            else:
                 logger_scraper.info("DEBUG: 'DOWNLOAD' header not found for raw block extraction.")

        except Exception as e:
            logger_scraper.error(f"Error extracting raw download html: {e}")

    # --- Tags ---
    data['tags'] = []
    
    # Priority 1: System Tags (Header/Title area) - usually js-tagList or tagGroup
    system_tags_found = False
    
    # Check for XenForo 2.x standard tag list
    if tags_span_container := soup.find('span', class_='js-tagList'):
        tag_links = tags_span_container.find_all('a', class_='tagItem')
        for tag_link in tag_links:
            tag_text = tag_link.get_text(strip=True)
            if tag_text not in data['tags']: 
                data['tags'].append(tag_text)
                system_tags_found = True

    if not system_tags_found:
        if tags_container := soup.find('div', class_='tagGroup'):
            tag_links = tags_container.find_all('a', class_='tagItem')
            for tag_link in tag_links:
                tag_text = tag_link.get_text(strip=True)
                if tag_text not in data['tags']:
                    data['tags'].append(tag_text)
                    system_tags_found = True

    # Priority 2: Spoiler "Genre/Tags" in post (Fallback)
    if not system_tags_found and bb_wrapper: 
        spoilers_for_tags = bb_wrapper.find_all('div', class_='bbCodeSpoiler')
        for spoiler in spoilers_for_tags:
            button = spoiler.find('button', class_='bbCodeSpoiler-button')
            content_div = spoiler.find('div', class_='bbCodeSpoiler-content')
            
            should_parse_tags = False
            if button:
                btn_text_lower = button.get_text(strip=True).lower()
                if "genre" in btn_text_lower or "tags" in btn_text_lower:
                    should_parse_tags = True
            
            # Fallback: Check if the content div itself has "Tags:" string at start if button text was generic
            if not should_parse_tags and content_div:
                 content_text_start = content_div.get_text(separator=' ', strip=True)[:20].lower()
                 if "tags" in content_text_start:
                     should_parse_tags = True

            if should_parse_tags and content_div:
                raw_tags_text = content_div.get_text(separator=',', strip=True)
                # Remove "Tags:" prefix if present
                raw_tags_text = re.sub(r'(?i)^tags:?\s*', '', raw_tags_text)
                
                if raw_tags_text:
                    parsed_tags = [tag.strip() for tag in raw_tags_text.split(',') if tag.strip()]
                    for pt in parsed_tags:
                        if pt not in data['tags']: data['tags'].append(pt)
                    # We found tags in spoiler, stop looking
                    break
    
    # Priority 3: Old/Legacy formats
    if not data['tags'] and bb_wrapper: 
        if tags_dt := bb_wrapper.find('dt', string=lambda t: t and 'tags' in t.lower()):
            if tags_dd := tags_dt.find_next_sibling('dd'): 
                tag_links = tags_dd.find_all('a')
                for tag_link in tag_links:
                    tag_text = tag_link.get_text(strip=True)
                    if tag_text not in data['tags']: data['tags'].append(tag_text)

    # --- DL Lists ---
    dls = soup.find_all('dl')
    for dl_element in dls:
        dt_elements = dl_element.find_all('dt')
        for dt in dt_elements:
            dt_text_lower = dt.get_text(strip=True).lower()
            dd = dt.find_next_sibling('dd')
            if not dd: continue
            dd_text = dd.get_text(strip=True)
            if 'developer' in dt_text_lower or 'author' in dt_text_lower:
                link_in_dd = dd.find('a')
                if link_in_dd and link_in_dd.get_text(strip=True): data['author_from_dl_list'] = link_in_dd.get_text(strip=True)
                elif dd_text: data['author_from_dl_list'] = dd_text
            elif 'version' in dt_text_lower: data['version_from_dl_list'] = dd_text
            elif 'engine' in dt_text_lower or 'game engine' in dt_text_lower: data['engine'] = dd_text
            elif 'language' in dt_text_lower: data['language'] = dd_text
            elif 'status' in dt_text_lower: data['status'] = dd_text
            elif 'censorship' in dt_text_lower or 'censor' in dt_text_lower: data['censorship'] = dd_text
            elif ('os' in dt_text_lower or 'platform' in dt_text_lower) and data['os_general_list'] == "Not found": data['os_general_list'] = dd_text

    # --- Infer Engine/Status/Censorship ---
    if isinstance(data['tags'], list) and data['tags'] != ["Not found"]:
        for tag_text_original in data['tags']:
            tag_text_lower = tag_text_original.lower()
            if data['engine'] == "Not found" and any(eng_name in tag_text_lower for eng_name in ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal', 'qsp', 'tyrano', 'wolf rpg']):
                data['engine'] = tag_text_original
            if data['status'] == "Not found" and any(st_name in tag_text_lower for st_name in ['completed', 'ongoing', 'on hold', 'on-hold', 'abandoned', 'hiatus']):
                data['status'] = tag_text_original
            if data['censorship'] == "Not found" and any(cen_kw in tag_text_lower for cen_kw in ['uncensored', 'censored']):
                data['censorship'] = tag_text_original
    
    if data['engine'] == "Not found" and data['title_full_raw']:
        title_lower_for_engine = data['title_full_raw'].lower()
        engine_keywords_title = ['ren\'py', 'unity', 'rpg maker', 'html', 'unreal engine', 'qsp', 'tyranobuilder', 'wolf rpg']
        for eng_key in engine_keywords_title:
            if eng_key in title_lower_for_engine:
                start_index = title_lower_for_engine.find(eng_key)
                data['engine'] = data['title_full_raw'][start_index : start_index + len(eng_key)]
                break

    # --- Consolidate ---
    if data['author_from_post_label'] != "Not found": data['final_author'] = data['author_from_post_label']
    elif data['author_from_dl_list'] != "Not found": data['final_author'] = data['author_from_dl_list']
    elif data['author_from_title'] != "Not found": data['final_author'] = data['author_from_title']
    elif data['author_from_thread_starter'] != "Not found": data['final_author'] = data['author_from_thread_starter']
    else: data['final_author'] = "Not found"

    if data['version_from_title'] != "Not found": data['final_version'] = data['version_from_title']
    elif data['version_from_post'] != "Not found": data['final_version'] = data['version_from_post']
    elif data['version_from_dl_list'] != "Not found": data['final_version'] = data['version_from_dl_list']
    else: data['final_version'] = "Not found"

    data['final_game_name'] = data['name']
    if data['final_game_name'] and data['engine'] and data['engine'] != "Not found":
        engine_lower = data['engine'].lower()
        game_name_lower = data['final_game_name'].lower()
        if game_name_lower.startswith(engine_lower) and game_name_lower != engine_lower:
            match_engine_prefix = re.match(re.escape(data['engine']), data['final_game_name'], re.IGNORECASE)
            if match_engine_prefix:
                engine_len_in_title = len(match_engine_prefix.group(0))
                if len(data['final_game_name']) > engine_len_in_title:
                    data['final_game_name'] = data['final_game_name'][engine_len_in_title:].lstrip(' -:[]()').strip()

    if not data['final_game_name'] or data['final_game_name'].lower() == data['engine'].lower():
        data['final_game_name'] = data['title_full_raw'] if data['title_full_raw'] else "Not found"

    result_data = {
        "url": data['url'],
        "title": data['final_game_name'],
        "version": data['final_version'],
        "author": data['final_author'],
        "tags": data['tags'] if data['tags'] else ["Not found"],
        "full_description": data['full_description'],
        "download_links": data['download_links'] if data['download_links'] else [],
        "engine": data['engine'],
        "language": data['language'],
        "status": data['status'],
        "censorship": data['censorship'],
        "release_date": data['release_date'],
        "thread_updated_date": data['thread_updated_date'],
        "os_general_list": data['os_general_list'],
        "os_general_list": data['os_general_list'],
        "image_url": data['image_url'],
        "download_links_raw_html": data['download_links_raw_html']
    }
    for key, value in result_data.items():
        if value is None: result_data[key] = "Not found"

    # --- Sanitize Status ---
    valid_statuses = ["Completed", "Ongoing", "On Hold", "Abandoned"]
    if result_data['status'] not in valid_statuses:
        # Fuzzy match or cleanup
        st_lower = result_data['status'].lower()
        if "complete" in st_lower: result_data['status'] = "Completed"
        elif "ongoing" in st_lower: result_data['status'] = "Ongoing"
        elif "on hold" in st_lower or "on-hold" in st_lower or "hiatus" in st_lower: result_data['status'] = "On Hold"
        elif "abandoned" in st_lower: result_data['status'] = "Abandoned"
        else:
            # If "With Emerald." or other garbage, reset to "Unknown" (or "Not found")
            # Log warning
            logger_scraper.warning(f"Sanitizing unknown status '{result_data['status']}' to 'Unknown'")
            result_data['status'] = "Unknown"

    return result_data


# --- Playwright Fallback Logic ---
def login_to_f95zone(page, username, password, target_url_after_login=None):
    """
    Logs into F95zone using Playwright.
    """
    try:
        logger_scraper.info("Login Attempt: Initiated.")
        page.fill("input[name='login']", username)
        page.fill("input[name='password']", password)
        login_button = page.locator("button.button--primary", has_text="Log in")
        if not login_button.count(): 
            login_button = page.locator("form.block[action='/login/login'] button[type='submit']")
        if not login_button.count():
            login_button = page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))

        if login_button.count():
            login_button.first.click(timeout=25000) 
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        else:
            return False

        # Check for login success
        if page.query_selector(f"div.p-account.p-navgroup--member span.p-navgroup-linkText:text-matches('{re.escape(username)}')"):
            if target_url_after_login:
                page.goto(target_url_after_login, timeout=60000, wait_until="domcontentloaded")
            return True
        return False
    except Exception as e:
        logger_scraper.error(f"LOGIN ERROR: {e}")
        return False

# --- Hybrid Extraction Function ---
def extract_game_data(game_thread_url, username=None, password=None, requests_session=None):
    """
    Extracts detailed information from an F95zone game thread page.
    Attempts lightweight requests-based scrape first, then falls back to Playwright.
    """
    logger_scraper.info(f"EXTRACT_GAME_DATA: Starting extraction for: {game_thread_url}")

    # --- Attempt 1: Lightweight Requests ---
    if requests_session:
        logger_scraper.info("EXTRACT_GAME_DATA: Attempting lightweight scrape using provided requests session.")
        try:
            response = requests_session.get(game_thread_url, timeout=20)
            if response.status_code == 200:
                # Check for Cloudflare or Block
                if "Just a moment..." in response.text or "Enable JavaScript and cookies to continue" in response.text:
                    logger_scraper.warning("EXTRACT_GAME_DATA: Requests fetch hit Cloudflare detection. Falling back to Playwright.")
                elif "You don't have permission to view the spoiler content" in response.text or "Log in or register now" in response.text:
                    logger_scraper.warning("EXTRACT_GAME_DATA: Requests fetch returned Guest view (spoiler blocked). detailed data missing. Falling back to Playwright for authenticated scrape.")
                else:
                    logger_scraper.info("EXTRACT_GAME_DATA: Requests fetch successful. Parsing content...")
                    result = parse_game_page_content(response.content, game_thread_url)
                    if result and result.get('title') != "Not found":
                        # Check if data qualifies as "Complete" - if not, we might want to fall back to Playwright
                        # e.g. if Tags are missing or Download links are empty, it might be a Guest view issue
                        missing_tags = not result.get('tags') or result['tags'] == ["Not found"]
                        missing_links = not result.get('download_links')
                        missing_status = result.get('status') in ["Not found", "Unknown"]
                        
                        if missing_tags or missing_links or missing_status:
                             logger_scraper.warning(f"EXTRACT_GAME_DATA: Lightweight extraction incomplete (Status: {result.get('status')}, Tags: {not missing_tags}, Links: {not missing_links}). Falling back to Playwright.")
                        else:
                            logger_scraper.info("EXTRACT_GAME_DATA: Lightweight extraction successful.")
                            return result
                    else:
                        logger_scraper.warning("EXTRACT_GAME_DATA: Lightweight extraction yielded empty data. Falling back.")
            else:
                logger_scraper.warning(f"EXTRACT_GAME_DATA: Requests fetch failed with status {response.status_code}. Falling back.")
        except Exception as e:
            logger_scraper.error(f"EXTRACT_GAME_DATA: Lightweight scrape error: {e}. Falling back.")

    # --- Attempt 2: Playwright Fallback ---
    logger_scraper.info("EXTRACT_GAME_DATA: Initiating Playwright fallback.")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            page = context.new_page()
            
            logged_in = False
            if username and password:
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=30000)
                logged_in = login_to_f95zone(page, username, password, target_url_after_login=game_thread_url)
            
            if not logged_in:
                 page.goto(game_thread_url, wait_until="domcontentloaded", timeout=45000)

            # Click Spoilers (legacy logic preserved)
            try:
                page.wait_for_selector("button.bbCodeSpoiler-button", timeout=5000)
                buttons = page.query_selector_all("button.bbCodeSpoiler-button")
                for btn in buttons:
                    if btn.is_visible(): btn.click(timeout=2000)
                    page.wait_for_timeout(500)
            except: pass

            page.wait_for_timeout(5000) # Increased to 5s to allow JS to populate status
            html_content = page.content()
            browser.close()

            logger_scraper.info("EXTRACT_GAME_DATA: Playwright fetch complete. Parsing content...")
            return parse_game_page_content(html_content, game_thread_url)

    except Exception as e:
        logger_scraper.error(f"EXTRACT_GAME_DATA: Playwright fallback failed: {e}", exc_info=True)
        return None