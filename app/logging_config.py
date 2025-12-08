import logging
import os
import sys

from logging.handlers import RotatingFileHandler

# --- Constants ---
# Default to a local 'logs' directory if not specified
DEFAULT_LOG_PATH = os.path.join(os.getcwd(), "logs", "update_checker.log")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", DEFAULT_LOG_PATH)

def setup_logging():
    """Configures logging for the application with rotation."""
    # Ensure log directory exists
    log_dir = os.path.dirname(os.path.abspath(LOG_FILE_PATH))
    
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"Log directory created: {log_dir}") 
        except OSError as e:
            print(f"Critical error: Could not create log directory {log_dir}. Error: {e}")
            # Continue, handlers might fail or just output to console
            
    # Create a custom logger
    logger = logging.getLogger("AVNCodex")
    logger.setLevel(logging.INFO)
    
    # Avoid adding handlers multiple times if function is called repeatedly
    if not logger.handlers:
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s')

        # File Handler (Rotating)
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE_PATH, 
                maxBytes=5*1024*1024, # 5 MB
                backupCount=5,
                encoding='utf-8',
                delay=False
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Failed to set up file logging: {e}")

        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Silence excessively verbose loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING) # Optional: quiet flask dev server request logs if too noisy
    
    return logger

logger = setup_logging()
