import sys
import os
import sqlite3
import logging # Added for scheduler logging
import atexit # Added for scheduler shutdown

# Add project root to sys.path to allow importing f95apiclient and app.main
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '.')) # app.py is in root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template, request, redirect, url_for, flash
from f95apiclient import F95ApiClient
from app.main import (
    DB_PATH,
    get_my_played_games, 
    check_for_my_updates,
    add_game_to_my_list, # Correctly import add_game_to_my_list from app.main
    delete_game_from_my_list, # Added
    mark_game_as_acknowledged, # Added
    update_last_notified_status, # Make sure this is available if we re-enable notification clearing
    initialize_database, # Added for auto-initialization
    get_my_played_game_details, # Added for editing
    update_my_played_game_details, # Added for editing
    get_setting, # Added for settings page
    set_setting, # Added for settings page
    # We'll need more functions from app.main later:
    # search_games_for_user, 
    scheduled_games_update_check, # Import the new scheduled task function
    check_single_game_update_and_status, # Added for manual sync
)

# APScheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

flask_app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
flask_app.secret_key = os.urandom(24) # Needed for flash messages

# Configure Flask app logger for APScheduler too
# If not already configured, APScheduler might use its own default
if not flask_app.debug:
    # In production, you might want more sophisticated logging
    # For now, ensure basic logging is available for scheduler messages
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    flask_app.logger.addHandler(stream_handler)
    flask_app.logger.setLevel(logging.INFO)
    # Also configure root logger for APScheduler if its logs are not appearing
    # logging.basicConfig(level=logging.INFO) # Uncomment if scheduler logs are missing

# Instantiate the F95ApiClient globally
# This client is used for searching, not for the main data processing which app.main.py handles
# If app.main.py is run separately, it uses its own client instance.
f95_client = F95ApiClient() 

# --- APScheduler Setup ---
scheduler = BackgroundScheduler(daemon=True)
scheduler.app = flask_app # Give scheduler access to app context if needed by jobs directly
scheduler_job_id = "f95_update_check_job"

def run_scheduled_update_job():
    # Use app_context for database connections, config, logging etc.
    with scheduler.app.app_context():
        flask_app.logger.info("APScheduler: Triggering scheduled games update check...")
        try:
            # DB_PATH is from app.main, f95_client is global in app.py
            scheduled_games_update_check(DB_PATH, f95_client)
            flask_app.logger.info("APScheduler: Scheduled job run completed.")
        except Exception as e:
            flask_app.logger.error(f"APScheduler: Error during scheduled job execution: {e}", exc_info=True)

def start_or_reschedule_scheduler(app_instance):
    global scheduler # Ensure we are referring to the global scheduler instance
    with app_instance.app_context():
        current_schedule_hours_str = get_setting(DB_PATH, 'update_schedule_hours', default_value='24')
        try:
            update_hours = int(current_schedule_hours_str)
            if update_hours <= 0: # -1 or 0 means manual, so don't schedule
                flask_app.logger.info(f"Scheduler: Update interval is {update_hours} hours (Manual). Job will be removed if exists.")
                try:
                    if scheduler.get_job(scheduler_job_id):
                        scheduler.remove_job(scheduler_job_id)
                        flask_app.logger.info(f"Scheduler: Removed job '{scheduler_job_id}'.")
                except JobLookupError:
                    flask_app.logger.info(f"Scheduler: Job '{scheduler_job_id}' not found, nothing to remove for manual schedule.")
                if scheduler.running:
                     # If scheduler is running but no jobs, it can be left running or paused/stopped.
                     # For simplicity, leave it running; it won't consume resources without jobs.
                     pass # flask_app.logger.info("Scheduler running but no jobs scheduled.")
                return # Do not proceed to add or start if manual

        except ValueError:
            flask_app.logger.error(f"Scheduler: Could not parse update_schedule_hours: '{current_schedule_hours_str}'. Scheduler not started/updated.")
            return

        # If scheduler is not running, start it.
        if not scheduler.running:
            try:
                scheduler.start()
                flask_app.logger.info("Scheduler started.")
                atexit.register(lambda: scheduler.shutdown())
            except Exception as e: # Catch specific exceptions if possible, e.g. if already started in a race condition
                flask_app.logger.error(f"Scheduler: Failed to start: {e}", exc_info=True)
                return # Can't proceed if scheduler won't start
        
        # Scheduler is running (or just started), try to add/reschedule the job
        try:
            existing_job = scheduler.get_job(scheduler_job_id)
            if existing_job:
                scheduler.reschedule_job(scheduler_job_id, trigger=IntervalTrigger(hours=update_hours))
                flask_app.logger.info(f"Scheduler: Rescheduled job '{scheduler_job_id}' to run every {update_hours} hours.")
            else:
                scheduler.add_job(
                    func=run_scheduled_update_job,
                    trigger=IntervalTrigger(hours=update_hours),
                    id=scheduler_job_id,
                    name='F95Zone Game Update Check',
                    replace_existing=True # Should be redundant if we check get_job first, but safe
                )
                flask_app.logger.info(f"Scheduler: Added job '{scheduler_job_id}' to run every {update_hours} hours.")
        except Exception as e:
            flask_app.logger.error(f"Scheduler: Error adding/rescheduling job '{scheduler_job_id}': {e}", exc_info=True)

@flask_app.route('/')
def index():
    # Get filter and sort parameters from request.args
    name_filter = request.args.get('name_filter', None)
    min_rating_str = request.args.get('min_rating_filter', None)
    sort_by = request.args.get('sort_by', 'name') # Default sort by name
    sort_order = request.args.get('sort_order', 'ASC') # Default sort order ASC

    min_rating_filter = None
    if min_rating_str and min_rating_str != 'any': # 'any' will be option for no rating filter
        try:
            min_rating_filter = float(min_rating_str)
        except ValueError:
            flash(f'Invalid minimum rating value \'{min_rating_str}\' ignored.', 'warning')
            min_rating_filter = None

    played_games = get_my_played_games(
        DB_PATH,
        name_filter=name_filter,
        min_rating_filter=min_rating_filter,
        sort_by=sort_by,
        sort_order=sort_order
    )
    notifications = check_for_my_updates(DB_PATH) # This identifies notifications

    # Check for Pushover configuration
    pushover_user_key = get_setting(DB_PATH, 'pushover_user_key')
    pushover_api_key = get_setting(DB_PATH, 'pushover_api_key')
    pushover_config_missing = not (pushover_user_key and pushover_api_key)

    # For now, notifications will re-appear until we have a mechanism to "clear" them
    # and call update_last_notified_status.
    
    # We could potentially sort notifications to show newly_completed ones first
    # or group them by type.
    
    # Pass current filter/sort values to the template to repopulate controls
    current_filters = {
        'name_filter': name_filter if name_filter else '',
        'min_rating_filter': min_rating_str if min_rating_str else 'any',
        'sort_by': sort_by,
        'sort_order': sort_order
    }

    return render_template('index.html', 
                           played_games=played_games, 
                           notifications=notifications,
                           current_filters=current_filters,
                           pushover_config_missing=pushover_config_missing)

# Placeholder for other routes to be added later:
@flask_app.route('/search', methods=['GET', 'POST'])
def search():
    search_term = None
    results = [] # Default to empty list for GET request or empty search term
    search_attempted = False # Flag to indicate if a search was actually made

    if request.method == 'POST':
        search_term = request.form.get('search_term', '').strip()
        search_attempted = True # A POST request means a search was attempted
        if search_term:
            api_results = f95_client.get_latest_game_data_from_rss(search_term=search_term, limit=30)
            
            if api_results is None: # This now signifies a complete failure in the client
                flash('Search failed: Could not retrieve data from F95Zone after multiple attempts. Proxies might be failing or the site is down. Please try again later.', 'error')
                results = None # Explicitly set to None to indicate failure to the template
            else:
                results = api_results # This could be an empty list (no results) or list of games
                if not results: # Explicitly check if api_results was an empty list
                    flash('No games found matching your search criteria.', 'info') # Use info or warning
        else:
            flash('Please enter a search term.', 'warning')
            search_attempted = False # No term, so not a real search attempt for results display
            results = [] # Keep results as empty list for no search term
            
    return render_template('search.html', search_term=search_term, results=results, search_attempted=search_attempted)

@flask_app.route('/add_game_to_list', methods=['POST'])
def add_game_to_user_list():
    if request.method == 'POST':
        try:
            game_name = request.form['game_name']
            f95_url = request.form['f95_url']
            version = request.form.get('version') 
            author = request.form.get('author')
            image_url = request.form.get('image_url')
            rss_pub_date_str = request.form.get('rss_pub_date')
            user_notes = request.form.get('user_notes')
            user_rating_str = request.form.get('user_rating') # This will be '0', '1', ..., '5', or '' for Not Rated

            user_rating = None # Default to None
            if user_rating_str: # If not an empty string (i.e., a rating was selected)
                try:
                    rating_val = int(user_rating_str) # Attempt to parse as integer
                    if 0 <= rating_val <= 5:
                        user_rating = rating_val
                    else:
                        # This case should ideally not happen if dropdown values are controlled
                        flash('Invalid rating selected. Must be between 0 and 5.', 'warning')
                        # user_rating remains None
                except ValueError:
                    # This case should ideally not happen with a select dropdown
                    flash('Invalid rating format submitted.', 'warning')
                    # user_rating remains None
            # If user_rating_str is empty ('Not Rated'), user_rating correctly remains None.

            # Basic validation
            if not game_name or not f95_url:
                flash('Game name and URL are required to add to list.', 'error')
                return redirect(url_for('search')) # Or back to where they came from with error

            # Call the function from app.main to add to DB
            # This function will need to handle parsing rss_pub_date_str if necessary
            # and potentially fetching more details or setting defaults.
            # For now, assuming add_game_to_my_list can handle these fields.
            success, message = add_game_to_my_list(
                db_path=DB_PATH, 
                client=f95_client, # Pass the client instance
                f95_url=f95_url,
                name_override=game_name,
                version_override=version,
                author_override=author,
                image_url_override=image_url,
                rss_pub_date_override=rss_pub_date_str,
                # Pass the new fields
                user_rating=user_rating, 
                user_notes=user_notes, 
                notify=True
            )

            if success:
                flash(f'{game_name} added to your list!', 'success')
            else:
                flash(f'Failed to add {game_name}: {message}', 'error')
        
        except Exception as e:
            flask_app.logger.error(f"Error in add_game_to_user_list: {e}")
            flash('An unexpected error occurred while adding the game.', 'error')

    # Redirect back to the search page (or index if preferred)
    # If search_term was part of the URL or session, could redirect back to search results.
    # For simplicity, redirecting to a new search.
    return redirect(url_for('search'))

@flask_app.route('/delete_game/<int:played_game_id>', methods=['POST'])
def delete_game_route(played_game_id):
    success, message = delete_game_from_my_list(DB_PATH, played_game_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('index'))

@flask_app.route('/acknowledge_update/<int:played_game_id>', methods=['POST'])
def acknowledge_update_route(played_game_id):
    success, message, acknowledged_details = mark_game_as_acknowledged(DB_PATH, played_game_id)
    if success and acknowledged_details:
        flash(message, 'success')
        # Also update the last notified status to prevent immediate re-notification for the same acknowledged state
        update_last_notified_status(
            db_path=DB_PATH,
            played_game_id=played_game_id,
            version=acknowledged_details["version"],
            rss_pub_date=acknowledged_details["rss_pub_date"],
            completed_status=acknowledged_details["completed_status"]
        )
    else:
        flash(message, 'error') # Message will be from mark_game_as_acknowledged if it failed
    return redirect(url_for('index'))

@flask_app.route('/edit_details/<int:played_game_id>', methods=['GET', 'POST'])
def edit_details_route(played_game_id):
    game_details = get_my_played_game_details(DB_PATH, played_game_id)
    if not game_details:
        flash('Game not found in your list.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        user_notes = request.form.get('user_notes', '')
        user_rating_str = request.form.get('user_rating', '') # Will be '0'- '5', or ''
        notify_for_updates_str = request.form.get('notify_for_updates')

        user_rating = None # Default to None, meaning 'Not Rated'
        if user_rating_str: # If it's not an empty string, a rating was chosen
            try:
                rating_val = int(user_rating_str) # Try to parse as integer
                if 0 <= rating_val <= 5:
                    user_rating = rating_val
                else:
                    # This path should ideally not be hit with a controlled select dropdown
                    flash('Invalid rating value submitted. Rating not changed.', 'warning')
                    user_rating = game_details.get('user_rating') # Revert to original if invalid submitted value
            except ValueError:
                # This path should also not be hit with a select dropdown
                flash('Invalid rating format. Rating not changed.', 'warning')
                user_rating = game_details.get('user_rating') # Revert to original
        # If user_rating_str was empty ('Not Rated'), user_rating remains None, effectively clearing/setting to Not Rated.

        # Convert checkbox value ('on' or None) to boolean
        notify_for_updates = True if notify_for_updates_str == 'on' else False

        update_result = update_my_played_game_details(
            db_path=DB_PATH,
            played_game_id=played_game_id,
            user_notes=user_notes,
            user_rating=user_rating,
            notify_for_updates=notify_for_updates
        )

        if update_result.get('success'):
            flash('Game details updated successfully!', 'success')
        else:
            flash(f"Failed to update game details: {update_result.get('message', 'Unknown error')}", 'error')
        return redirect(url_for('index')) # Redirect to index after POST

    # For GET request, pass game_details to the template
    return render_template('edit_game.html', game=game_details)

@flask_app.route('/manual_sync/<int:played_game_id>', methods=['POST'])
def manual_sync_route(played_game_id):
    flask_app.logger.info(f"Manual sync requested for played_game_id: {played_game_id}")
    game_name_for_flash = "Selected Game"
    try:
        # Get game name for a more informative flash message before sync
        # as sync might change the name.
        game_details_before_sync = get_my_played_game_details(DB_PATH, played_game_id)
        if game_details_before_sync:
            game_name_for_flash = game_details_before_sync.get('name', game_name_for_flash)

        # Call the existing function to check a single game
        # This function updates the DB directly and logs its actions
        check_single_game_update_and_status(DB_PATH, f95_client, played_game_id)
        
        flash(f"Manual sync initiated for '{game_name_for_flash}'. Check notifications for any updates.", 'success')
    except Exception as e:
        flask_app.logger.error(f"Error during manual sync for played_game_id {played_game_id}: {e}", exc_info=True)
        flash(f"Manual sync failed for '{game_name_for_flash}'. Error: {str(e)[:100]}", 'error') # Truncate long errors
    return redirect(url_for('index'))

@flask_app.route('/settings', methods=['GET', 'POST'])
def settings_route():
    if request.method == 'POST':
        # Update Schedule
        update_schedule_hours_str = request.form.get('update_schedule_hours')
        if update_schedule_hours_str is not None: # Check if the field was submitted
            try:
                new_schedule_hours = int(update_schedule_hours_str)
                if set_setting(DB_PATH, 'update_schedule_hours', str(new_schedule_hours)):
                    # flash('Update schedule saved successfully!', 'success') # Consolidate flash messages
                    flask_app.logger.info(f"Settings changed: Triggering scheduler update with new interval: {new_schedule_hours} hours.")
                    start_or_reschedule_scheduler(flask_app)
                else:
                    flash('Failed to save update schedule.', 'error')
            except ValueError:
                flash('Invalid schedule value provided. Must be a number.', 'error')
        # else: # If not submitted, don't flash an error, just don't update it.
            # flash('No schedule value provided.', 'warning')

        # Pushover Settings
        pushover_user_key = request.form.get('pushover_user_key', '')
        pushover_api_key = request.form.get('pushover_api_key', '')
        set_setting(DB_PATH, 'pushover_user_key', pushover_user_key)
        set_setting(DB_PATH, 'pushover_api_key', pushover_api_key)

        # Pushover Notification Toggles (booleans are stored as 'True'/'False' strings)
        notify_settings = {
            'notify_on_game_add': request.form.get('notify_on_game_add') == 'on',
            'notify_on_game_delete': request.form.get('notify_on_game_delete') == 'on',
            'notify_on_game_update': request.form.get('notify_on_game_update') == 'on',
            'notify_on_status_change_completed': request.form.get('notify_on_status_change_completed') == 'on',
            'notify_on_status_change_abandoned': request.form.get('notify_on_status_change_abandoned') == 'on',
            'notify_on_status_change_on_hold': request.form.get('notify_on_status_change_on_hold') == 'on'
        }
        for key, value in notify_settings.items():
            set_setting(DB_PATH, key, str(value))

        flash('Settings saved successfully!', 'success') # Single success message for all changes
        return redirect(url_for('settings_route'))

    # GET request - Fetch all settings
    current_settings = {
        'update_schedule_hours': get_setting(DB_PATH, 'update_schedule_hours', '24'),
        'pushover_user_key': get_setting(DB_PATH, 'pushover_user_key', ''),
        'pushover_api_key': get_setting(DB_PATH, 'pushover_api_key', ''),
        'notify_on_game_add': get_setting(DB_PATH, 'notify_on_game_add', 'True') == 'True',
        'notify_on_game_delete': get_setting(DB_PATH, 'notify_on_game_delete', 'True') == 'True',
        'notify_on_game_update': get_setting(DB_PATH, 'notify_on_game_update', 'True') == 'True',
        'notify_on_status_change_completed': get_setting(DB_PATH, 'notify_on_status_change_completed', 'True') == 'True',
        'notify_on_status_change_abandoned': get_setting(DB_PATH, 'notify_on_status_change_abandoned', 'True') == 'True',
        'notify_on_status_change_on_hold': get_setting(DB_PATH, 'notify_on_status_change_on_hold', 'True') == 'True'
    }
    
    # Define schedule options for the dropdown
    schedule_options = [
        {'value': '-1', 'label': 'Manual Only'}, # Using -1 for manual
        {'value': '1', 'label': 'Every Hour'},
        {'value': '3', 'label': 'Every 3 Hours'},
        {'value': '6', 'label': 'Every 6 Hours'},
        {'value': '12', 'label': 'Every 12 Hours'},
        {'value': '24', 'label': 'Every 24 Hours'},
        {'value': '48', 'label': 'Every 48 Hours'}
    ]
    return render_template('settings.html', current_settings=current_settings, schedule_options=schedule_options)

# @flask_app.route('/update_played_game/<int:played_game_id>', methods=['GET', 'POST'])

if __name__ == '__main__':
    # Initialize the database if it doesn't exist or tables are missing
    initialize_database(DB_PATH)
    
    # Note: app.main.initialize_database() should be run by app.main.py
    # This web app assumes the database is already initialized and populated by app.main.py
    # If running this web app for the first time and DB doesn't exist, 
    # you might want to run app/main.py once first.
    # The above line now handles this for development.

    # Start the scheduler after app initialization
    # Pass flask_app directly as the app_instance
    start_or_reschedule_scheduler(flask_app)
    
    flask_app.run(debug=True, host='0.0.0.0', port=5000) 