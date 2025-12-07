import logging
import os
import sys

# --- Constants ---
# These might be better in a config file, but for now we keep them here or in a config module
# LOG_FILE_PATH = "/data/logs/update_checker.log" 
# Better to use an environment variable or a default relative path for portability
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "/data/logs/update_checker.log")

def setup_logging():
    """Configures logging for the application."""
    # Ensure log directory exists
    log_dir = os.path.dirname(LOG_FILE_PATH)
    # Check and create directory before basicConfig tries to open the file handler
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            # If logger isn't configured yet, a simple print might be necessary for this initial step
            print(f"Log directory created: {log_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create log directory {log_dir}. Error: {e}")
            # Decide on fallback or exit strategy if logging is critical
            # For now, allow to proceed, basicConfig might fail or log to current dir if path invalid.
    
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE_PATH, mode='a'), # Append to log file
            logging.StreamHandler() # Also print to console
        ]
    )
    # Silence excessively verbose loggers (e.g., urllib3)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger("AVNCodex") # Use a fixed name or __name__ if called from here

logger = setup_logging()
