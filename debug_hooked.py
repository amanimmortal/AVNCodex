import logging
import sys
import os

# Setup logging to console
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Add app to path
sys.path.append(os.getcwd())

from app.f95_web_scraper import parse_game_page_content

# Mock HTML content for Hooked! based on typical structure if I can't fetch it
# But I should try to fetch it if possible? Use requests first.
# Since I can't easily auth, I'll interpret the user's description.
# "Only the word Win shows up".

# Let's try to mock a structure that might cause this failure.
# Maybe the links are inside a spoiler that IS unwrapped, but the loop fails?
# Or maybe the links are just text?

# BETTER: Just run the scraper against the URL using the existing Playwright/Requests logic if possible.
# I will try to verify using a mock first that reproduces "Header found, links skipped".

mock_html_hooked = """
<div class="bbWrapper">
    <b>Download</b><br>
    <div class="bbCodeSpoiler">
        <button class="bbCodeSpoiler-button">Spoiler</button>
        <div class="bbCodeSpoiler-content">
            <div class="bbCodeBlock-content">
                 <b>Win</b><br>
                 <a href="https://gofile.io/d/123" target="_blank">GoFile</a><br>
                 <a href="https://mega.nz/file/123" target="_blank">Mega</a>
            </div>
        </div>
    </div>
</div>
"""

# If my unwrap logic works, this should become:
# <b>Download</b>
# <div class="bbCodeBlock-content">...</div>

# And the linear scanner will enter the div?
# Wait. `current_node = current_node.next_sibling`
# If `download_header_node` is "Download" (text or b), its next sibling might be `<br>`.
# Then next sibling is `div.bbCodeSpoiler` (or the replaced content).
# The scraper loop:
# `if hasattr(current_node, 'descendants'):` -> It's a tag.
# If it's the `div.bbCodeConfig-content` (the unwrapped spoiler), does it have `descendants`? Yes.
# Does the scraper recurse into it to find links?
# The scraper has:
# `if current_node.name == 'a': ...`
# `elif hasattr(current_node, 'find_all'): all_links = current_node.find_all('a') ...`
# So it DOES find links inside the container.

# So why would it fail?
# Maybe the "Download" header is INSIDE the spoiler?
# User said: "Only the word Win shows up".
# This implies "Win" was detected as a section header.
# "Win" is likely inside the spoiler.
# If "Win" was detected, it means the scraper processed the "Win" node.
# If it processed "Win", it continued.
# Why didn't it match the links?
# Maybe the links text/href didn't match validation?
# `if not href or ... continue`
# `if "attachments.f95zone.to" ... continue`

# Let's write a script that dumps the scraping result of the mock.

print("--- Testing Mock Scrape ---")
data = parse_game_page_content(mock_html_hooked, "http://mock")
print("Download Links Found:", len(data['download_links']))
for l in data['download_links']:
    print(l)

print("\n--- Testing Raw HTML Extraction ---")
print(data.get('download_links_raw_html', 'No Raw HTML'))
