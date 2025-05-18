# F95 Game Updater (Web App)

A Python-based web application to check for game updates from F95Zone, intended to be run as a Docker container.

## Features (Planned)

- Check for game updates from F95Zone.
- Store game information in a database.
- Web interface to view games and update status.

## Project Structure

- `app.py`: Main Flask application.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: For building the Docker container.
- `f95apiclient/`: Python client for interacting with F95Zone (to be developed).
- `static/`: For static web assets (CSS, JS, images).
- `templates/`: For HTML templates (if server-side rendering is used).

## Running with Docker

1.  **Build the Docker image:**
    ```bash
    docker build -t f95updater-webapp .
    ```

2.  **Run the Docker container:**
    ```bash
    docker run -p 5000:5000 f95updater-webapp
    ```

The application will be accessible at `http://localhost:5000`.

## Development

1.  Create a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Run the Flask app:
    ```bash
    python app.py
    ```

## F95API Python Client

The core of this application will be a Python client that replicates the functionality of the original `@millenniumearl/f95api` (a Node.js library). This involves:

- Making HTTP requests to F95Zone.
- Parsing HTML content (web scraping) as F95Zone does not have an official public API.
- Handling login, session management, and potentially CAPTCHAs (this will be the most challenging part).
- Extracting game information, version details, and update statuses. 