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
*   **Scheduling**: APScheduler is used for background task scheduling (checking for game updates).
*   **Deployment**: Designed for Docker, but can also be run directly for development.

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

## Notes on F95Zone Interaction

*   This application relies on F95Zone's RSS feeds. Changes to their site structure or RSS feed availability can break functionality.
*   The `F95APIClient` includes mechanisms to cycle through public proxies to improve request success rates, as direct requests can be rate-limited or blocked. The reliability of these public proxies can vary.
*   No direct web scraping of HTML pages for game data is performed by default for update checks; it primarily uses structured RSS data. 