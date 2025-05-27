import sys
import os
import sqlite3
import logging # Added for scheduler logging
import atexit # Added for scheduler shutdown
from datetime import datetime, timezone, timedelta # Added for user created_at and next_run_time

# Add project root to sys.path to allow importing f95apiclient and app.main
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '.')) # app.py is in root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps # For login_required decorator
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
    get_primary_admin_user_id, # Added for fetching primary admin ID
    get_all_users_details, # Added for admin user listing
    scheduled_games_update_check, # Import the new scheduled task function
    check_single_game_update_and_status, # Added for manual sync
    get_user_played_game_urls, # Added for checking existing games in search
    sync_all_my_games_for_user, # Added for manual sync all
    process_rss_feed, # Added for process_rss_feed
    update_completion_statuses, # Added for update_completion_statuses
)

# APScheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

# --- Early Initialization: Database Schema ---
try:
    initialize_database(DB_PATH)
except Exception as e_init_db:
    print(f"CRITICAL_ERROR_INIT_DB_SCHEMA: {e_init_db}", file=sys.stderr)
    # Depending on severity, might sys.exit(1) or let Flask try to start and potentially fail later.

# --- Flask App Instantiation ---
flask_app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
flask_app.secret_key = os.urandom(24) # Needed for flash messages

# --- Global API Client ---
f95_client = F95ApiClient()

# --- Helper Function Definitions ---
# These need to be defined before they are used by module-level calls or routes.

# Database Connection Helper
def get_db_connection():
    """Establishes a connection to the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# User Management Helpers
def create_user(username, password, is_admin=False):
    """Creates a new user in the database."""
    conn = get_db_connection()
    try:
        current_time = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), is_admin, current_time)
        )
        conn.commit()
        # Use flask_app.logger only if flask_app is fully configured for logging
        # For early startup, print might be more reliable if logger isn't ready
        flask_app.logger.info(f"User '{username}' created successfully.")
        return True
    except sqlite3.IntegrityError:
        flask_app.logger.warning(f"Attempted to create user '{username}', but username already exists.")
        return False
    except sqlite3.Error as e:
        flask_app.logger.error(f"Database error creating user '{username}': {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_by_username(username):
    """Retrieves a user by their username."""
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return user
    except sqlite3.Error as e:
        # flask_app.logger might not be ready here if called too early by other startup tasks
        flask_app.logger.error(f"Database error fetching user by username '{username}': {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_user_by_id(user_id):
    """Retrieves a user by their ID."""
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return user
    except sqlite3.Error as e:
        # flask_app.logger might not be ready here
        flask_app.logger.error(f"Database error fetching user by ID '{user_id}': {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_user_count():
    """Returns the total number of users in the database."""
    conn = get_db_connection()
    try:
        count = conn.execute("SELECT COUNT(id) FROM users").fetchone()[0]
        return count
    except sqlite3.Error as e:
        # flask_app.logger might not be ready here
        flask_app.logger.error(f"Database error getting user count: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def update_user_password(user_id, new_password_hash):
    """Updates the user's password_hash in the database."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_password_hash, user_id)
        )
        conn.commit()
        # flask_app.logger.info(f"Password updated for user_id {user_id}.") # Use logger once app confirmed stable
        flask_app.logger.info(f"Password updated for user_id {user_id}.")
        return True
    except sqlite3.Error as e:
        # flask_app.logger.error(f"Database error updating password for user_id {user_id}: {e}")
        flask_app.logger.error(f"Database error updating password for user_id {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def create_initial_admin_user_if_none_exists():
    """Creates a default admin user if no users exist in the database."""
    # This function relies on get_user_count() and create_user()
    # It needs an app_context if flask_app.logger is used inside create_user, but we switched to print for early errors.
    if get_user_count() == 0:
        default_admin_username = "admin"
        default_admin_password = "admin" # CHANGE THIS IN PRODUCTION!
        # print("INFO: No users found in the database. Creating default admin user...", file=sys.stderr)
        flask_app.logger.info("No users found in the database. Creating default admin user...")
        if create_user(default_admin_username, default_admin_password, is_admin=True):
            # print(f"INFO: Default admin user '{default_admin_username}' created with password '{default_admin_password}'. PLEASE CHANGE THE PASSWORD IMMEDIATELY.", file=sys.stderr)
            flask_app.logger.info(f"Default admin user '{default_admin_username}' created with password '{default_admin_password}'. PLEASE CHANGE THE PASSWORD IMMEDIATELY.")
        else:
            # print("ERROR: Failed to create default admin user.", file=sys.stderr)
            flask_app.logger.error("Failed to create default admin user.")

# APScheduler Setup Function Definitions
scheduler = BackgroundScheduler(daemon=True)
scheduler.app = flask_app
scheduler_job_id = "f95_update_check_job"

def run_scheduled_update_job():
    with scheduler.app.app_context():
        current_time_utc = datetime.now(timezone.utc)
        flask_app.logger.info(f"APScheduler: Evaluating user-specific game update job run at {current_time_utc.isoformat()}.")

        primary_admin_id = get_primary_admin_user_id(DB_PATH)
        if not primary_admin_id:
            flask_app.logger.error("APScheduler: Cannot run user-specific sync. No primary admin user found to get/set sync timestamps.")
            return

        last_user_sync_completed_at_str = get_setting(DB_PATH, 'last_user_specific_sync_completed_at', user_id=primary_admin_id)
        current_schedule_hours_str = get_setting(DB_PATH, 'update_schedule_hours_global', default_value='24', user_id=primary_admin_id)
        
        perform_user_sync = True
        schedule_interval_hours = 24.0 # Default to float for calculations

        try:
            schedule_config_value = int(current_schedule_hours_str)
            if schedule_config_value == -5: # 5 minutes testing interval
                schedule_interval_hours = 5 / 60.0 
            elif schedule_config_value > 0:
                schedule_interval_hours = float(schedule_config_value)
            else: # Manual or disabled
                flask_app.logger.info(f"APScheduler: User-specific sync schedule is {schedule_config_value} (manual/disabled). Job should not run based on this setting.")
                # Note: The job itself is scheduled by start_or_reschedule_scheduler based on this value.
                # This check provides an additional safeguard or differing logic if needed.
                # For now, if it's <=0, the job shouldn't have been scheduled with an interval anyway.
                return 
        except ValueError:
            flask_app.logger.warning(f"APScheduler: Could not parse schedule hours '{current_schedule_hours_str}'. Using default {schedule_interval_hours}h for user-specific sync timing.")

        if last_user_sync_completed_at_str:
            try:
                last_sync_time = datetime.fromisoformat(last_user_sync_completed_at_str)
                time_since_last_sync = current_time_utc - last_sync_time
                
                # Skip if the last sync was completed more recently than 90% of the configured interval
                # This tolerance (0.90) prevents rapid re-syncs on restart if the interval is, e.g., 12 hours and it just ran 1 hour ago.
                required_duration_since_last_sync = timedelta(hours=(schedule_interval_hours * 0.90))
                
                if time_since_last_sync < required_duration_since_last_sync:
                    flask_app.logger.info(f"APScheduler: Skipping user-specific sync. Last sync at {last_user_sync_completed_at_str} is too recent. "
                                          f"(Time since last: {time_since_last_sync} vs required: {required_duration_since_last_sync}, Interval: {schedule_interval_hours}h)")
                    perform_user_sync = False
                else:
                    flask_app.logger.info(f"APScheduler: Proceeding with user-specific sync. Last sync was at {last_user_sync_completed_at_str}. "
                                          f"(Time since last: {time_since_last_sync} vs Interval: {schedule_interval_hours}h)")
            except ValueError:
                flask_app.logger.warning(f"APScheduler: Could not parse last_user_specific_sync_completed_at: '{last_user_sync_completed_at_str}'. Proceeding with user-specific sync.")
        else:
            flask_app.logger.info("APScheduler: No record of last user-specific sync. Proceeding with initial user-specific sync.")

        if perform_user_sync:
            flask_app.logger.info(f"APScheduler: Running scheduled user game update checks at {current_time_utc.isoformat()}.")
            try:
                scheduled_games_update_check(DB_PATH, f95_client)
                current_utc_timestamp_iso = datetime.now(timezone.utc).isoformat()
                if set_setting(DB_PATH, 'last_user_specific_sync_completed_at', current_utc_timestamp_iso, user_id=primary_admin_id):
                    flask_app.logger.info(f"APScheduler: Successfully set last_user_specific_sync_completed_at to {current_utc_timestamp_iso} for admin user {primary_admin_id}.")
                else:
                    flask_app.logger.error(f"APScheduler: FAILED to set last_user_specific_sync_completed_at for admin user {primary_admin_id}.")
                flask_app.logger.info(f"APScheduler: User-specific game update checks completed at {datetime.now(timezone.utc).isoformat()}.")
            except Exception as e_user_sync:
                flask_app.logger.error(f"APScheduler: Error during user-specific game update checks: {e_user_sync}", exc_info=True)
        
        flask_app.logger.info(f"APScheduler: Full scheduled job evaluation and execution finished at {datetime.now(timezone.utc).isoformat()}.")

def start_or_reschedule_scheduler(app_instance):
    global scheduler 
    with app_instance.app_context():
        primary_admin_id = get_primary_admin_user_id(DB_PATH)
        current_schedule_hours_str = '24' 

        if primary_admin_id is not None:
            schedule_val = get_setting(DB_PATH, 'update_schedule_hours_global', default_value='24', user_id=primary_admin_id)
            if schedule_val is not None:
                 current_schedule_hours_str = schedule_val
        else:
            flask_app.logger.warning("WARNING_SCHEDULER: No primary admin found, using default schedule of 24 hours.")
        
        try:
            update_value = int(current_schedule_hours_str)
            if update_value == -5:
                flask_app.logger.info("INFO_SCHEDULER: Update interval is 5 minutes (Testing).")
                trigger_args = {'minutes': 5}
            elif update_value <= 0:
                flask_app.logger.info(f"INFO_SCHEDULER: Update interval is {update_value} (Manual/Disabled). Job will be removed if exists.")
                try:
                    if scheduler.get_job(scheduler_job_id):
                        scheduler.remove_job(scheduler_job_id)
                        flask_app.logger.info(f"INFO_SCHEDULER: Removed job '{scheduler_job_id}'.")
                except JobLookupError:
                    flask_app.logger.info(f"INFO_SCHEDULER: Job '{scheduler_job_id}' not found, nothing to remove.")
                return 
            else: 
                flask_app.logger.info(f"INFO_SCHEDULER: Update interval is {update_value} hours.")
                trigger_args = {'hours': update_value}
        except ValueError:
            flask_app.logger.error(f"ERROR_SCHEDULER_CONFIG: Could not parse update_schedule_hours: '{current_schedule_hours_str}'.")
            return

    if not scheduler.running:
        try:
            scheduler.start()
            flask_app.logger.info("INFO_SCHEDULER: Scheduler started.")
            atexit.register(shutdown_scheduler_politely)
        except Exception as e_sched_start:
            flask_app.logger.error(f"ERROR_SCHEDULER: Failed to start scheduler: {e_sched_start}", exc_info=True)

    try:
        existing_job = scheduler.get_job(scheduler_job_id)
        if existing_job:
            scheduler.reschedule_job(scheduler_job_id, trigger=IntervalTrigger(**trigger_args))
            flask_app.logger.info(f"INFO_SCHEDULER: Rescheduled job '{scheduler_job_id}'.")
        else:
            scheduler.add_job(
                func=run_scheduled_update_job,
                trigger=IntervalTrigger(**trigger_args),
                id=scheduler_job_id,
                name='F95Zone Game Update Check',
                replace_existing=True, 
                next_run_time=datetime.now() + timedelta(seconds=10) 
            )
            flask_app.logger.info(f"INFO_SCHEDULER: Added job '{scheduler_job_id}'. First run in ~10s.")
    except Exception as e:
        flask_app.logger.error(f"ERROR_SCHEDULER_ADD_JOB: {e}")

# --- Module-Level Initialization Calls (after definitions and app instantiation) ---
try:
    with flask_app.app_context():
        create_initial_admin_user_if_none_exists()
except Exception as e_init_admin_call:
    print(f"CRITICAL_ERROR_CALL_INIT_ADMIN: {e_init_admin_call}", file=sys.stderr)

try:
    start_or_reschedule_scheduler(flask_app)
except Exception as e_init_scheduler_call:
    print(f"CRITICAL_ERROR_CALL_INIT_SCHEDULER: {e_init_scheduler_call}", file=sys.stderr)


# --- Flask App Configuration and F95APIClient Instantiation ---
# Set Flask's logger level to DEBUG (can be done after flask_app is defined)
flask_app.logger.setLevel(logging.DEBUG)
if not flask_app.debug:
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    flask_app.logger.addHandler(stream_handler)
    flask_app.logger.setLevel(logging.INFO)

# --- Login Required Decorator and Before Request Handler ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login_route', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@flask_app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = get_user_by_id(user_id) # Uses helper defined above
        if g.user is None: 
            session.pop('user_id', None) 
            flask_app.logger.warning(f"User ID {user_id} from session not found in DB. Cleared session.")

# --- Routes Definitions --- 
# (Keep all route definitions below the helper functions and initializations they might depend on)

@flask_app.route('/register', methods=['GET', 'POST'])
def register_route():
    if g.user: # If already logged in, redirect to index
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        password_confirm = request.form['password_confirm']

        error = None
        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        elif password != password_confirm:
            error = 'Passwords do not match.'
        
        if error is None:
            existing_user = get_user_by_username(username)
            if existing_user:
                error = f"User {username} is already registered."
            else:
                # First user to register becomes an admin
                is_first_user = get_user_count() == 0
                if create_user(username, password, is_admin=is_first_user):
                    flash(f'User {username} created successfully! You can now log in.', 'success')
                    if is_first_user:
                        flash('First user registered: You have been made an admin.', 'info')
                    return redirect(url_for('login_route'))
                else:
                    error = "Registration failed due to a server error. Please try again."
        
        if error:
            flash(error, 'error')

    return render_template('register.html')

@flask_app.route('/login', methods=['GET', 'POST'])
def login_route():
    if g.user: # If already logged in, redirect to index
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        error = None
        user = get_user_by_username(username)

        if user is None or not check_password_hash(user['password_hash'], password):
            error = 'Invalid username or password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username'] # Store username for easy display
            flash(f'Welcome back, {user["username"]}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        
        flash(error, 'error')

    return render_template('login.html')

@flask_app.route('/logout')
@login_required
def logout_route():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login_route'))

@flask_app.route('/')
@login_required
def index():
    name_filter = request.args.get('name_filter', None)
    min_rating_str = request.args.get('min_rating_filter', None)
    sort_by = request.args.get('sort_by', 'name') 
    sort_order = request.args.get('sort_order', 'ASC') 

    min_rating_filter = None
    if min_rating_str and min_rating_str != 'any': 
        try:
            min_rating_filter = float(min_rating_str)
        except ValueError:
            flash(f'Invalid minimum rating value \'{min_rating_str}\' ignored.', 'warning')
            min_rating_filter = None

    played_games = get_my_played_games(
        DB_PATH,
        user_id=g.user['id'], # Pass user_id
        name_filter=name_filter,
        min_rating_filter=min_rating_filter,
        sort_by=sort_by,
        sort_order=sort_order
    )
    notifications = check_for_my_updates(DB_PATH, user_id=g.user['id']) # Pass user_id

    pushover_user_key = get_setting(DB_PATH, 'pushover_user_key', user_id=g.user['id']) # Pass user_id
    pushover_api_key = get_setting(DB_PATH, 'pushover_api_key', user_id=g.user['id']) # Pass user_id
    pushover_config_missing = not (pushover_user_key and pushover_api_key)

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
        
        user_played_urls = set()
        if g.user:
            user_played_urls = get_user_played_game_urls(DB_PATH, g.user['id'])

        if search_term:
            api_results_raw = f95_client.get_latest_game_data_from_rss(search_term=search_term, limit=30)
            
            if api_results_raw is None: # This now signifies a complete failure in the client
                flash('Search failed: Could not retrieve data from F95Zone after multiple attempts. Proxies might be failing or the site is down. Please try again later.', 'error')
                results = None # Explicitly set to None to indicate failure to the template
            else:
                results = []
                for game_data in api_results_raw:
                    game_data['is_already_in_list'] = game_data.get('url') in user_played_urls
                    results.append(game_data)

                if not results: # Explicitly check if api_results was an empty list after processing
                    flash('No games found matching your search criteria.', 'info') # Use info or warning
        else:
            flash('Please enter a search term.', 'warning')
            search_attempted = False # No term, so not a real search attempt for results display
            results = [] # Keep results as empty list for no search term
            
    return render_template('search.html', search_term=search_term, results=results, search_attempted=search_attempted)

@flask_app.route('/add_game_to_list', methods=['POST'])
@login_required
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
            user_rating_str = request.form.get('user_rating')

            user_rating = None 
            if user_rating_str: 
                try:
                    rating_val = int(user_rating_str) 
                    if 0 <= rating_val <= 5:
                        user_rating = rating_val
                    else:
                        flash('Invalid rating selected. Must be between 0 and 5.', 'warning')
                except ValueError:
                    flash('Invalid rating format submitted.', 'warning')

            if not game_name or not f95_url:
                flash('Game name and URL are required to add to list.', 'error')
                return redirect(url_for('search')) 

            success, message = add_game_to_my_list(
                db_path=DB_PATH, 
                user_id=g.user['id'], # Pass user_id
                client=f95_client, 
                f95_url=f95_url,
                name_override=game_name,
                version_override=version,
                author_override=author,
                image_url_override=image_url,
                rss_pub_date_override=rss_pub_date_str,
                user_rating=user_rating, 
                user_notes=user_notes, 
                notify=True # This notify might become a user preference later
            )

            if success:
                flash(f'{game_name} added to your list!', 'success')
            else:
                flash(f'Failed to add {game_name}: {message}', 'error')
        
        except Exception as e:
            flask_app.logger.error(f"Error in add_game_to_user_list: {e}", exc_info=True)
            flash('An unexpected error occurred while adding the game.', 'error')

    return redirect(url_for('search'))

@flask_app.route('/delete_game/<int:played_game_id>', methods=['POST'])
@login_required
def delete_game_route(played_game_id):
    success, message = delete_game_from_my_list(DB_PATH, user_id=g.user['id'], played_game_id=played_game_id) # Pass user_id
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('index'))

@flask_app.route('/acknowledge_update/<int:played_game_id>', methods=['POST'])
@login_required
def acknowledge_update_route(played_game_id):
    success, message, acknowledged_details = mark_game_as_acknowledged(DB_PATH, user_id=g.user['id'], played_game_id=played_game_id) # Pass user_id
    if success and acknowledged_details:
        flash(message, 'success')
        update_last_notified_status(
            db_path=DB_PATH,
            user_id=g.user['id'], # Pass user_id
            played_game_id=played_game_id,
            version=acknowledged_details["version"],
            rss_pub_date=acknowledged_details["rss_pub_date"],
            completed_status=acknowledged_details["completed_status"]
        )
    else:
        flash(message, 'error') 
    return redirect(url_for('index'))

@flask_app.route('/edit_details/<int:played_game_id>', methods=['GET', 'POST'])
@login_required
def edit_details_route(played_game_id):
    game_details = get_my_played_game_details(DB_PATH, user_id=g.user['id'], played_game_id=played_game_id) # Pass user_id
    if not game_details:
        flash('Game not found in your list.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        user_notes = request.form.get('user_notes', '')
        user_rating_str = request.form.get('user_rating', '') 
        notify_for_updates_str = request.form.get('notify_for_updates')

        user_rating = None 
        if user_rating_str: 
            try:
                rating_val = int(user_rating_str) 
                if 0 <= rating_val <= 5:
                    user_rating = rating_val
                else:
                    flash('Invalid rating value submitted. Rating not changed.', 'warning')
                    user_rating = game_details.get('user_rating') 
            except ValueError:
                flash('Invalid rating format. Rating not changed.', 'warning')
                user_rating = game_details.get('user_rating') 

        notify_for_updates = True if notify_for_updates_str == 'on' else False

        update_result = update_my_played_game_details(
            db_path=DB_PATH,
            user_id=g.user['id'], # Pass user_id
            played_game_id=played_game_id,
            user_notes=user_notes,
            user_rating=user_rating,
            notify_for_updates=notify_for_updates
        )

        if update_result.get('success'):
            flash('Game details updated successfully!', 'success')
        else:
            flash(f"Failed to update game details: {update_result.get('message', 'Unknown error')}", 'error')
        return redirect(url_for('index')) 

    return render_template('edit_game.html', game=game_details)

@flask_app.route('/manual_sync/<int:played_game_id>', methods=['POST'])
@login_required
def manual_sync_route(played_game_id):
    flask_app.logger.info(f"Manual sync requested by user {g.user['id']} for played_game_id: {played_game_id}")
    game_name_for_flash = "Selected Game"
    try:
        game_details_before_sync = get_my_played_game_details(DB_PATH, user_id=g.user['id'], played_game_id=played_game_id) # Pass user_id
        if game_details_before_sync:
            game_name_for_flash = game_details_before_sync.get('name', game_name_for_flash)

        # check_single_game_update_and_status already works on played_game_id, which is user-specific via user_played_games table
        # However, its internal calls to get/set settings related to notifications might need user_id if those become user-specific settings.
        # For now, assuming it primarily updates game details and user_played_games based on played_game_id.
        # We will need to review check_single_game_update_and_status in app/main.py to ensure it correctly handles user context if it reads global settings for notifications.
        check_single_game_update_and_status(DB_PATH, f95_client, played_game_row_id=played_game_id, user_id=g.user['id']) # Pass user_id
        
        flash(f"Manual sync initiated for '{game_name_for_flash}'. Check notifications for any updates.", 'success')
    except Exception as e:
        flask_app.logger.error(f"Error during manual sync for user {g.user['id']}, played_game_id {played_game_id}: {e}", exc_info=True)
        flash(f"Manual sync failed for '{game_name_for_flash}'. Error: {str(e)[:100]}", 'error') 
    return redirect(url_for('index'))

@flask_app.route('/manual_sync_all', methods=['POST'])
@login_required
def manual_sync_all_route():
    flask_app.logger.info(f"Manual sync all requested by user {g.user['id']}")
    try:
        processed_count, total_count = sync_all_my_games_for_user(DB_PATH, f95_client, user_id=g.user['id'])
        if total_count > 0:
            flash(f"Manual sync for all {processed_count}/{total_count} relevant games initiated. Check notifications for any updates.", 'success')
        else:
            flash("No relevant games found to sync based on your notification preferences and game statuses.", 'info')
    except Exception as e:
        flask_app.logger.error(f"Error during manual sync all for user {g.user['id']}: {e}", exc_info=True)
        flash(f"Manual sync for all games failed. Error: {str(e)[:100]}", 'error') 
    return redirect(url_for('index'))

@flask_app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_route():
    if request.method == 'POST':
        # Handle global update schedule change (admin only)
        update_schedule_hours_str = request.form.get('update_schedule_hours')
        if update_schedule_hours_str is not None: 
            flask_app.logger.info(f"User {g.user['username']} (ID: {g.user['id']}) attempting to set schedule. Admin status: {g.user['is_admin']} (Type: {type(g.user['is_admin'])})") # DEBUGGING
            if g.user and g.user['is_admin']:
                try:
                    new_schedule_hours = int(update_schedule_hours_str)
                    if set_setting(DB_PATH, 'update_schedule_hours_global', str(new_schedule_hours), user_id=g.user['id']):
                        flask_app.logger.info(f"Admin user {g.user['id']} changed global update schedule to: {new_schedule_hours} hours.")
                        start_or_reschedule_scheduler(flask_app) 
                    else:
                        flash('Failed to save global update schedule.', 'error')
                except ValueError:
                    flash('Invalid schedule value provided. Must be a number.', 'error')
            else:
                # Non-admin user attempted to change schedule, flash warning.
                # Only flash if a value was actually submitted for this field.
                flash('Update schedule can only be set by an admin.', 'warning')

        # Handle user-specific settings (Pushover, notification toggles)
        pushover_user_key = request.form.get('pushover_user_key', '')
        pushover_api_key = request.form.get('pushover_api_key', '')
        set_setting(DB_PATH, 'pushover_user_key', pushover_user_key, user_id=g.user['id']) # Pass user_id
        set_setting(DB_PATH, 'pushover_api_key', pushover_api_key, user_id=g.user['id']) # Pass user_id

        notify_settings_keys = [
            'notify_on_game_add', 'notify_on_game_delete', 'notify_on_game_update',
            'notify_on_status_change_completed', 'notify_on_status_change_abandoned',
            'notify_on_status_change_on_hold'
        ]
        for key in notify_settings_keys:
            value = request.form.get(key) == 'on'
            set_setting(DB_PATH, key, str(value), user_id=g.user['id']) # Pass user_id

        flash('Settings saved successfully!', 'success') 
        return redirect(url_for('settings_route'))

    # GET request - Fetch all settings for the current user
    current_settings = {
        # For update_schedule_hours, we show the global schedule value.
        # Only admins can change it, but all users see the current effective schedule.
        'update_schedule_hours': '24', # Default
        'pushover_user_key': get_setting(DB_PATH, 'pushover_user_key', '', user_id=g.user['id']),
        'pushover_api_key': get_setting(DB_PATH, 'pushover_api_key', '', user_id=g.user['id']),
        'notify_on_game_add': get_setting(DB_PATH, 'notify_on_game_add', 'True', user_id=g.user['id']) == 'True',
        'notify_on_game_delete': get_setting(DB_PATH, 'notify_on_game_delete', 'True', user_id=g.user['id']) == 'True',
        'notify_on_game_update': get_setting(DB_PATH, 'notify_on_game_update', 'True', user_id=g.user['id']) == 'True',
        'notify_on_status_change_completed': get_setting(DB_PATH, 'notify_on_status_change_completed', 'True', user_id=g.user['id']) == 'True',
        'notify_on_status_change_abandoned': get_setting(DB_PATH, 'notify_on_status_change_abandoned', 'True', user_id=g.user['id']) == 'True',
        'notify_on_status_change_on_hold': get_setting(DB_PATH, 'notify_on_status_change_on_hold', 'True', user_id=g.user['id']) == 'True'
    }
    
    primary_admin_id_for_schedule = get_primary_admin_user_id(DB_PATH)
    if primary_admin_id_for_schedule is not None:
        global_schedule_val = get_setting(DB_PATH, 'update_schedule_hours_global', default_value='24', user_id=primary_admin_id_for_schedule)
        if global_schedule_val is not None:
            current_settings['update_schedule_hours'] = global_schedule_val
    else:
        # If no admin, implies fresh setup, keep default or log warning
        flask_app.logger.warning("Settings page: No primary admin found for global schedule display, showing default.")

    schedule_options = [
        {'value': '-5', 'label': 'Every 5 Minutes (Testing)'},
        {'value': '-1', 'label': 'Manual Only'}, 
        {'value': '1', 'label': 'Every Hour'},
        {'value': '3', 'label': 'Every 3 Hours'},
        {'value': '6', 'label': 'Every 6 Hours'},
        {'value': '12', 'label': 'Every 12 Hours'},
        {'value': '24', 'label': 'Every 24 Hours'},
        {'value': '48', 'label': 'Every 48 Hours'}
    ]
    # Only admin can see/edit schedule options for global scheduler
    can_edit_schedule = g.user['is_admin'] if g.user else False # Changed to dictionary access and added g.user check

    return render_template('settings.html', current_settings=current_settings, schedule_options=schedule_options, can_edit_schedule=can_edit_schedule)

@flask_app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password_route():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_new_password = request.form['confirm_new_password']

        error = None
        if not current_password:
            error = 'Current password is required.'
        elif not new_password:
            error = 'New password is required.'
        elif new_password != confirm_new_password:
            error = 'New passwords do not match.'
        # Add more password complexity rules here if desired, e.g., minimum length
        elif len(new_password) < 8:
            error = 'New password must be at least 8 characters long.'

        if error is None:
            # Check current password
            if not check_password_hash(g.user['password_hash'], current_password):
                error = 'Incorrect current password.'
            else:
                # Update password
                new_password_hash_val = generate_password_hash(new_password)
                if update_user_password(g.user['id'], new_password_hash_val):
                    flash('Your password has been updated successfully!', 'success')
                    # Optionally, log the user out and redirect to login, or just stay on the page/redirect to settings
                    return redirect(url_for('settings_route')) 
                else:
                    error = 'Failed to update password due to a server error. Please try again.'
        
        if error:
            flash(error, 'error')

    return render_template('change_password.html')

@flask_app.route('/admin/users')
@login_required
def admin_users_route():
    if not g.user or not g.user['is_admin']:
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('index'))
    
    users = get_all_users_details(DB_PATH)
    return render_template('admin_users.html', users=users)

# @flask_app.route('/update_played_game/<int:played_game_id>', methods=['GET', 'POST'])
# def update_played_game_route(played_game_id): # Placeholder - comment out if not implemented
#     pass

def shutdown_scheduler_politely():
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    # initialize_database(DB_PATH) # Moved to top-level
    # create_initial_admin_user_if_none_exists() # Moved to top-level
    # start_or_reschedule_scheduler(flask_app) # Moved to top-level
    
    flask_app.run(debug=True, host='0.0.0.0', port=5000) 