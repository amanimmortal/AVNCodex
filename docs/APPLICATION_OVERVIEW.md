# YAM Application Documentation

## 1. Overview

YAM (Yet Another Manager/Modlist) is an application designed to help users track and manage games, primarily from the F95zone platform. It consists of a main component:

*   **Python Flask Backend**: A web server application that handles core data processing, interaction with the F95zone API (via its own Python client), database management (SQLite), and provides a web interface and potentially an API. This backend is designed to be run in a Docker container.

## 2. Python Flask Backend (`app.py`, `app/main.py`)

*   **Purpose**:
    *   Acts as the primary engine for fetching and processing game data from F95zone.
    *   Manages a central SQLite database (`/data/f95_games.db` in Docker) storing game information, user lists, and application settings.
    *   Provides user authentication and session management for its web interface.
    *   Includes a scheduler (APScheduler) for automatically checking for game updates in the background.
    *   Can send notifications (e.g., via Pushover).
*   **Core Modules**:
    *   `app.py`: The main Flask application file.
        *   Handles routing for web pages (login, registration, dashboard, game lists, settings, admin).
        *   Manages user sessions and authentication (`login_required` decorator).
        *   Initializes and manages the APScheduler for background tasks.
        *   Instantiates `F95ApiClient` (Python version) for some direct searches (though most heavy lifting seems to be in `app/main.py`).
    *   `app/main.py`: Contains the core business logic.
        *   Database schema initialization and helper functions for CRUD operations on `users`, `games`, `user_played_games`, and `app_settings` tables.
        *   Functions to interact with `f95apiclient` for fetching game data, processing RSS feeds, and checking game statuses.
        *   Logic for adding games to a user's list, marking updates, managing notifications.
        *   Scheduled job logic (`scheduled_games_update_check`).
        *   Setting management (get/set per user or globally).
    *   `f95apiclient/__init__.py`: Python client for F95zone.
        *   Handles login, 2FA, session management.
        *   Fetches and parses RSS feeds for game updates.
        *   Retrieves game details from game threads.
        *   Includes robust proxy support (HTTP/SOCKS5) with list fetching and rotation.
        *   Implements retry logic for network requests.
*   **Database (`f95_games.db`)**:
    *   `users`: Stores user credentials and admin status.
    *   `games`: Stores general information about games scraped from F95zone.
    *   `user_played_games`: Links users to games they play, stores user-specific notes, ratings, notification preferences, and acknowledged versions.
    *   `app_settings`: Stores application settings, potentially user-specific.
*   **Deployment**:
    *   Primarily via Docker (`Dockerfile`, `docker-compose.yml`, `docker-compose.windows.yml`).
    *   `Dockerfile` sets up a Python 3.9 environment, installs dependencies from `requirements.txt`, and runs `app.py`.
    *   Compose files manage port mapping (5000:5000) and persistent data volume (`/data`).
*   **Key Dependencies**: Flask, requests, beautifulsoup4, lxml, python-dotenv, SQLAlchemy (though direct sqlite3 usage is more prominent), psycopg2-binary, feedparser, PySocks, APScheduler, python-pushover2.

## 3. Getting Started for a New Developer

*   **Python Backend Development**:
    *   Set up a Python 3.9 environment.
    *   Install dependencies from `requirements.txt`.
    *   Familiarize yourself with Flask, APScheduler, and SQLite.
    *   To run: Use Docker with the provided `Dockerfile` and `docker-compose.yml` (or `docker-compose.windows.yml`). This will handle the environment and database paths.
    *   The main entry point for the server is `app.py`.
    *   Core logic is in `app/main.py` and `f95apiclient/`.
*   **Key Areas to Investigate**:
    *   Database strategy: Understand the SQLite usage and schema.
    *   API surface: Does the Python backend expose a formal API? The Flask routes in `app.py` primarily serve HTML templates.

## 4. Project Structure Highlights

*   `YAM/`
    *   `app.py`: Main Flask application (backend).
    *   `app/`: Contains modules for the backend.
        *   `main.py`: Core backend logic.
        *   `db/`:
            *   `schemas/`: Likely SQLite schema definitions or SQLAlchemy models (if used more deeply).
        *   `static/`: Static assets (JS, CSS, images) for Flask.
        *   `templates/`: HTML templates for Flask.
    *   `data/`: (In Docker/intended for runtime) Persistent storage for logs, SQLite DB.
    *   `f95apiclient/`: Python client for F95zone API.
    *   `Dockerfile`, `docker-compose*.yml`: Docker setup.
    *   `requirements.txt`: Python dependencies.
    *   `resources/`: Assets like fonts, images, language files. 