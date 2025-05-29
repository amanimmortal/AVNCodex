# YAM - Yet Another Monitor (for F95Zone Game Updates)

A Python-based web application to track and check for game updates from F95Zone. It is designed to be run as a Docker container or locally for development.

## Core Features

*   **User Accounts**: Supports multiple users with individual game lists and notification settings.
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
*   **Database**: SQLite for storing user data, game information, and application settings.
*   **F95Zone Interaction**: Uses a custom `F95APIClient` to fetch game data primarily via F95Zone's RSS feeds.
    *   The client can search by game name and filter by completion status.
    *   It includes basic proxy support to help with request reliability.
    *   The application is configured to request a larger number of items (90) from RSS feeds where possible, as F95Zone's RSS `rows` parameter defaults to a smaller number (30) if an unsupported value is provided. This aims to improve the comprehensiveness of search results and status checks.
*   **Scheduling**: APScheduler is used for background task scheduling (checking for game updates).
*   **Deployment**: Designed for Docker, but can also be run directly for development.

## Core Logic (`app/main.py`)

The `app/main.py` module is the heart of the application's backend logic. Key functionalities include:

*   **Database Management**:
    *   `initialize_database()`: Sets up the SQLite database schema, including tables for `users`, `games` (master list of game details), `user_played_games` (user-specific game tracking, notes, ratings, notification states), and `app_settings` (user-specific and global configurations). It also handles schema migrations for adding new columns to existing tables.
    *   Functions for CRUD operations on these tables (e.g., `get_user_by_id`, `add_game_to_my_list`, `get_setting`, `set_setting`).
*   **Game Information & Update Processing**:
    *   `process_rss_feed()`: Periodically fetches the latest game data from F95Zone's general RSS feed to update the central `games` table with new game entries or update information for existing ones (like version, author, RSS publication date).
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

## Database Schema Overview

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

*   `app.py`: Main Flask application entry point, handles routing, user sessions, and initializes the scheduler.
*   `app/main.py`: Contains core application logic, database interactions, game update checking, and notification functions.
*   `f95apiclient/`: Python client for interacting with F95Zone RSS feeds.
*   `app/templates/`: HTML templates for the web interface.
*   `app/static/`: Static web assets (CSS, JavaScript).
*   `requirements.txt`: Python dependencies.
*   `Dockerfile`: For building the Docker image.
*   `docker-compose.yml` / `docker-compose.windows.yml`: For easier Docker deployment.
*   `/data/`: (Inside Docker container, or locally) Default path for `f95_games.db` (database) and `logs/`.

## Configuration

*   **Pushover**: API and User keys are configured per-user via the web UI's settings page.
*   **Update Schedule**: The interval for game update checks is configurable globally by an admin user via the settings page (e.g., every 12 hours, 24 hours, or manually).

## Running the Application

### Using Docker (Recommended)

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
3.  The application will typically be accessible at `http://localhost:5000`.
4.  **Logs**: View container logs using `docker-compose logs -f`.
5.  **Stopping**:
    ```bash
    docker-compose down
    ```

### Local Development

1.  **Prerequisites**: Python 3.x.
2.  **Create a virtual environment** (recommended):
    ```bash
    python -m venv .venv
    # On Linux/macOS:
    source .venv/bin/activate
    # On Windows (PowerShell):
    .venv\Scripts\Activate.ps1
    # On Windows (CMD):
    .venv\Scripts\activate.bat
    ```
3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Create a `data` directory** in the project root if it doesn't exist (for the SQLite database and logs):
    ```bash
    mkdir data
    mkdir data/logs 
    ```
    *Note: The application (`app/main.py`) is configured to place the database and logs in `/data/` by default. For local development without Docker, ensure this path is writable or adjust `DB_PATH` and `LOG_FILE_PATH` in `app/main.py` if necessary.*
5.  **Run the Flask application**:
    ```bash
    python app.py
    ```
6.  The application will be accessible at `http://localhost:5000` (or as configured). The first user to register becomes an admin.

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

## Notes on F95Zone Interaction

*   This application relies on F95Zone's RSS feeds. Changes to their site structure or RSS feed availability can break functionality.
*   The F95Zone RSS feeds have a parameter (often referred to as `rows` or similar, corresponding to `limit` in the `F95APIClient`) that controls the number of results. While the API might accept various values, it typically defaults to 30 items if an unsupported number is requested. The application now attempts to use a limit of 90 items for its RSS queries to maximize the data retrieved in a single request.
*   The `F95APIClient` includes mechanisms to cycle through public proxies to improve request success rates, as direct requests can be rate-limited or blocked. The reliability of these public proxies can vary.
*   No direct web scraping of HTML pages for game data is performed by default for update checks; it primarily uses structured RSS data. 

## License

This project is licensed under the MIT License. See the `LICENSE` file for details. 