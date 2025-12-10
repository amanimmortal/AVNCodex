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
            
            # 1. Find the "DOWNLOAD" start marker
            # Strategy: Look for "DOWNLOAD" string in case-insensitive way.
            # We want the *highest* logical node that represents just the header.
            # Iterate descendants once?
            
            # Helper to check if text is predominantly "DOWNLOAD"
            def is_download_header_text(txt):
                if not txt: return False
                t = txt.strip().lower()
                return "download" in t and len(t) < 30 and "below" not in t and "click" not in t # "Click download below" vs "DOWNLOAD"

            for elem in bb_wrapper.descendants:
                 # Check Headers/Strong tags directly
                 if elem.name in ['h1','h2','h3','h4','strong','b','u','span']:
                     if is_download_header_text(elem.get_text(strip=True)):
                         download_header_node = elem
                         break
                 
                 # Check isolated Text Nodes
                 if isinstance(elem, str):
                     if is_download_header_text(elem) and elem.parent.name not in ['script', 'style', 'a']:
                         # Promote to parent if parent is just a wrapper for this text
                         if len(elem.parent.get_text(strip=True)) < 40:
                             download_header_node = elem.parent
                         else:
                             download_header_node = elem # Just the text
                         break
            
            if download_header_node:
                captured_html = ""
                current_node = download_header_node
                
                # We start capturing from the node *after* the header, or include the header?
                # Usually we want the buttons, so maybe include header is fine for context.
                # Let's include the header.
                
                # Linear Walk Strategy
                # We need to walk 'next elements' until we hit the thumbnails.
                # 'next_element' walks the tree in document order.
                
                # Limit safety
                steps = 0
                max_steps = 2000 
                
                # Stop Condition Check
                def should_stop(node):
                     if not node: return False
                     if isinstance(node, str): return False
                     
                     # 1. Thumbnails Container (lbContainer)
                     classes = node.get('class', [])
                     if 'lbContainer' in classes or 'js-lbContainer' in classes:
                         return True
                     
                     # 2. Attachments Image or Link
                     # Check if it's an image/link pointing to attachments.f95zone.to
                     # (Users said: "always BEFORE the thumbnails... which start with attachments.f95zone.to")
                     if node.name == 'img':
                         src = node.get('src', '') or node.get('data-url', '')
                         if "attachments.f95zone.to" in src: return True
                     if node.name == 'a':
                         href = node.get('href', '')
                         if "attachments.f95zone.to" in href: return True
                         
                     return False

                # We iterate utilizing next_sibling if possible to skip walking *into* the thumbnails
                # But we need to capture deep content of the downloads.
                
                # Better Strategy: Walk siblings of the header's parent, or the header itself.
                # If header is deep inside a structure, we might miss siblings effectively.
                # Usually "DOWNLOAD" is a root-level or near-root level element in the post.
                
                iter_node = current_node
                
                while iter_node and steps < max_steps:
                    steps += 1
                    
                    # Check stop logic on the *current* node before processing
                    if should_stop(iter_node):
                        logger_scraper.info("DEBUG: Stopping download extraction at thumbnails/attachments.")
                        break
                    
                    # Append Content
                    # If it's a Tag, we clean it and check if it *contains* the stop condition (nested thumbnails)
                    # If it contains thumbnails, we might want to salvage the part before them? 
                    # For simplicity, if a block contains the stop condition, we stop *at* that block?
                    # Or we walk into it?
                    # Given the user says thumbnails are "at the bottom", they are likely a sibling block or the last block.
                    
                    if not isinstance(iter_node, str):
                        # Tag Processing
                        
                        # 1. Remove all Images (User requested "imageless")
                        # We do this on the node *before* converting to string
                        if hasattr(iter_node, 'find_all'):
                             for img in iter_node.find_all('img'):
                                 img.decompose()
                             if iter_node.name == 'img':
                                 # If the node itself is an image, skip it
                                 iter_node = iter_node.next_sibling # Step over? 
                                 # We need to handle step logic if we skip the current node logic
                                 # Easier to just not append it
                                 
                                 # Update iter_node loop logic
                                 next_node = iter_node.next_sibling
                                 if not next_node:
                                      parent = iter_node.parent
                                      if parent and 'bbWrapper' not in parent.get('class', []):
                                           next_node = parent.next_sibling
                                 iter_node = next_node
                                 continue

                        # 2. Force Button Classes on Links
                        if iter_node.name == 'a':
                             href = iter_node.get('href', '')
                             if href and not href.startswith('#') and 'attachments.f95zone.to' not in href:
                                  classes = iter_node.get('class', [])
                                  if 'download-link-btn' not in classes:
                                      classes.append('download-link-btn')
                                      iter_node['class'] = classes
                                  # Remove inline styles that might mess up buttons
                                  if iter_node.has_attr('style'): del iter_node['style']
                                      
                        elif hasattr(iter_node, 'find_all'):
                             all_links = iter_node.find_all('a')
                             for lnk in all_links:
                                  href = lnk.get('href', '')
                                  if href and not href.startswith('#') and 'attachments.f95zone.to' not in href:
                                       classes = lnk.get('class', [])
                                       if 'download-link-btn' not in classes:
                                           classes.append('download-link-btn')
                                           lnk['class'] = classes
                                       if lnk.has_attr('style'): del lnk['style']

                        # 3. Clean Text Inside Tags (e.g. " - [Win]" -> "[Win]")
                        # 4. Check if the Tag itself is a Layout Header
                        # If a tag is NOT a link (and not containing links), check its text.
                        # If it matches our header logic, we convert it to a header block.
                        
                        is_link = (iter_node.name == 'a') or (iter_node.find('a') is not None)
                        
                        if not is_link and iter_node.name not in ['script', 'style', 'img']:
                             # Get direct text or full text
                             tag_text = iter_node.get_text(strip=True)
                             
                             # Noise check (e.g. isolated "*")
                             if re.match(r'^[\s\-\:|*]+$', tag_text):
                                  iter_node.decompose() # It's just noise
                                  captured_html += "" # Don't append anything
                                  # Continue loop logic handled by next_sibling below
                                  # But we need to skip the captured_html += link below
                                  # Easier to set a flag or just continue
                             else:
                                  # Header Logic
                                  upper_clean = re.sub(r'^\s*[\-\:|*]\s*', '', tag_text).replace(':', '').strip().upper()
                                  known_headers = ["WIN/LINUX", "MAC", "LINUX", "ANDROID", "EXTRAS", "WALKTHROUGH", "OTHERS", "PC", "APK", "PATCH", "DOWNLOAD", "DOWNLOADS", "WIN", "WINDOWS"]
                                  
                                  is_header = False
                                  if upper_clean in known_headers:
                                      is_header = True
                                  elif len(upper_clean) > 2 and len(upper_clean) < 30 and upper_clean.isupper() and re.match(r'^[A-Z0-9\/\s\(\)]+$', upper_clean):
                                      if tag_text.strip().endswith(':'): is_header = True
                                      
                                  if is_header:
                                       # Convert to Div Header
                                       iter_node.name = 'div'
                                       iter_node['class'] = ['download-group-header']
                                       # Remove inline styles
                                       if iter_node.has_attr('style'): del iter_node['style']
                                  
                                  captured_html += str(iter_node)
                        else:
                             captured_html += str(iter_node)
                    
                    else:
                         # NavigableString Logic (Top Level Text Nodes)
                         text = str(iter_node)
                         
                         # Aggressive Cleaning of "Noise" Nodes
                         # Check if the node is JUST separators/whitespace/stars
                         is_noise = re.match(r'^[\s\-\:|*]+$', text)
                         
                         if not is_noise:
                             # It has content, but might have leading/trailing separators
                             # e.g. " - Download Here"
                             cleaned = re.sub(r'^\s*[\-\:|*]\s*', '', text) 
                             cleaned = re.sub(r'\s*[\-\:|*]\s*$', '', cleaned)
                             
                             if cleaned.strip():
                                 # Detect Headers
                                 upper_clean = cleaned.strip().upper()
                                 known_headers = ["WIN/LINUX", "MAC", "LINUX", "ANDROID", "EXTRAS", "WALKTHROUGH", "OTHERS", "PC", "APK", "PATCH", "DOWNLOAD", "DOWNLOADS", "WIN", "WINDOWS"]
                                 is_header = False
                                 
                                 if upper_clean in known_headers:
                                     is_header = True
                                 elif len(upper_clean) > 2 and len(upper_clean) < 30 and upper_clean.isupper() and re.match(r'^[A-Z0-9\/\s\(\)]+$', upper_clean):
                                     # If the original text ended with a colon, it's likely a header
                                     if text.strip().endswith(':'): is_header = True
                                 
                                 if is_header:
                                      captured_html += f'<div class="download-group-header">{cleaned.strip()}</div>'
                                 else:
                                      captured_html += cleaned
                         else:
                             # It is noise, Skip appending
                             pass

                    # Step Logic
                    next_node = iter_node.next_sibling
                    if not next_node:
                        parent = iter_node.parent
                        if parent and 'bbWrapper' not in parent.get('class', []):
                             next_node = parent.next_sibling
                    
                    iter_node = next_node

                if captured_html:
                     # Clean unsafe tags
                     soup_clean = BeautifulSoup(captured_html, 'html.parser')
                     for unsafe in soup_clean.find_all(['script', 'iframe', 'form', 'style']):
                         unsafe.decompose()
                     
                     # Final pass: Remove empty text nodes or empty spans?
                     # Also remove images again just in case (soup_clean ensures deep clean)
                     for img in soup_clean.find_all('img'): img.decompose()

                     data['download_links_raw_html'] = str(soup_clean)
                     logger_scraper.info("DEBUG: Successfully extracted raw download HTML block (Robust Method).")
            else:
                 logger_scraper.info("DEBUG: 'DOWNLOAD' marker not found for raw block extraction.")

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

def extract_game_data(game_thread_url, username=None, password=None, requests_session=None):
    """
    Extracts detailed information from an F95zone game thread page.
    Uses authenticated Playwright scraping ONLY (Requests fallback removed for robustness).
    """
    logger_scraper.info(f"EXTRACT_GAME_DATA: Starting extraction for: {game_thread_url}")
    
    # NOTE: requests_session argument is kept for signature compatibility but ignored.

    logger_scraper.info("EXTRACT_GAME_DATA: Initiating Playwright session.")
    try:
        with sync_playwright() as p:
            # Launch options - headless but can be toggled for debugging
            browser = p.chromium.launch(headless=True)
            
            # Browser Context with standard User Agent
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            page = context.new_page()
            
            # 1. Login Logic
            logged_in = False
            if username and password:
                # Go to login page first
                logger_scraper.info("EXTRACT_GAME_DATA: Navigating to login page...")
                page.goto("https://f95zone.to/login/login", wait_until="domcontentloaded", timeout=45000)
                
                # Perform login
                logged_in = login_to_f95zone(page, username, password, target_url_after_login=game_thread_url)
                if not logged_in:
                     logger_scraper.warning("EXTRACT_GAME_DATA: Login failed or not verified. Will attempt to scrape as Guest (likely to fail for some content).")
            else:
                 logger_scraper.warning("EXTRACT_GAME_DATA: No credentials provided. Scraping as Guest.")
            
            # 2. Navigate to Game Thread (if not already there from login redirect)
            if not logged_in or page.url != game_thread_url:
                 logger_scraper.info(f"EXTRACT_GAME_DATA: Navigating to game thread: {game_thread_url}")
                 page.goto(game_thread_url, wait_until="domcontentloaded", timeout=60000)

            # 3. Smart Waits & Interaction
            # Wait for the main post content to be visible - this is the signal the useful part has loaded.
            try:
                page.wait_for_selector("article.message--post", timeout=15000)
            except Exception:
                logger_scraper.warning("EXTRACT_GAME_DATA: Timeout waiting for article.message--post. Page might be broken or Cloudflare blocked.")
            
            # Expand Spoilers (Legacy logic, helpful for full text)
            try:
                # We only click spoilers that might look like "Tags" or "Genre" or generic triggers
                # But typically we unwrap them in the soup parser anyway. 
                # Clicking them in JS ensures the DOM is fully hydrated if they are lazy loaded.
                
                # Check if we have any spoilers
                if page.locator("button.bbCodeSpoiler-button").count() > 0:
                    # Click all visible ones? Risks clicking 'download' spoilers that we want to parse structure of.
                    # Actually, we want to click them so the HTML snapshot contains the expanded content.
                    # LIMIT: Only click first 10 to avoid stalling on massive Changelogs?
                    # The soup parser handles unwrapping global spoilers now, so this might be redundant 
                    # UNLESS content isn't in DOM until clicked (unlikely for XF2).
                    # We'll skip massive clicking to speed things up, trusting the Soup 'Global Unwrap' logic.
                    pass 
            except: pass

            # Safety Buffer - minimal wait to allow any final JS (like status field) to settle
            # Reduced from 5000 to 1500
            page.wait_for_timeout(1500) 
            
            # 4. Capture Content
            html_content = page.content()
            browser.close()

            logger_scraper.info("EXTRACT_GAME_DATA: Playwright fetch complete. Parsing content...")
            return parse_game_page_content(html_content, game_thread_url)

    except Exception as e:
        logger_scraper.error(f"EXTRACT_GAME_DATA: Playwright session failed: {e}", exc_info=True)
        return None