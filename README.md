# AVN Codex (for F95Zone Game Updates)

AVN Codex is a Python/Flask application designed to track and check for game updates from F95Zone.

## Overview

The application is a Python-based web application built with the Flask framework. It features its own F95Zone API client (`f95apiclient`), uses an SQLite database for data persistence, and handles scheduled update checks and notifications.

This README details the Python Flask application components, which can be developed or run independently in a Docker environment.

## Core Features

*   **User Accounts**: Supports multiple users with individual game lists and notification settings (managed via its web interface).
*   **Game List Management**:
    *   Search for games on F95Zone via its RSS feed.
    *   Add games to a personal monitoring list.
    *   Edit user-specific details (notes, rating).
    *   Delete games from the list.
*   **Automated Update Checking**:
    *   Regularly checks for updates to games in users' lists.
    *   Identifies changes in game version, RSS publication date, and completion status (Ongoing, Completed, On-Hold, Abandoned).
    *   The scheduler intelligently skips checks if a recent check has been performed within the configured interval, even across application restarts.
*   **Notifications**:
    *   Sends notifications via Pushover for game updates and status changes.
    *   Users can configure their Pushover User Key and API Token.
    *   Granular control over which events trigger notifications (e.g., game added, version update, status change to completed).
*   **Update Acknowledgment**: Users can acknowledge updates, hiding the notification until a new update is found.
*   **Manual Sync**: Option to manually trigger an update check for a single game or all games in a user's list.
*   **Admin Interface**: Basic user management for administrators.
*   **Web Interface**: Built with Flask, providing a UI to manage games, view updates, and configure settings.

## Technical Overview

*   **Backend**: Python (Flask framework).
*   **Database**: SQLite (`f95_games.db`) for storing user data, game information, and application settings.
*   **F95Zone Interaction**: Uses a custom Python client (`f95apiclient/`) to fetch game data primarily via F95Zone's RSS feeds.
    *   The client can search by game name and filter by completion status.
    *   It includes basic proxy support to help with request reliability.
    *   The application is configured to request a larger number of items (90) from RSS feeds where possible, as F95Zone's RSS `rows` parameter defaults to a smaller number (30) if an unsupported value is provided. This aims to improve the comprehensiveness of search results and status checks.
*   **Scheduling**: APScheduler is used for background task scheduling (checking for game updates).
*   **Deployment**: The Python application is designed for Docker, but can also be run directly for development.

## Core Logic (`app/main.py`)

The `app/main.py` module is the heart of the application's backend logic. Key functionalities include:

*   **Database Management**:
    *   `initialize_database()`: Sets up the SQLite database schema, including tables for `users`, `games` (master list of game details), `user_played_games` (user-specific game tracking, notes, ratings, notification states), and `app_settings` (user-specific and global configurations). It also handles schema migrations for adding new columns to existing tables.
    *   Functions for CRUD operations on these tables (e.g., `get_user_by_id`, `add_game_to_my_list`, `get_setting`, `set_setting`).
*   **Game Information & Update Processing**:
    *   `process_rss_feed()`: Periodically fetches the latest game data from F95Zone's general RSS feed to update the central `games` table with new game entries or update information for existing ones (like version, author, RSS publication date). (Note: Review of `app.main.py` suggests this global periodic task might be deprecated in favor of on-demand updates).
    *   `update_completion_statuses()`: Checks specific F95Zone RSS feeds (e.g., "completed games") to update the `completed_status` field in the `games` table (e.g., to 'COMPLETED', 'ABANDONED', 'ON_HOLD', or 'ONGOING').
    *   `get_first_significant_word()`: A text processing helper to extract a meaningful search term from a game's name for more accurate RSS feed searching.
*   **User-Specific Game Monitoring & Notifications**:
    *   `check_for_my_updates()`: For a given user, compares the current game details in the `games` table against the `last_notified_version`, `last_notified_rss_pub_date`, and `last_notified_completion_status` stored in `user_played_games` to identify new updates.
    *   `update_last_notified_status()`: Updates these "last notified" fields after a notification has been processed for a user.
    *   `mark_game_as_acknowledged()`: Allows users to "acknowledge" an update. This copies the current game state (version, RSS date, completion status) from `games` to `user_acknowledged_version`, `user_acknowledged_rss_pub_date`, and `user_acknowledged_completion_status` in `user_played_games`. Notifications for this game are suppressed until a new, unacknowledged change occurs.
    *   `send_pushover_notification()`: Handles the sending of notifications via the Pushover service, using user-configured keys.
*   **Scheduled Tasks & Manual Sync**:
    *   `check_single_game_update_and_status()`: The core function for checking a specific game for a specific user. It fetches the latest data, determines if there are updates or status changes, updates the `games` table, and triggers notifications.
    *   `scheduled_games_update_check()`: Called by the APScheduler, this iterates through all users and their tracked games (that are eligible for checks) and calls `check_single_game_update_and_status()` for each.
    *   `sync_all_my_games_for_user()`: Allows a user to manually trigger `check_single_game_update_and_status()` for all their relevant games.

## Database Schema Overview (SQLite)

The application uses an SQLite database (`f95_games.db`) with the following main tables:

*   **`users`**: Stores user credentials (hashed passwords) and admin status.
    *   `id`, `username`, `password_hash`, `is_admin`, `created_at`
*   **`games`**: A central catalog of game information fetched from F95Zone.
    *   `id`, `f95_url` (unique), `name`, `version`, `author`, `image_url`, `rss_pub_date`, `completed_status`, `first_added_to_db`, `last_seen_on_rss`, `last_updated_in_db`, `last_checked_at`
*   **`user_played_games`**: Links users to games they are tracking and stores user-specific data.
    *   `id`, `user_id` (FK to `users`), `game_id` (FK to `games`), `user_notes`, `user_rating`, `notify_for_updates`
    *   `last_notified_version`, `last_notified_rss_pub_date`, `last_notified_completion_status` (tracks the state for which the last notification was sent)
    *   `user_acknowledged_version`, `user_acknowledged_rss_pub_date`, `user_acknowledged_completion_status` (tracks the state acknowledged by the user)
*   **`app_settings`**: Stores application settings, both global (associated with the primary admin user) and user-specific.
    *   `user_id` (FK to `users`), `setting_key`, `setting_value` (e.g., Pushover keys, notification preferences, global update schedule).

## Project Structure

*   `app.py`: Main Flask application entry point.
*   `app/main.py`: Contains core application logic (database interactions, game update checking, notification functions).
*   `f95apiclient/`: Python client for interacting with F95Zone RSS feeds.
*   `app/templates/`: HTML templates for the Flask web interface.
*   `app/static/`: Static web assets (CSS, JavaScript) for the Flask web interface.
*   `requirements.txt`: Python dependencies.
*   `Dockerfile`: For building a Docker image of the application.
*   `docker-compose.yml` / `docker-compose.windows.yml`: For easier Docker deployment.
*   `/data/`: (Inside Docker container, or locally) Default path for `f95_games.db` (database) and `logs/`.
*   `resources/`: Assets like fonts, images, language files, potentially used by the Flask application.

## Configuration

*   **Pushover**: API and User keys are configured per-user via the web UI's settings page.
*   **Update Schedule**: The interval for game update checks is configurable globally by an admin user via the settings page (e.g., every 12 hours, 24 hours, or manually).

## Running the Application

### Python Application via Docker

1.  **Prerequisites**: Docker and Docker Compose installed.
2.  **Build and Run**:
    *   For Linux/macOS:
        ```bash
        docker-compose up --build -d
        ```
    *   For Windows:
        ```bash
        docker-compose -f docker-compose.windows.yml up --build -d
        ```
3.  The application will be accessible at `http://localhost:5000`. The first user to register becomes an admin.
4.  **Logs**: View container logs using `docker-compose logs -f`.
5.  **Stopping**:
    ```bash
    docker-compose down
    ```

### Local Development

For a detailed step-by-step guide for Windows, please see [LOCAL_SETUP.md](LOCAL_SETUP.md).

**Quick Summary**:
1.  Install dependencies: `pip install -r requirements.txt`
2.  Install Playwright: `playwright install chromium`
3.  Run the application: `python run_app.py`


## Troubleshooting

*   **No updates found/Pushover issues**:
    *   Check the application logs: `docker-compose logs -f` (for Docker) or console output (for local).
    *   Verify Pushover User Key and API Token are correctly entered in the web UI settings.
    *   Ensure the F95Zone RSS feeds are accessible. The application uses proxies, but their reliability can vary.
    *   Check the "Update Schedule" in settings. If set to "Manual Only", automatic checks will not run.
*   **Database Errors**:
    *   Ensure the `/data/` directory (or its equivalent if customized) is writable by the application.
    *   If you encounter schema-related errors after an update, the `initialize_database()` function attempts to perform basic migrations (like adding columns). For major schema changes, manual intervention might be rarely needed.
*   **"Too Many Requests" or similar errors from F95Zone**:
    *   The `F95APIClient` attempts to use proxies to mitigate this. However, F95Zone may still temporarily block access if requests are too frequent or aggressive. The scheduler interval should be set to a reasonable value (e.g., several hours).
*   **Database Errors (Python Application)**:
    *   Ensure the `/data/` directory (or its equivalent if customized) is writable by the application.
    *   If you encounter schema-related errors after an update, the `initialize_database()` function attempts to perform basic migrations (like adding columns). For major schema changes, manual intervention might be rarely needed.

## Notes on F95Zone Interaction

This application relies on F95Zone's RSS feeds and site structure. Changes to F95Zone can break functionality.

*   **Python Client (`f95apiclient/`)**:
    *   Uses F95Zone's RSS feeds.
    *   The F95Zone RSS feeds have a parameter (often referred to as `rows` or similar, corresponding to `limit` in the `F95APIClient`) that controls the number of results. While the API might accept various values, it typically defaults to 30 items if an unsupported number is requested. The application now attempts to use a limit of 90 items for its RSS queries to maximize the data retrieved in a single request.
    *   The `F95APIClient` includes mechanisms to cycle through public proxies to improve request success rates, as direct requests can be rate-limited or blocked. The reliability of these public proxies can vary.
    *   No direct web scraping of HTML pages for game data is performed by default for update checks; it primarily uses structured RSS data.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details. 