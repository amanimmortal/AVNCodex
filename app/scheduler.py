from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
from flask import current_app
from f95apiclient import F95ApiClient

from app.logging_config import logger
from app.database import get_primary_admin_user_id, get_setting
from app.services import scheduled_games_update_check

# Global scheduler instance
scheduler = BackgroundScheduler()

def shutdown_scheduler_politely():
    """Shuts down the scheduler if it's running."""
    if scheduler.running:
        logger.info("INFO_SCHEDULER: Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        logger.info("INFO_SCHEDULER: Scheduler shutdown complete.")

def run_scheduled_update_job(app):
    """
    The job function designed to be run by the scheduler.
    """
    with app.app_context(): # Ensure we have application context
        logger.info("--- Scheduled Job Started ---")
        
        # Check if we should run based on global settings
        db_path = app.config.get('DATABASE', 'f95_games.db') # Fallback if config not present
        
        primary_admin_id = get_primary_admin_user_id(db_path)
        if not primary_admin_id:
            logger.warning("Scheduled Update: No primary admin found. Skipping check.")
            return

        # Simple logic: Run the check. 
        # The complex "should we run now" logic based on time interval 
        # can be handled by the scheduler's trigger configuration itself, 
        # or we can keep the logic checks here if the interval is fixed (e.g. every hour) 
        # but we only want to act every X hours. 
        # For simplicity, assuming the scheduler trigger controls the frequency.
        
        local_f95_client = None
        try:
            local_f95_client = F95ApiClient()
            scheduled_games_update_check(db_path, local_f95_client)
        except Exception as e:
            logger.error(f"Scheduled Update Error: {e}", exc_info=True)
        finally:
            if local_f95_client:
                local_f95_client.close_session()
        
        logger.info("--- Scheduled Job Finished ---")

def start_or_reschedule_scheduler(app):
    """
    Starts or updates the scheduler with the correct interval from settings.
    Handles special values: '-5' for 5 minutes (testing), '-1' for disabled.
    """
    db_path = app.config.get('DATABASE', 'f95_games.db')
    
    with app.app_context():
        # Default to 6 hours if not set
        raw_val = "6"
        primary_admin = get_primary_admin_user_id(db_path)
        if primary_admin:
            val = get_setting(db_path, 'update_schedule_hours_global', user_id=primary_admin)
            if val:
                raw_val = val
                
        logger.info(f"INFO_SCHEDULER: Configuring scheduler with raw setting: {raw_val}")

        if not scheduler.running:
            scheduler.start()
            atexit.register(shutdown_scheduler_politely)
            logger.info("INFO_SCHEDULER: Scheduler started.")
        
        # Remove existing job to replace it
        if scheduler.get_job('game_update_job'):
            scheduler.remove_job('game_update_job')
            logger.info("INFO_SCHEDULER: Existing job removed for rescheduling.")
        
        # logic for special values
        try:
            int_val = int(raw_val)
        except ValueError:
            int_val = 6 # Default safe fallback
            
        if int_val == -1:
             logger.info("INFO_SCHEDULER: Schedule set to Manual Only (-1). No background job added.")
             return # Do not add job
        
        trigger = None
        if int_val == -5:
            logger.info("INFO_SCHEDULER: Schedule set to Testing Mode (Every 5 Minutes).")
            trigger = IntervalTrigger(minutes=5)
        elif int_val > 0:
            logger.info(f"INFO_SCHEDULER: Schedule set to Every {int_val} Hours.")
            trigger = IntervalTrigger(hours=int_val)
        else:
            logger.warning(f"INFO_SCHEDULER: Invalid schedule value {int_val}. Defaulting to 6 hours.")
            trigger = IntervalTrigger(hours=6)

        # Add the job
        scheduler.add_job(
            func=run_scheduled_update_job,
            trigger=trigger,
            id='game_update_job',
            name='Check for Game Updates',
            replace_existing=True,
            args=[app] # specific argument for the job function
        )
