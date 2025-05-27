# YAM Application Documentation

## 1. Overview

YAM (Yet Another Manager/Modlist) is an application designed to help users track and manage games, primarily from the F95zone platform. It consists of two main components:

*   **Python Flask Backend**: A web server application that handles core data processing, interaction with the F95zone API (via its own Python client), database management (SQLite), and provides a web interface and potentially an API. This backend is designed to be run in a Docker container.
*   **Electron Desktop Application**: A cross-platform desktop client (Windows, macOS, Linux) that provides a rich user interface for managing games. It has its own F95zone API client (JavaScript-based) and uses local NeDB databases for storing its data. It includes features like game update notifications, a recommendation engine, and internationalization.

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

## 3. Electron Desktop Application (`app/app.js`, `app/src/`)

*   **Purpose**:
    *   Provides a user-friendly desktop interface for interacting with the YAM system.
    *   Allows users to browse, search, and manage their game library.
    *   Fetches data directly from F95zone using its own JavaScript API client.
    *   Manages its own local data stores (NeDB) for caching and client-specific information.
    *   Handles automatic application updates.
    *   Offers features like game recommendations.
*   **Core Modules**:
    *   `app/app.js`: The Electron main process.
        *   Manages application lifecycle, windows, and global state.
        *   Handles IPC communication with renderer processes (UI).
        *   Integrates auto-updater (`electron-updater`).
        *   Manages user settings via `electron-store`.
        *   Provides access to F95zone API functions via `F95Wrapper` and IPC.
        *   Manages NeDB database operations via IPC.
    *   `app/src/scripts/f95wrapper.js`: Wrapper around the `@millenniumearl/f95api` (JavaScript F95zone client).
    *   `app/db/stores/`: Contains `GameDataStore.js` and `ThreadDataStore.js` which are NeDB-based data stores for game and thread information.
    *   `app/src/scripts/window-creator.js`: Manages creation of different application windows.
    *   `app/src/scripts/localization.js`: Handles internationalization.
    *   `app/src/scripts/classes/`: Contains data model classes like `GameInfoExtended`, `ThreadInfo`, and the `RecommendationEngine`.
    *   Renderer process code (HTML, CSS, JS for UI) is expected to be in `app/src/components/`, `app/static/`, or `app/templates/` (though `templates` are typically for Flask, the structure might be mixed or some parts are for Electron's HTML views).
*   **Local Databases (NeDB)**:
    *   `gameStore` (`game-data.db`): Stores game data specific to the Electron client.
    *   `threadStore` (`thread-data.db`): Stores F95zone thread data.
    *   `updateStore` (`update-data.db`): Likely stores information about available updates for games tracked by the client.
*   **Key Dependencies**: Electron, electron-builder, electron-updater, electron-log, electron-store, @materializecss/materialize, @millenniumearl/f95api, i18next, nedb-promises.
*   **Build Process**:
    *   `package.json` defines scripts (`dist:win`, `dist:mac`, `dist:linux`) using `electron-builder` to create distributable packages.
    *   Build configuration in `package.json` specifies app ID, icons, files to include/exclude, etc.

## 4. Interaction between Backend and Frontend

*   The Python backend and Electron frontend can operate somewhat independently due to both having F95zone API clients.
*   **Scenario 1: Electron app is primary**: Users interact mainly with the Electron app. The Electron app uses its JS F95API client to fetch data and manages its NeDB databases. The Python backend might not be directly used by the Electron app in this mode, or only for specific fallback/auxiliary functions not yet identified.
*   **Scenario 2: Python backend as a server/API**: The Python backend (running in Docker) could serve a web interface accessible via a browser. It's possible the Electron app could also be configured to communicate with an API exposed by this Python backend, but this is not evident from `app/app.js`, which seems to favor direct F95 API calls.
*   **Data Synchronization**: It's unclear if there's any direct synchronization mechanism between the SQLite database of the Python backend and the NeDB databases of the Electron frontend. They might be managing parallel sets of data. If a user uses both (e.g., web interface via Docker and the desktop app), their lists and settings might not be automatically synced unless there's an API layer facilitating this. *This is a key area for further investigation for a developer.*

## 5. Getting Started for a New Developer

*   **Understanding the Dual Nature**: Recognize that there are two semi-distinct parts: the Python/Flask server and the Electron desktop app.
*   **Python Backend Development**:
    *   Set up a Python 3.9 environment.
    *   Install dependencies from `requirements.txt`.
    *   Familiarize yourself with Flask, APScheduler, and SQLite.
    *   To run: Use Docker with the provided `Dockerfile` and `docker-compose.yml` (or `docker-compose.windows.yml`). This will handle the environment and database paths.
    *   The main entry point for the server is `app.py`.
    *   Core logic is in `app/main.py` and `f95apiclient/`.
*   **Electron App Development**:
    *   Set up Node.js (version >=14.10 as per `package.json`).
    *   Run `npm install` in the project root to install dependencies from `package.json`.
    *   Familiarize yourself with Electron's main vs. renderer process architecture, IPC, and NeDB.
    *   The main entry point is `app/app.js`.
    *   UI components are likely in `app/src/` (HTML/JS/CSS for renderer processes).
    *   To run in development: Typically `npm start` or a similar script (if defined in `package.json`, though not explicitly shown, `electron .` is a common way).
    *   To build: Use `npm run dist:win/mac/linux`.
*   **Key Areas to Investigate**:
    *   The exact flow of data: When does the Electron app use its own F95 client vs. potentially communicating with the Python backend (if at all)?
    *   Database strategy: Why the separate SQLite (backend) and NeDB (frontend) databases? Is there any intended synchronization?
    *   API surface: Does the Python backend expose a formal API for the Electron client or other services? The Flask routes in `app.py` primarily serve HTML templates.
    *   UI code for Electron: Delve into `app/src/components/`, `app/static/js/`, and HTML files to understand how the renderer processes are built and how they use the IPC channels exposed by `app/app.js`.

## 6. Project Structure Highlights

*   `YAM/`
    *   `app.py`: Main Flask application (backend).
    *   `app/`: Contains modules for both backend and frontend.
        *   `main.py`: Core backend logic.
        *   `app.js`: Main Electron process (frontend).
        *   `db/`:
            *   `schemas/`: Likely SQLite schema definitions or SQLAlchemy models (if used more deeply).
            *   `stores/`: NeDB store definitions for Electron (`GameDataStore.js`, `ThreadDataStore.js`).
        *   `electron/`: Likely contains Electron-specific UI or utility modules (e.g., for different windows like login, messagebox).
        *   `src/`:
            *   `components/`: Likely UI components for the Electron app.
            *   `scripts/`: Helper scripts for Electron (main and renderer).
                *   `classes/`: Data model classes for Electron.
            *   `styles/`: CSS styles.
        *   `static/`: Static assets (JS, CSS, images) for Flask and/or Electron.
        *   `templates/`: HTML templates (primarily for Flask, but Electron might also load HTML files from here or `app/src/`).
    *   `data/`: (In Docker/intended for runtime) Persistent storage for logs, SQLite DB.
    *   `f95apiclient/`: Python client for F95zone API.
    *   `Dockerfile`, `docker-compose*.yml`: Docker setup.
    *   `package.json`: Node.js dependencies and Electron build configuration.
    *   `requirements.txt`: Python dependencies.
    *   `resources/`: Assets like fonts, images, language files. 