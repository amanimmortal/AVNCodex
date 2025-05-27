# f95apiclient/__init__.py

import requests
from requests.exceptions import ProxyError, ConnectTimeout, ReadTimeout, SSLError # For retry logic
from bs4 import BeautifulSoup # Removed NavigableString, Tag as _parse_handiwork_page is removed
# import json # Removed as JSON-LD parsing is removed
import re # For regex-based parsing
import logging # Added for logging
import random # Added for random sampling and proxy selection
import urllib.parse # Added for URL encoding
import time # Added for retry delay
from typing import Optional

# Setup basic logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants based on F95API (Node.js version) ---
F95_BASE_URL = "https://f95zone.to"
F95_LOGIN_URL = f"{F95_BASE_URL}/login/login"
F95_LOGIN_2FA_URL = f"{F95_BASE_URL}/login/two-step"
HTTP_PROXY_LIST_URL = "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/https.txt" # Switched to vakhov's HTTPS-specific list
SOCKS5_PROXY_LIST_URL = "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt" # New
# F95_LATEST_UPDATES_URL = f"{F95_BASE_URL}/sam/latest_alpha/" # HTML page, old method - REMOVED
# F95_LATEST_UPDATES_RSS_URL = f"{F95_BASE_URL}/sam/latest_alpha/latest_data.php?cmd=rss&cat=games&rows=60" # REMOVED - URL is now dynamic

# CSS Selectors from GENERIC section of css-selector.ts
SEL_CSRF_TOKEN_INPUT = 'input[name="_xfToken"]'
SEL_LOGIN_ERROR_BANNER = "div.blockMessage.blockMessage--error.blockMessage--iconic"
SEL_CURRENT_USER_ID_SPAN = "span.avatar[data-user-id]" # Indicates successful login if present

# CSS Selectors for Thread/Post parsing (derived from F95API) - REMOVED as no longer parsing pages
# SEL_THREAD_JSONLD = 'script[type="application/ld+json"]'
# SEL_THREAD_TITLE = "h1.p-title-value"
# SEL_THREAD_PREFIXES = 'h1.p-title-value a.labelLink span[dir="auto"]'
# SEL_THREAD_TAGS = "div.tagList > a.tagItem"
# SEL_POST_ARTICLE = "article.message"
# SEL_POST_BODY_WRAPPER = "div.bbWrapper"
# SEL_POST_AUTHOR_ID = "div.message-cell--user a.avatar[data-user-id]"
# SEL_POST_PUBLISH_DATE = "div.message-attribution-main > a > time"
# SEL_POST_SPOILER_WRAPPER = "div.bbCodeSpoiler"
# SEL_POST_SPOILER_BUTTON_TITLE = "button.bbCodeSpoiler-button span.bbCodeSpoiler-button-title"
# SEL_POST_SPOILER_CONTENT = "div.bbCodeSpoiler-content div.bbCodeBlock-content"
# SEL_LATEST_UPDATES_GAME_LINK = "a[data-tp-primary='on'][href*='/threads/']"

# Known error messages from messageToCode function
MSG_INCORRECT_CREDENTIALS = "Incorrect password. Please try again."
MSG_REQUIRE_CAPTCHA = "You did not complete the CAPTCHA verification properly. Please try again."
MSG_AUTH_SUCCESSFUL = "Authentication successful"

# Metadata keys (from ot-metadata-values.ts in F95API, simplified for direct use) - REMOVED as no longer parsing pages
# MD_KEY_VERSION = ["Version", "Game Version"]
# MD_KEY_AUTHOR = ["Author", "Developer", "Creator"]
# ... and other MD_KEY_* constants removed

# Removed get_direct_text as it was used by _parse_handiwork_page

class F95ApiClient:
    def __init__(self, session_cookies=None, max_attempts=5, retry_delay_seconds=5, request_timeout=15, use_proxies=True):
        """
        Initializes the F95API Client.
        session_cookies: Optional dictionary of cookies to use for requests,
                         can be used to bypass login/CAPTCHA if obtained manually.
        max_attempts: Maximum number of total attempts for requests (1 initial + N-1 retries with new proxies).
        retry_delay_seconds: Delay between retries in seconds (currently unused in the main proxy-switching retry loop).
        request_timeout: Timeout for individual requests in seconds.
        use_proxies: Boolean to enable/disable proxy usage.
        """
        self.base_url = F95_BASE_URL
        self.login_url = F95_LOGIN_URL
        # self.latest_updates_url = F95_LATEST_UPDATES_URL # REMOVED
        self.session = requests.Session()
        self.session.verify = False # Ignore SSL certificate verification issues

        if session_cookies:
            self.session.cookies.update(session_cookies)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self._xf_token = None
        self.logger = logging.getLogger(__name__)
        self.is_logged_in = False

        self.max_attempts = max_attempts # Renamed from max_retries for clarity based on new logic
        self.retry_delay_seconds = retry_delay_seconds # Kept, but not used in the immediate proxy switch loop
        self.request_timeout = request_timeout
        self.use_proxies = use_proxies
        self.available_proxies = [] # Will store tuples of (proxy_url_str, scheme_for_requests_dict)

        if self.use_proxies:
            self._load_proxies()
            if self.available_proxies:
                self._set_random_proxy()
            else:
                self.logger.warning("Proxy usage is enabled, but no proxies were loaded. Proceeding without proxies.")
                self.session.proxies = {}
        else:
            self.logger.info("Proxy usage is disabled by configuration.")
            self.session.proxies = {}

    def _fetch_proxy_list(self, url, proxy_type_scheme):
        """Fetches a list of proxies from a URL and adds them to self.available_proxies."""
        self.logger.info(f"Attempting to load {proxy_type_scheme.upper()} proxy list from: {url}")
        fetched_count = 0
        try:
            response = requests.get(url, timeout=self.request_timeout) 
            response.raise_for_status()
            
            raw_lines = response.text.splitlines()
            for raw_line in raw_lines:
                # Split line by spaces to handle multiple proxies per line, then strip each part
                potential_proxies_on_line = [p.strip() for p in raw_line.split(' ')]
                for line_entry in potential_proxies_on_line:
                    if not line_entry: # Skip empty strings that might result from multiple spaces
                        continue

                    # Basic validation: should be ip:port. 
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line_entry):
                        full_proxy_url = f"{proxy_type_scheme}://{line_entry}"
                        self.available_proxies.append((full_proxy_url, proxy_type_scheme))
                        fetched_count +=1
                    # Check if it already has the scheme (e.g. http://ip:port or socks5h://ip:port)
                    elif line_entry.startswith(f"{proxy_type_scheme}://") and \
                         re.match(r"^"+proxy_type_scheme+r"://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line_entry):
                        self.available_proxies.append((line_entry, proxy_type_scheme))
                        fetched_count += 1
                    elif line_entry: # Log if a non-empty entry didn't match known patterns
                        self.logger.debug(f"Skipping non-matching proxy entry from {url}: '{line_entry}'")

            if fetched_count > 0:
                 self.logger.info(f"Successfully added {fetched_count} {proxy_type_scheme.upper()} proxies from {url}.")
            else:
                self.logger.warning(f"No valid {proxy_type_scheme.upper()} proxies found in the list from {url}.")

        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch or parse {proxy_type_scheme.upper()} proxy list from {url}: {e}")
        except Exception as e: # Catch any other unexpected error
            self.logger.error(f"An unexpected error occurred while loading {proxy_type_scheme.upper()} proxies from {url}: {e}")

    def _load_proxies(self):
        """
        Attempts to load lists of HTTP/HTTPS and SOCKS5 proxies.
        """
        self.available_proxies = [] # Clear any existing proxies
        
        # Fetch HTTPS proxies (which can be used for HTTP/HTTPS traffic)
        # Requests library uses 'http' as scheme for these proxies for both http and https URLs
        self._fetch_proxy_list(HTTP_PROXY_LIST_URL, "http") 
                                                       
        # Fetch SOCKS5 proxies
        self._fetch_proxy_list(SOCKS5_PROXY_LIST_URL, "socks5h") # Using socks5h for remote DNS resolution

        if self.available_proxies:
            random.shuffle(self.available_proxies) # Shuffle the combined list
            self.logger.info(f"Total {len(self.available_proxies)} proxies loaded and shuffled (HTTPS/SOCKS5).")
        else:
            self.logger.warning("No proxies were loaded from any source.")
            
    def _set_random_proxy(self):
        """
        Configures the session to use one randomly selected proxy from self.available_proxies.
        """
        if not self.available_proxies:
            self.logger.debug("No available proxies to set.")
            self.session.proxies = {} # Ensure no proxy is set
            return False

        selected_proxy_url, scheme = random.choice(self.available_proxies)
        
        # The 'scheme' here is what requests needs ('http', 'socks5h', etc.)
        # The actual proxy_url already includes its own scheme (e.g. http://ip:port or socks5h://ip:port)
        self.session.proxies = {
            "http": selected_proxy_url,  # Use this proxy for http:// URLs
            "https": selected_proxy_url  # And also for https:// URLs
        }
        self.logger.info(f"Session configured to use proxy: {selected_proxy_url} (type derived from its scheme: {scheme})")
        return True

    def _make_request(self, method: str, url: str, params: Optional[dict] = None, data: Optional[dict] = None, headers: Optional[dict] = None) -> requests.Response:
        """Makes an HTTP request with the current session, handling proxies and retries."""
        
        effective_headers = self.session.headers.copy()
        if headers:
            effective_headers.update(headers)

        last_exception = None
        # Initialize log_proxy_info with a default for the initial direct attempt
        log_proxy_info = "direct connection" 
        attempt_with_proxy_activated = False 

        for attempt in range(self.max_attempts):
            self.logger.debug(f"Request attempt {attempt + 1}/{self.max_attempts} to {method.upper()} {url}")
            
            current_proxies_for_request = None # Default to no proxy / direct

            # Determine if proxy should be used for this attempt
            if self.use_proxies and self.available_proxies:
                if attempt == 0 and not attempt_with_proxy_activated:
                    # First attempt for a request sequence is direct by default, unless forced
                    self.logger.info(f"Attempt {attempt + 1}: Initial attempt will be direct (no proxy).")
                    log_proxy_info = "direct connection"
                    current_proxies_for_request = {}
                else:
                    # Subsequent attempts or if proxy activation was triggered
                    if not attempt_with_proxy_activated: # Activate proxy usage if not already
                        attempt_with_proxy_activated = True 
                        self.logger.info("Proxy usage activated due to previous failure or settings.")
                    
                    if self._set_random_proxy(): # This sets self.session.proxies
                        current_proxies_for_request = self.session.proxies
                        log_proxy_info = f"proxy {self.current_proxy}"
                        self.logger.info(f"Attempt {attempt + 1}: Using new proxy: {self.current_proxy}")
                    else:
                        # No proxies available, or failed to set one, try direct if allowed or last resort
                        self.logger.warning(f"Attempt {attempt + 1}: No proxy available or failed to set. Attempting direct.")
                        log_proxy_info = "direct connection (fallback)"
                        current_proxies_for_request = {}
            else:
                # Proxies not enabled or none loaded, always direct
                self.logger.info(f"Attempt {attempt + 1}: Making request directly (proxies not enabled or none loaded).")
                log_proxy_info = "direct connection (proxies disabled/unavailable)"
                current_proxies_for_request = {}

            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=effective_headers,
                    timeout=self.request_timeout,
                    allow_redirects=True,
                    proxies=current_proxies_for_request # Explicitly pass proxies for this specific request call
                )
                response.raise_for_status()  # Raise HTTPError for bad responses (4XX or 5XX)
                return response # Success
            
            except (requests.exceptions.ConnectionError, ConnectTimeout, ReadTimeout, SSLError, ProxyError) as e: # Combined common connection/proxy errors
                self.logger.warning(f"Attempt {attempt + 1}/{self.max_attempts} with {log_proxy_info} failed: {type(e).__name__} - {e}")
                last_exception = e
                
                # If this was a direct attempt and it failed with a connection-related error, activate proxy usage for next time.
                if not attempt_with_proxy_activated and current_proxies_for_request is None and self.use_proxies and self.available_proxies:
                    if isinstance(e, requests.exceptions.ConnectionError) and "Max retries exceeded" in str(e):
                        self.logger.info(f"Direct attempt failed with 'Max retries exceeded'. Activating proxy usage for subsequent attempts.")
                        attempt_with_proxy_activated = True
                    elif isinstance(e, (ConnectTimeout, ReadTimeout)):
                        self.logger.info(f"Direct attempt failed with Timeout. Activating proxy usage for subsequent attempts.")
                        attempt_with_proxy_activated = True
                    elif isinstance(e, SSLError): # SSL errors might also be IP/network specific
                        self.logger.info(f"Direct attempt failed with SSLError. Activating proxy usage for subsequent attempts.")
                        attempt_with_proxy_activated = True
                    elif isinstance(e, ProxyError) and current_proxies_for_request is not None: # Should not happen if current_proxies_for_request is None
                         self.logger.warning("ProxyError received even when direct connection was intended. Check logic.")
                    # For a generic ConnectionError not matching "Max retries", we might also want to try proxies.
                    elif isinstance(e, requests.exceptions.ConnectionError):
                        self.logger.info(f"Direct attempt failed with general ConnectionError. Activating proxy usage for subsequent attempts.")
                        attempt_with_proxy_activated = True


                if attempt < self.max_attempts - 1:
                    self.logger.info(f"Continuing to attempt {attempt + 2}/{self.max_attempts}. Next will {'use proxy' if attempt_with_proxy_activated else 'be direct'}.")
                    continue 
                else:
                    self.logger.error(f"All {self.max_attempts} attempts failed. Last error ({type(e).__name__}) on {log_proxy_info}: {e}")
            
            except requests.exceptions.HTTPError as e:
                self.logger.warning(f"Attempt {attempt + 1}/{self.max_attempts} with {log_proxy_info} failed: HTTPError {e.response.status_code} {e.response.reason}")
                last_exception = e

                # If this was a direct attempt and it's a 403, activate proxy usage.
                if not attempt_with_proxy_activated and current_proxies_for_request is None and e.response.status_code == 403 and self.use_proxies and self.available_proxies:
                    self.logger.info(f"Direct attempt failed with HTTP 403. Activating proxy usage for subsequent attempts.")
                    attempt_with_proxy_activated = True
                
                # Retry for 429 (Too Many Requests) or 5xx server errors
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    if attempt < self.max_attempts - 1:
                        self.logger.info(f"HTTPError {e.response.status_code} is retryable. Continuing to attempt {attempt + 2}/{self.max_attempts}.")
                        attempt_with_proxy_activated = True
                        if attempt < self.max_attempts - 1:
                            self.logger.info(f"HTTPError {e.response.status_code} is retryable. Continuing to attempt {attempt + 2}/{self.max_attempts}.")
                            time.sleep(self.retry_delay_seconds * (1 + (e.response.status_code == 429))) # Slightly longer for 429
                            continue
                        else:
                            self.logger.error(f"All {self.max_attempts} attempts failed. Last HTTPError: {e.response.status_code}")
                    else:
                        self.logger.error(f"All {self.max_attempts} attempts failed. Last HTTPError: {e.response.status_code}")
                else:
                    # For other HTTP errors (e.g., 400, 401, non-403 on direct, 404), don't retry with this logic, return the response immediately.
                    self.logger.error(f"Non-retryable HTTPError {e.response.status_code} or unhandled HTTP error. Returning error response immediately.")
                    return e.response 
            
            except Exception as e: # Catch any other unexpected errors during the request
                self.logger.error(f"An unexpected error occurred on attempt {attempt + 1}/{self.max_attempts} for {url} with {log_proxy_info}: {type(e).__name__} - {e}", exc_info=True)
                last_exception = e
                # Activate proxies if direct attempt failed with unexpected error.
                if not attempt_with_proxy_activated and current_proxies_for_request is None and self.use_proxies and self.available_proxies:
                    self.logger.info(f"Direct attempt failed with unexpected error. Activating proxy usage for subsequent attempts.")
                    attempt_with_proxy_activated = True

                if attempt < self.max_attempts - 1:
                    self.logger.info(f"Continuing to attempt {attempt + 2}/{self.max_attempts} after unexpected error.")
                    continue
                else:
                    self.logger.error(f"All {self.max_attempts} attempts failed with unexpected error. Last error ({type(e).__name__}): {e}")

        # If loop finishes, all attempts failed.
        if last_exception: # If no HTTP response but an exception was caught
            self.logger.error(f"Request to {url} failed after {self.max_attempts} attempts. Last exception: {last_exception}")
        return None # All attempts failed

    def _get_xf_token(self, url_to_fetch_token_from=None):
        """
        Fetches the _xfToken (CSRF token) from a given F95Zone page.
        Usually fetched from the login page itself.
        """
        fetch_url = url_to_fetch_token_from or self.login_url
        self.logger.debug(f"Attempting to fetch CSRF token from {fetch_url}")
        
        response = self._make_request("GET", fetch_url) # Use new request method

        if response and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            token_element = soup.select_one(SEL_CSRF_TOKEN_INPUT)
            if token_element and token_element.get('value'):
                self._xf_token = token_element['value']
                self.logger.debug(f"CSRF token fetched: {self._xf_token}")
                return self._xf_token
            else:
                # If not found on specified page, try fetching from base_url as a fallback ONLY if not already trying base_url
                if fetch_url != self.base_url:
                    self.logger.debug(f"CSRF token not found on {fetch_url}, trying {self.base_url}")
                    return self._get_xf_token(url_to_fetch_token_from=self.base_url)
                self.logger.warning(f"Could not find _xfToken input element on {fetch_url} or {self.base_url}.")
                return None
        else:
            self.logger.error(f"Failed to fetch page {fetch_url} for CSRF token. Status: {response.status_code if response else 'No Response'}")
            return None

    def login(self, username, password):
        """
        Attempts to log in to F95Zone.
        username: F95Zone username.
        password: F95Zone password.
        Returns: A dictionary with 'success' (bool) and 'message' (str).
        """
        self.logger.info(f"Attempting login for user: {username}")
        self.is_logged_in = False 

        if not self._xf_token:
            self._get_xf_token() 

        if not self._xf_token: 
             return {'success': False, 'status_code': 'NO_CSRF_TOKEN', 'message': "Failed to retrieve CSRF token."}

        form_data = {
            'login': username,
            'password': password,
            '_xfToken': self._xf_token,
            'remember': '1',
            '_xfRedirect': self.base_url + "/", 
            'url': '', 
            'password_confirm': '',
            'additional_security': '',
            'website_code': ''
        }

        try:
            response = self.session.post(self.login_url, data=form_data)
            response.raise_for_status() 
            self.logger.debug(f"Login POST to {self.login_url} completed. Final URL: {response.url}")

            soup = BeautifulSoup(response.text, 'html.parser')

            if response.url.startswith(F95_LOGIN_2FA_URL):
                token_on_2fa_page = soup.select_one(SEL_CSRF_TOKEN_INPUT)
                if token_on_2fa_page and token_on_2fa_page.get('value'):
                    self._xf_token = token_on_2fa_page['value']
                self.logger.warning("Login requires 2FA.")
                return {'success': False, 'status_code': '2FA_REQUIRED', 'message': "Two-factor authentication is required."}

            error_banner = soup.select_one(SEL_LOGIN_ERROR_BANNER)
            if error_banner:
                error_text = error_banner.get_text(separator=" ", strip=True)
                self.logger.warning(f"Login failed with error banner: {error_text}")
                if MSG_INCORRECT_CREDENTIALS in error_text:
                    return {'success': False, 'status_code': 'INCORRECT_CREDENTIALS', 'message': MSG_INCORRECT_CREDENTIALS}
                if MSG_REQUIRE_CAPTCHA in error_text:
                    return {'success': False, 'status_code': 'CAPTCHA_REQUIRED', 'message': MSG_REQUIRE_CAPTCHA}
                return {'success': False, 'status_code': 'LOGIN_FAILED_BANNER', 'message': error_text}
            
            security_error_banner = soup.select_one("div.blockMessage") 
            if security_error_banner:
                error_text = security_error_banner.get_text(separator=" ", strip=True)
                if "Security error occurred." in error_text:
                    self._xf_token = None 
                    self.logger.error(f"Login failed with security error: {error_text}")
                    return {'success': False, 'status_code': 'SECURITY_ERROR_CSRF', 'message': error_text}

            user_id_span = soup.select_one(SEL_CURRENT_USER_ID_SPAN)
            if user_id_span and not response.url.startswith(self.login_url) and 'xf_user' in self.session.cookies:
                new_token_element = soup.select_one(SEL_CSRF_TOKEN_INPUT)
                if new_token_element and new_token_element.get('value'):
                    self._xf_token = new_token_element['value']
                self.logger.info(f"Login successful for user: {username}")
                self.is_logged_in = True
                return {'success': True, 'status_code': 'AUTH_SUCCESSFUL', 'message': MSG_AUTH_SUCCESSFUL}
            else:
                 self.is_logged_in = False 
                 return {'success': False, 'status_code': 'LOGIN_SUSPECTED_NO_COOKIE', 'message': "Login page indicates success, but session cookie not found."}

            if response.url.startswith(self.login_url):
                 self.logger.warning("Login failed: Still on login page with no clear error.")
                 self.is_logged_in = False
                 return {'success': False, 'status_code': 'STILL_ON_LOGIN_PAGE', 'message': "Login attempt failed, still on login page with no clear error."}
            
            self.is_logged_in = False
            return {'success': False, 'status_code': 'UNKNOWN_LOGIN_STATE', 'message': "Login status unknown after attempting."}

        except requests.RequestException as e:
            self.logger.error(f"Login request exception: {e}")
            self.is_logged_in = False
            return {'success': False, 'status_code': 'REQUEST_EXCEPTION', 'message': f"Login request failed: {e}"}

    def get_latest_game_data_from_rss(self, limit=60, search_term: str = None, completion_status_filter: str = None) -> list[dict]:
        """
        Fetches and parses game data from the F95Zone RSS feed using the new _make_request method.
        """
        base_rss_url = f"{self.base_url}/sam/latest_alpha/latest_data.php"
        url_params_dict = {'cmd': 'rss', 'cat': 'games', 'rows': str(limit)}

        if search_term:
            url_params_dict['search'] = search_term # requests will handle URL encoding of params
            self.logger.info(f"Fetching RSS feed with search term: '{search_term}', limit: {limit}")
        else:
            self.logger.info(f"Fetching RSS feed, limit: {limit}")

        prefix_params = []
        if completion_status_filter:
            if completion_status_filter == "completed":
                prefix_params.append(("prefixes[]", "18"))
                self.logger.info("Filtering RSS for: Completed games")
            elif completion_status_filter == "ongoing":
                prefix_params.append(("noprefixes[]", "18"))
                prefix_params.append(("noprefixes[]", "20")) 
                prefix_params.append(("noprefixes[]", "22")) 
                self.logger.info("Filtering RSS for: Ongoing games (not completed, on hold, or abandoned)")
            elif completion_status_filter == "on_hold":
                 prefix_params.append(("prefixes[]", "20"))
                 self.logger.info("Filtering RSS for: On Hold games")
            elif completion_status_filter == "abandoned":
                 prefix_params.append(("prefixes[]", "22"))
                 self.logger.info("Filtering RSS for: Abandoned games")
        
        # Construct query string manually for list-like parameters if requests encode them differently than expected
        # For "prefixes[]=18", requests typically encodes params={'prefixes[]': '18'} as prefixes%5B%5D=18
        # If multiple prefixes are needed, e.g. prefixes[]=18&prefixes[]=19
        # we can pass a list of tuples to params: params=[('prefixes[]', '18'), ('prefixes[]', '19')]
        
        final_url_params = list(url_params_dict.items()) + prefix_params
        
        # Log the fully constructed URL for debugging (urllib.parse.urlencode handles the list of tuples for params)
        debug_url = f"{base_rss_url}?{urllib.parse.urlencode(final_url_params)}"
        self.logger.debug(f"Constructed RSS request URL: {debug_url}")

        response = self._make_request("GET", base_rss_url, params=final_url_params)

        # If response is None (all retries failed) or not a 200 OK, return None to indicate failure.
        if response is None:
            self.logger.error(f"Failed to fetch RSS feed {debug_url} after all retries or due to an unexpected issue before sending the request.")
            return None # Explicitly return None for complete failure to fetch
        if response.status_code != 200:
            self.logger.error(f"Failed to fetch RSS feed {debug_url}. Status: {response.status_code}, Reason: {response.reason}")
            return None # Explicitly return None for non-200 responses

        parsed_items_data = []
        try:
            # Using feedparser for robust RSS parsing
            import feedparser
            feed = feedparser.parse(response.content) # Use response.content for feedparser
            self.logger.debug(f"Found {len(feed.entries)} items in the RSS feed response.")

            for item in feed.entries:
                game_data = {}
                title = item.get("title", "No Title")
                
                # Regex to extract name and version: ^\[(UPDATE|NEW)\]\s(.*?)\s\[([^\]]+)\]$
                # Example: [UPDATE] Game Name Here [v1.0 Final]
                # Example: [NEW] Another Game [0.5b]
                match = re.match(r"^\[(?:UPDATE|NEW|GAME)\]\s(.*?)(?:\s\[([^\]]+)\])?$", title.strip())
                if match:
                    game_data['name'] = match.group(1).strip()
                    game_data['version'] = match.group(2).strip() if match.group(2) else "Unknown"
                else:
                    # Fallback if primary regex fails (e.g. no [version] part, or different prefix)
                    name_match = re.match(r"^\[[^\]]+\]\s*(.*)", title.strip())
                    if name_match:
                        game_data['name'] = name_match.group(1).strip()
                    else:
                        game_data['name'] = title # Use full title if no structure matches
                    game_data['version'] = "Unknown" 
                
                self.logger.debug(f"RSS title parsed: Name='{game_data.get('name', 'N/A')}', Version='{game_data.get('version', 'N/A')}' from '{title}'")

                game_data['url'] = item.get("link")
                author_raw = item.get("author", "N/A") # Get raw author, default to N/A
                
                # Clean the author string
                author_cleaned = "N/A" # Default to N/A
                if author_raw and author_raw != "N/A":
                    # Use regex to remove <rss@f95> tag, ignoring case and allowing for surrounding whitespace
                    author_cleaned = re.sub(r'\s*<rss@f95>\s*', '', author_raw, flags=re.IGNORECASE).strip()
                
                game_data['author'] = author_cleaned if author_cleaned else "N/A" # Ensure it's N/A if empty after strip
                
                # F95Zone RSS uses 'published' for the date
                game_data['rss_pub_date'] = item.get("published") # Format: 'Sat, 18 May 2024 10:00:00 GMT'

                # Extract image URL from description HTML using regex
                image_url_rss = None
                if item.get("description", ""):
                    # More robust regex for src attribute, using hex escapes for quotes to avoid SyntaxError
                    img_match = re.search(r'<img[^>]+src\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', item.get("description", ""), re.IGNORECASE)
                    if img_match:
                        image_url_rss = img_match.group(1)
                
                game_data['image_url'] = image_url_rss # Changed key from image_url_rss to image_url

                # Ensure essential fields are present
                if game_data.get('name') and game_data.get('url'):
                    parsed_items_data.append(game_data)

        except Exception as e:
            self.logger.error(f"Error parsing RSS feed content: {e}")
            # If parsing fails after a successful fetch, this is different from fetch failure.
            # Returning empty list might be acceptable, or None if we want to signal this specific error too.
            # For now, let's keep it as [] for parsing errors post-successful fetch, to distinguish from total fetch failure.
            return [] # Return empty if parsing fails

        self.logger.info(f"Collected {len(parsed_items_data)} unique game data items from RSS processing.")
        
        # The 'limit' parameter is now handled by 'rows' in the RSS URL.
        # The _make_request and RSS server should respect this.
        # No client-side random sampling is done here anymore if search_term is not None.
        # If search_term is None, the RSS feed itself limits by 'rows'.
        
        if search_term:
            # If a specific search is performed, all unique results found (up to 'rows' limit) are returned.
            selected_items = parsed_items_data
            self.logger.info(f"Search term provided. Returning all {len(selected_items)} unique items found from RSS (respecting 'rows' limit).")
        else:
            # General feed fetching, 'rows' parameter in URL controls the limit.
            selected_items = parsed_items_data
            self.logger.info(f"Returning {len(selected_items)} game data items after processing (respecting 'rows' limit).")
        
        return selected_items

    # Removed get_handiwork_from_url method
    # Removed _parse_handiwork_page method
    # Removed search_handiwork and check_game_update as they were not implemented and rely on page parsing.
    # Kept get_game_details as a placeholder for now, though it's not used by the current test script.
    def get_game_details(self, game_id_or_url):
        """
        Placeholder for fetching game details. Currently not used if all data comes from RSS.
        """
        self.logger.info(f"Fetching details for {game_id_or_url} - Not implemented in RSS-only mode.")
        return None

    def close_session(self):
        """Closes the requests session."""
        self.session.close()
        self.logger.info("Requests session closed.")

# Need to import requests if it's used here directly
# import requests 