from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify, g, send_from_directory
from functools import wraps
import os
import sys
import threading
from werkzeug.security import check_password_hash, generate_password_hash
import datetime
from f95apiclient import F95ApiClient

# --- New Module Imports ---
from app.logging_config import setup_logging
from app.database import (
    initialize_database, 
    get_db_connection,
    get_primary_admin_user_id,
    get_all_users_details,
    get_setting,
    set_setting,
    get_all_user_ids
)
from app.services import (
    add_game_to_my_list,
    get_my_played_games,
    get_my_played_game_details,
    update_my_played_game_details,
    delete_game_from_my_list,
    mark_game_as_acknowledged,
    update_last_notified_status,
    check_single_game_update_and_status,
    sync_all_my_games_for_user,
    search_games_for_user,
    check_for_my_updates,
    send_pushover_notification
)
from app.scheduler import start_or_reschedule_scheduler

# Constants
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev_options_secret_key")
DB_PATH = os.environ.get("DATABASE_PATH", "/data/f95_games.db")
IMAGE_CACHE_DIR_FS = os.getenv("IMAGE_CACHE_DIR_FS", "/data/image_cache")

# Setup Logging
logger = setup_logging()

# Initialize Flask
flask_app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
flask_app.secret_key = SECRET_KEY
flask_app.config['DATABASE'] = DB_PATH
flask_app.logger = logger # Use our configured logger

# --- Database Initialization ---
try:
    initialize_database(DB_PATH)
except Exception as e_init_db:
    flask_app.logger.critical(f"CRITICAL_ERROR_INIT_DB_SCHEMA: {e_init_db}")

# --- Helper Functions ---

def create_user(username, password, is_admin=False):
    """Creates a new user in the database."""
    password_hash = generate_password_hash(password)
    conn = get_db_connection(DB_PATH)
    if not conn: return False
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, is_admin, datetime.datetime.now(datetime.timezone.utc).isoformat())
        )
        conn.commit()
        return True
    except Exception as e:
        flask_app.logger.error(f"Error creating user: {e}")
        return False
    finally:
        conn.close()

def get_user_count():
    """Returns the total number of users."""
    conn = get_db_connection(DB_PATH)
    if not conn: return 0
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return count
    finally:
        conn.close()

def create_initial_admin_user_if_none_exists():
    """Creates a default admin user if the database is empty."""
    if get_user_count() == 0:
        default_admin_username = "admin"
        default_admin_password = "admin" # CHANGE THIS IN PRODUCTION!
        flask_app.logger.info("No users found. Creating default admin user...")
        if create_user(default_admin_username, default_admin_password, is_admin=True):
            flask_app.logger.info(f"Default admin '{default_admin_username}' created. CHANGE PASSWORD IMMEDIATELY.")
        else:
            flask_app.logger.error("Failed to create default admin user.")

# Ensure initial user exists
create_initial_admin_user_if_none_exists()

# Scheduler Startup
try:
    start_or_reschedule_scheduler(flask_app)
except Exception as e:
    flask_app.logger.error(f"Failed to start scheduler: {e}")


# --- Thread Wrapper for Background Sync ---
def sync_all_for_user_background_task(app_context, user_id_to_sync, db_path_to_use, force_scrape_flag: bool = False):
    """Refactored background task wrapper."""
    with app_context.app_context(): # Ensure Flask context for logging/db if needed
        local_f95_client = F95ApiClient() 
        try:
            count, total = sync_all_my_games_for_user(
                db_path=db_path_to_use, 
                f95_client=local_f95_client, 
                user_id=user_id_to_sync,
                force_scrape=force_scrape_flag
            )
            # Notify user of completion
            if get_setting(db_path_to_use, 'notify_on_sync_complete', 'True', user_id=user_id_to_sync) == 'True':
                 send_pushover_notification(
                     db_path_to_use, 
                     user_id_to_sync, 
                     "Manual Sync Complete", 
                     f"Checked {count}/{total} games for updates."
                 )
        except Exception as e:
            flask_app.logger.error(f"Background sync error (User {user_id_to_sync}): {e}", exc_info=True)
        finally:
            if local_f95_client:
                local_f95_client.close_session()

# --- Decorators ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@flask_app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db_connection(DB_PATH)
        g.user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()

# --- Routes ---

@flask_app.route('/', methods=['GET'])
@login_required
def index():
    user_id = session['user_id']
    
    # Filter Logic
    name_filter = request.args.get('name_filter')
    min_rating_filter = request.args.get('min_rating_filter')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'ASC')
    
    filters = {
        'name_filter': name_filter or '',
        'min_rating_filter': min_rating_filter or 'any',
        'sort_by': sort_by,
        'sort_order': sort_order
    }
    
    # Check for updates notification logic (from main.py check_for_my_updates)
    # We can invoke check_for_my_updates from services if needed for display notifs
    # For now, just getting the list
    
    games_list = get_my_played_games(
        DB_PATH, 
        user_id, 
        name_filter=name_filter,
        min_rating_filter=min_rating_filter,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    # Notifications
    notifications = check_for_my_updates(DB_PATH, user_id)
    
    # Pushover Config Check
    p_key = get_setting(DB_PATH, 'pushover_user_key', user_id=user_id)
    p_token = get_setting(DB_PATH, 'pushover_api_token', user_id=user_id)
    pushover_config_missing = not (p_key and p_token)
    
    return render_template('index.html', played_games=games_list, current_filters=filters, notifications=notifications, pushover_config_missing=pushover_config_missing)

@flask_app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection(DB_PATH)
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username or password')
            
    return render_template('login.html')

@flask_app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@flask_app.route('/register', methods=['GET', 'POST'])
def register():
    # Only allow registration if no users exist or (optionally) if logged in admin allows it?
    # Requirement wasn't strict, but typically open registration or admin-only.
    # Allowing open registration for now as per original app likely did (though original didn't have explicit route shown in snippets)
    # Actually, original code had create_user function.
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if create_user(username, password):
            flash('Registration successful. Please login.')
            return redirect(url_for('login'))
        else:
            flash('Username already exists or error.')
    return render_template('register.html')

@flask_app.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    results = None
    search_term = None
    search_attempted = False
    
    if request.method == 'POST':
        search_attempted = True
        search_term = request.form.get('search_term')
        if search_term and len(search_term) >= 3:
            results, error_msg = search_games_for_user(DB_PATH, search_term, session['user_id'])
            if error_msg:
                flash(f"Search warning: {error_msg}. showing local results.", 'warning')
            
            if not results:
                flash(f'No games found matching "{search_term}".', 'warning')
        else:
             flash('Please enter at least 3 characters.', 'warning')
             
    return render_template('search.html', results=results, search_term=search_term, search_attempted=search_attempted)

@flask_app.route('/cached_images/<path:filename>')
def serve_cached_image(filename):
    return send_from_directory(IMAGE_CACHE_DIR_FS, filename)

@flask_app.route('/search_games_api', methods=['GET'])
@login_required
def search_games_api():
    query = request.args.get('query')
    if not query or len(query) < 3:
        return jsonify([])
    results, error = search_games_for_user(DB_PATH, query, session['user_id'])
    # API consumers might just want the list, but we could add error metadata if needed. 
    # For now, just return the list to avoid breaking contract, or return object?
    # Original was just a list. Let's return list but log error.
    if error:
        logger.warning(f"API Search warning: {error}")
    return jsonify(results)

@flask_app.route('/add_game', methods=['POST'])
@login_required
def add_game():
    f95_url = request.form.get('f95_url')
    name = request.form.get('name') or request.form.get('game_name') # Search template uses game_name
    version = request.form.get('version')
    author = request.form.get('author')
    image_url = request.form.get('image_url')
    rss_pub_date = request.form.get('rss_pub_date')
    user_notes = request.form.get('user_notes')
    user_rating = request.form.get('user_rating')
    
    # Clean up optional fields
    if user_rating == "": user_rating = None
    
    success, msg = add_game_to_my_list(DB_PATH, session['user_id'], f95_url, 
                                       name_override=name,
                                       version_override=version,
                                       author_override=author,
                                       image_url_override=image_url,
                                       rss_pub_date_override=rss_pub_date,
                                       user_notes=user_notes,
                                       user_rating=user_rating)
    if success:
        flash(msg, 'success')
        
        # --- Auto-Trigger Background Sync for New Game ---
        # Fetch game_id (which is needed for sync) from the list we just added to?
        # add_game_to_my_list returns success/msg, but not the ID.
        # We need to look it up or modify add_game_to_my_list to return it.
        # Looking up by URL is safe enough for this context.
        try:
            conn = get_db_connection(DB_PATH)
            # Find the game_id from valid games table first
            g_row = conn.execute("SELECT id FROM games WHERE f95_url = ?", (f95_url.strip(),)).fetchone()
            if g_row:
                game_id = g_row['id']
                # Now trigger the sync thread (reuse manual_sync_game logic if possible or inline it)
                def single_sync_task(app_instance, user_id, g_id):
                    with app_instance.app_context():
                        client = F95ApiClient()
                        try:
                            # Force scrape to get full details immediately
                            check_single_game_update_and_status(DB_PATH, client, g_id, user_id, force_scrape=True) 
                        except Exception as e:
                            app_instance.logger.error(f"Auto-sync error for game {g_id}: {e}")
                        finally:
                            client.close_session()

                thread = threading.Thread(target=single_sync_task, args=(flask_app, session['user_id'], game_id))
                thread.start()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to trigger auto-sync for new game: {e}")
        # -------------------------------------------------

    else:
         # If already in list, show as info/success context or warning
         category = 'success' if "already in your list" in msg else 'danger'
         flash(msg, category)
    return redirect(url_for('index'))

@flask_app.route('/delete_game/<int:played_game_id>', methods=['POST'])
@login_required
def delete_game(played_game_id):
    success, msg = delete_game_from_my_list(DB_PATH, session['user_id'], played_game_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('index'))

@flask_app.route('/manual_sync_all', methods=['POST'])
@login_required
def manual_sync_all():
    """Triggers a background sync for the current user."""
    # Check user setting for force scrape
    force_scrape = get_setting(DB_PATH, 'force_scrape_on_manual_sync', 'False', user_id=session['user_id']) == 'True'
    
    # Launch background thread
    thread = threading.Thread(
        target=sync_all_for_user_background_task,
        args=(flask_app, session['user_id'], DB_PATH, force_scrape) 
    )
    thread.start()
    msg = 'Manual sync started in background.'
    if force_scrape: msg += ' (Force Scrape Enabled)'
    flash(msg, 'info')
    return redirect(url_for('index'))

@flask_app.route('/manual_sync_game/<int:played_game_id>', methods=['POST'])
@login_required
def manual_sync_game(played_game_id):
    # Logic to sync single game - simpler to just trigger check_single_game_update_and_status in background or foreground?
    # Foreground might timeout if scraping. Background better.
    # We need a wrapper for single game sync or just call check_single_game_update_and_status
    # For now, let's run in background to be safe.
    def single_sync_task(app_instance, user_id, game_id):
        with app_instance.app_context():
            # Setup client
            client = F95ApiClient()
            try:
                # Signature: check_single_game_update_and_status(db_path, f95_client, played_game_row_id, user_id, force_scrape=False)
                # Note: manual_sync_game passes 'played_game_id' which corresponds to 'played_game_row_id' (upg.id)
                check_single_game_update_and_status(DB_PATH, client, game_id, user_id, force_scrape=True)
                
                # Notify completion
                if get_setting(DB_PATH, 'notify_on_sync_complete', 'True', user_id=user_id) == 'True':
                     send_pushover_notification(
                         DB_PATH, 
                         user_id, 
                         "Game Sync Complete", 
                         "Manual check for single game finished."
                     )
            except Exception as e:
                app_instance.logger.error(f"Single sync error: {e}", exc_info=True)
            finally:
                client.close_session()
            
    thread = threading.Thread(
        target=single_sync_task,
        args=(flask_app, session['user_id'], played_game_id)
    )
    thread.start()
    flash('Game sync started in background.', 'info')
    return redirect(url_for('index'))

@flask_app.route('/acknowledge_update/<int:played_game_id>', methods=['POST'])
@login_required
def acknowledge_update(played_game_id):
    success, msg, _ = mark_game_as_acknowledged(DB_PATH, session['user_id'], played_game_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('index'))

@flask_app.route('/edit_game/<int:played_game_id>', methods=['GET', 'POST'])
@login_required
def edit_game(played_game_id):
    if request.method == 'POST':
        user_notes = request.form.get('user_notes')
        user_rating = request.form.get('user_rating')
        notify = request.form.get('notify_for_updates') == 'on'
        
        # rating conversion
        rating_val = int(user_rating) if user_rating and user_rating.isdigit() else None
        
        success, msg = update_my_played_game_details(
            DB_PATH, 
            session['user_id'], 
            played_game_id, 
            user_notes=user_notes, 
            user_rating=rating_val, 
            notify_for_updates=notify
        )
        flash(msg, 'success' if success else 'error')
        return redirect(url_for('index'))
    
    # GET: fetch details
    game = get_my_played_game_details(DB_PATH, session['user_id'], played_game_id)
    if not game:
        flash('Game not found.', 'error')
        return redirect(url_for('index'))
    return render_template('edit_game.html', game=game)

@flask_app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_new_password')
        
        conn = get_db_connection(DB_PATH)
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        if not check_password_hash(user['password_hash'], current_pw):
            flash('Incorrect current password.', 'error')
        elif new_pw != confirm_pw:
            flash('New passwords do not match.', 'error')
        else:
            new_hash = generate_password_hash(new_pw)
            conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, session['user_id']))
            conn.commit()
            flash('Password updated successfully.', 'success')
            conn.close()
            return redirect(url_for('settings'))
        conn.close()
    return render_template('change_password.html')

@flask_app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_id = session['user_id']
    is_admin = session.get('is_admin', False)
    
    if request.method == 'POST':
        # 1. User Settings (Pushover & Notifications)
        pushover_user_key = request.form.get('pushover_user_key')
        pushover_api_key = request.form.get('pushover_api_key')
        
        set_setting(DB_PATH, 'pushover_user_key', pushover_user_key, user_id=user_id)
        set_setting(DB_PATH, 'pushover_api_token', pushover_api_key, user_id=user_id) # Stored as api_token in DB
        
        # Checkboxes - missing in form means False
        notify_opts = [
            'notify_on_game_add', 'notify_on_game_delete', 'notify_on_game_update',
            'notify_on_status_change_completed', 'notify_on_status_change_abandoned', 'notify_on_status_change_on_hold',
            'force_scrape_on_manual_sync'
        ]
        for opt in notify_opts:
            val = 'True' if request.form.get(opt) == 'on' else 'False'
            set_setting(DB_PATH, opt, val, user_id=user_id)
            
        # 2. Global Settings (Admin Only)
        if is_admin:
            f95_user = request.form.get('f95_username')
            f95_pass = request.form.get('f95_password')
            sched_hours = request.form.get('update_schedule_hours')
            
            # For global settings, we might store them under the admin user ID or a special system ID (common practice is admin user)
            set_setting(DB_PATH, 'f95_username', f95_user, user_id=user_id)
            set_setting(DB_PATH, 'f95_password', f95_pass, user_id=user_id)
            set_setting(DB_PATH, 'update_schedule_hours_global', sched_hours, user_id=user_id)
            
            # Reschedule if changed
            try:
                start_or_reschedule_scheduler(flask_app)
            except Exception as e:
                flask_app.logger.error(f"Failed to reschedule: {e}")

        flash('Settings updated successfully.', 'success')
        return redirect(url_for('settings'))

    # GET: Populate settings
    # Fetch all relevant settings
    
    # Helper to get bool setting
    def get_bool_setting(key):
        return get_setting(DB_PATH, key, 'False', user_id=user_id) == 'True'
    
    # User specific
    current_settings = {
        'pushover_user_key': get_setting(DB_PATH, 'pushover_user_key', '', user_id=user_id),
        'pushover_api_key': get_setting(DB_PATH, 'pushover_api_token', '', user_id=user_id), # Template expects pushover_api_key
        'notify_on_game_add': get_bool_setting('notify_on_game_add'),
        'notify_on_game_delete': get_bool_setting('notify_on_game_delete'),
        'notify_on_game_update': get_bool_setting('notify_on_game_update'),
        'notify_on_status_change_completed': get_bool_setting('notify_on_status_change_completed'),
        'notify_on_status_change_abandoned': get_bool_setting('notify_on_status_change_abandoned'),
        'notify_on_status_change_on_hold': get_bool_setting('notify_on_status_change_on_hold'),
        'force_scrape_on_manual_sync': get_bool_setting('force_scrape_on_manual_sync'),
    }
    
    # Global / Admin specific
    # Even if not admin, we might need to show them (though template disables fields)
    # But usually only admin sees/edits these.
    # We'll fetch them from the current user perspective. 
    # NOTE: In this app design, 'global' credentials seem to be tied to the 'primary admin'.
    # If the current user IS the primary admin, they see them.
    # Logic in database.py get_primary_admin_user_id suggests there's one primary.
    
    primary_admin_id = get_primary_admin_user_id(DB_PATH)
    is_primary_admin = (str(user_id) == str(primary_admin_id)) or (is_admin and not primary_admin_id)

    if is_primary_admin:
        # Fetch from self
        current_settings['f95_username'] = get_setting(DB_PATH, 'f95_username', '', user_id=user_id)
        current_settings['f95_password'] = get_setting(DB_PATH, 'f95_password', '', user_id=user_id)
        current_settings['update_schedule_hours'] = get_setting(DB_PATH, 'update_schedule_hours_global', '6', user_id=user_id)
    else:
        # Hide or show masked? Template handles disabled state but expects values.
        # If not admin, maybe show empty or masked.
        current_settings['f95_username'] = '******'
        current_settings['f95_password'] = '******'
        current_settings['update_schedule_hours'] = '6' # Default display

    return render_template('settings.html', current_settings=current_settings, can_edit_global_settings=is_primary_admin)

@flask_app.route('/admin/users', methods=['GET'])
@login_required
def admin_users():
    if not session.get('is_admin'):
        abort(403) # Forbidden
    
    users = get_all_users_details(DB_PATH)
    return render_template('admin_users.html', users=users)

if __name__ == '__main__':
    # Ensure image cache dir exists
    if not os.path.exists(IMAGE_CACHE_DIR_FS):
        os.makedirs(IMAGE_CACHE_DIR_FS, exist_ok=True)
    
    flask_app.run(debug=True, host='0.0.0.0', port=5000)