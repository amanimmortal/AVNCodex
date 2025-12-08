# Local Setup Guide for Windows

This guide will help you set up and run AVNCodex locally on your Windows machine.

## Prerequisites

1.  **Python 3.8 or higher**: Download from [python.org](https://www.python.org/downloads/). Ensure you check "Add Python to PATH" during installation.
2.  **Git**: Download from [git-scm.com](https://git-scm.com/downloads).

## Installation

1.  **Open PowerShell or Command Prompt** and navigate to the project directory:
    ```powershell
    cd d:\GitHub\AVNCodex
    ```

2.  **Create a Virtual Environment** (Recommended to keep dependencies isolated):
    ```powershell
    python -m venv venv
    ```

3.  **Activate the Virtual Environment**:
    ```powershell
    .\venv\Scripts\Activate.ps1
    ```
    *Note: If you get a permission error, run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` in PowerShell.*

4.  **Install Python Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```

5.  **Install Playwright Browsers**:
    The application uses Playwright for web scraping. You need to install the browser binaries:
    ```powershell
    playwright install chromium
    ```

## Configuration

1.  **Environment Variables (Optional)**:
    You can create a `.env` file in the root directory to customize settings.
    ```properties
    # .env
    FLASK_SECRET_KEY=your-super-secret-key-change-me
    # Defaults to data/f95_games.db if not set
    # DATABASE_PATH=data/f95_games.db 
    ```

2.  **Directories**:
    Ensure the `data` directory exists for the database and logs. The application will try to create them, but it's good to double-check.
    ```powershell
    if (!(Test-Path -Path "data")) { New-Item -ItemType Directory -Path "data" }
    if (!(Test-Path -Path "data/logs")) { New-Item -ItemType Directory -Path "data/logs" }
    ```

## Running the Application

1.  **Start the Server**:
    With your virtual environment activated, run:
    ```powershell
    python run_app.py
    ```

2.  **Access the App**:
    Open your web browser and navigate to:
    [http://localhost:5000](http://localhost:5000)

3.  **Initial Login**:
    If this is a fresh install, an admin user will be created automatically.
    - **Username**: `admin`
    - **Password**: `admin`
    **IMPORTANT**: Change this password immediately after logging in!

## Common Issues

-   **Updates stuck/failing**: Make sure you have a stable internet connection. F95Zone can sometimes block requests; if so, try again later or adjust the update schedule.
-   **Missing Modules**: If you see errors about missing modules (e.g., `ModuleNotFoundError: No module named 'apscheduler'`), ensure you have activated your virtual environment (`.\venv\Scripts\Activate.ps1`) and run `pip install -r requirements.txt` again.
