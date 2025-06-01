# Process for Extracting Game Data from F95zone

This document outlines the steps used to navigate F95zone, find specific games, and extract information from their pages, primarily using Playwright tools to interact with the website and retrieve HTML content for analysis.

## Prerequisites

1.  **Valid User Credentials:** Access to some pages (like the SAM 'latest_alpha' lists) and game threads requires being logged in.
2.  **Playwright Tools:** The process relies on tools that can navigate web pages, retrieve HTML content, and execute basic browser actions.

## Step-by-Step Process

1.  **Login (Initial Step / If Session Expires):**
    *   Navigate to the login page: `https://f95zone.to/login/login`.
    *   Use a tool to fill the username input (e.g., `input[name='login']`) with the provided username.
    *   Use a tool to fill the password input (e.g., `input[name='password']`) with the provided password.
    *   Use a tool to click the login button (e.g., `button:has-text('Log in')`).
    *   Allow a brief pause for login processing and potential redirects.

2.  **Navigate to the Filtered Game List:**
    *   Use a navigation tool to go to the desired SAM (Search and Manager) game list page.
    *   Example URL for filtered "Games" (prefix 7), page `X`: `https://f95zone.to/sam/latest_alpha/#/cat=games/page=X/prefixes=7` (replace `X` with the desired page number).

3.  **Retrieve HTML of the Game List Page:**
    *   Once on the game list page, use a tool like `mcp_playwright_playwright_get_visible_html` to fetch the complete HTML content of the page.

4.  **Parse Game List HTML to Find Game Thread URL:**
    *   **Identify Game Entries:** The game list page contains multiple game entries. In the SAM interface, these are often represented by `div` elements with a class like `resource-tile` or `structItem` containing an `article` tag.
    *   **Locate Target Game Link:** Within the HTML for the desired game entry (e.g., the first one for "Takei's Journey" or "A Series of Changes" in our examples), find the primary anchor (`<a>`) tag that links to the game's main thread page. This link is usually associated with the game's title.
        *   A common XPath/CSS selector pattern for the container of a game might be `//div[contains(@class, 'resource-tile')]` or `//article[contains(@class, 'structItem')]`.
        *   Within that, the link might be identifiable via `//h3[contains(@class, 'resource-title')]/a` or `.structItem-title a`.
    *   **Extract `href`:** From the located `<a>` tag, extract the value of its `href` attribute.
    *   **Form Absolute URL:** If the extracted `href` is relative (e.g., `/threads/game-title.12345/`), prepend the base URL (`https://f95zone.to`) to form an absolute URL.

5.  **Navigate to the Game Thread Page:**
    *   Use a navigation tool with the absolute URL obtained in the previous step to go directly to the game's thread page.

6.  **Retrieve HTML of the Game Thread Page:**
    *   Once on the game's thread page, use a tool like `mcp_playwright_playwright_get_visible_html` again to fetch its complete HTML content.

7.  **Parse Game Thread HTML to Extract Specific Information:**

    The RSS feed provides several key pieces of data: Game Name, Version, a Preview Image URL, Author/Developer, Game Thread URL, and a Publication/Update Date. The primary goal of parsing the game thread page is to obtain data *not* available in the RSS feed.

    Once the HTML of the game thread page is retrieved (as per Step 6), parse it to find the following information. The methods described below involve searching the HTML for specific keywords, labels, and common structural patterns (like `<div>`s with certain classes, `<dt>`/`<dd>` pairs, or content within the first post of the thread).

    *   **a) Tags/Categories:**
        *   _(This is not available in the RSS feed)._
        *   **How to find:** Search for an element labeling the tags section (e.g., `<dt>Tags</dt>`, a `div` or heading with "Tags"). The actual tags are typically `<a>` (anchor) tags within the subsequent element (e.g., `<dd>` or a dedicated tags `div`). Extract the inner text of these `<a>` tags.

    *   **b) Full Game Description/Overview:**
        *   _(The RSS feed only contains a preview image, not the comprehensive textual description)._
        *   **How to find:** This is usually the main content of the first post in the thread. Look for elements like `div.message-content`, `div.bbWrapper`, or the primary content `div` of an `article` tag associated with the thread starter. The content may include detailed text, images, and further sub-sections.

    *   **c) Changelog:**
        *   _(This is generally not in the RSS feed, or only indirectly implied by an update)._
        *   **How to find:** Often located within the main game description/overview or as a separate section explicitly labeled. Look for headings like "Changelog", "What's New", "Update Notes", or similar. It might be enclosed in spoiler tags (e.g., `div.bbCodeSpoiler`) or a distinct formatted block.

    *   **d) Download Links:**
        *   _(These are critical and not available in the RSS feed)._
        *   **How to find:** These are anchor (`<a>`) tags. Search for keywords such as "Download", names of common file-hosting services (e.g., "Mega", "Google Drive", "MediaFire"), or direct file extensions (e.g., `.zip`, `.rar`, `.apk`) within the `href` attribute or the link's text. Links are frequently found within spoiler tags, specially styled `div` elements, or `button` elements. Multiple links for different versions, platforms, or hosts may exist.

    *   **e) Game Engine:**
        *   _(This information is not in the RSS feed)._
        *   **How to find:** May be explicitly stated near the game title, in the description, tags, or a dedicated "Information" block. Look for keywords: "Engine", "Made with", "Ren'Py", "Unity", "RPG Maker", "HTML", "TyranoBuilder", etc.

    *   **f) Language(s):**
        *   _(This information is not in the RSS feed)._
        *   **How to find:** Look for a "Language" label or common language names (e.g., "English", "Español", "Русский") in an information block or within the game's description. The site is primarily English, but some games might offer or specify other languages.

    *   **g) Development Status:**
        *   _(This information is not typically in the RSS feed, although a version number might imply it for some games)._
        *   **How to find:** Look for terms like "Ongoing", "Completed", "Hiatus", "Abandoned". This might be present in tags, the game title prefix/suffix, or explicitly stated in the description or an information block.

    *   **h) Censorship Information:**
        *   _(This information is not in the RSS feed)._
        *   **How to find:** Look for terms such as "Censored", "Uncensored", "Optional patch". This is often found in tags or explicitly mentioned in the game description or an information block.

    *(The following data points are generally available from the RSS feed. While they can also be extracted from the game page for confirmation or if a more canonical/detailed version is needed, they are not the primary targets for new information):*
    *   _Game Title (often found in `<h1>` or a prominent header in the thread view)._
    *   _Version (may be part of the thread title or explicitly listed)._
    *   _Author/Developer (look for labels like "Author", "Developer", "Thread starter" and the associated user profile link/name)._
    *   _Release Date/Last Update (compare with RSS `pubDate`; the game page might offer more specific dates like initial release vs. last update)._

8.  **Verification (Optional but Recommended):**
    *   At various stages (e.g., after navigating to a page, before parsing), use a tool like `mcp_playwright_playwright_screenshot` to capture an image of the current page. This helps in debugging and verifying that the process is interacting with the correct elements and pages.

This documented process provides a systematic way to extract data. The key is the ability to fetch and then analyze raw HTML content, as direct DOM manipulation or element attribute extraction via JavaScript evaluation proved unreliable in some contexts on this site. 