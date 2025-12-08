# Next Steps & Potential Enhancements for YAM

## Quality of Life (QoL) / Small Enhancements

These are generally smaller changes that could improve the existing user experience:

### UI/UX Improvements

*   **Bulk Actions**: Allow users to select multiple games in their list (or from search results) to perform actions like:
    *   Add to monitored list (from search).
    *   Delete from monitored list.
    *   Acknowledge updates.
*   **Enhanced Filtering & Sorting**: On the main game list page, provide more advanced filtering options (e.g., filter by multiple custom tags, by "status" like "Ongoing/Completed/Abandoned", by unacknowledged updates, by date added). Add more sorting options (e.g., sort by last acknowledged date, date added).
*   **Clearer Visual Cues**:
    *   Use more distinct visual indicators (e.g., color-coded tags or icons) for different game statuses (Ongoing, Completed, On-Hold, Abandoned, Unacknowledged Update).
    *   Clearly display when each game was last checked for updates by the system.
*   **Customizable Dashboard View**: Allow users to perhaps re-order sections on the main page or choose which information blocks are visible.
*   **Persistent Filters**: Remember the user's last used filter and sort settings on the game list page.

### Notification Enhancements

*   **Additional Notification Channels**: Beyond Pushover, consider adding support for:
    *   Native desktop notifications.
    *   Discord webhooks.
    *   Telegram bots.
*   **"Test Notification" Button**: In the settings page, allow users to send a test notification to verify their setup for the selected channel.
*   **Snooze Game Notifications**: Option to temporarily mute notifications for a specific game for a defined period (e.g., 1 week, 1 month).

### Game Management Improvements

*   **Custom User Tags/Categories**: Allow users to create and assign their own tags or categories to games for better organization (e.g., "Favorite", "To Play Next", genre sub-categories).
*   **"Mark as Played/Finished"**: A user-defined status, separate from F95Zone's "Completed", to indicate they have personally finished playing a game.
*   **Wishlist Functionality**: A separate section or tag for games users are interested in but aren't actively monitoring for updates yet.
*   **Import/Export User Data**: Allow users to export their monitored games list (including notes, ratings, acknowledged status) to a common format (JSON, CSV) and import it back. This is useful for backups or migrating between YAM instances.

### General User Experience

*   **In-App Changelog**: When the application updates, show a brief list of new features or bug fixes.
*   **Better Progress Indicators**: For potentially long-running actions like "Manual Sync All" or initial large searches, provide more detailed progress feedback in the UI.

## Larger Feature Additions

These are more significant features that would add new capabilities:

### Expanded Game Information & Discovery

*   **Link to Other Game Databases**: For a tracked game, provide quick links to its page on other relevant platforms (e.g., VNDB, Steam, itch.io, or other F95-like sites if the game is available elsewhere).
*   **"More Like This" Recommendations**: Based on a game a user has rated highly or plays often, suggest other games from F95Zone with similar tags, author, or from a simple collaborative filter if ratings are available.
*   **Advanced F95Zone Search Integration**: If feasible through the F95Zone API/RSS (or by carefully targeted direct queries if necessary), allow more granular search filters from within YAM (e.g., by specific F95Zone tags, game engine, excluding certain tags).

### Enhanced Game Tracking & Details

*   **Track Game Size/Changelogs (if available)**: If F95Zone provides information on game download size or links to developer changelogs, try to capture and display this. This is often not in RSS, so it might be difficult.
*   **User-Provided Cover Images**: Allow users to upload/link their own preferred cover image for a game if they don't like the one fetched or if none is available.

### Core Functionality Enhancements

*   **Unified User Data**: Implement a robust mechanism to synchronize user data (monitored games, notes, ratings, notification settings, acknowledged statuses) with the Python web backend. This would allow a user to use the web interface and have a consistent view. This could involve the Python backend exposing a proper API.

### Expanded Content Support

*   **Track Developers/Authors**: Allow users to "follow" specific F95Zone authors and get notified when they release a new game or update an existing one.
*   **(Ambitious) Extend tracking to other adult game platforms** or even general indie sites like itch.io, if there's user demand and feasible APIs/RSS feeds.

### Community Features (Optional & Privacy-Conscious)

*   **Anonymous Statistics**: Opt-in feature to share anonymous data about what games are popular or highly rated among YAM users, providing a "trending" or "community recommended" section.
*   **Shareable Lists (Anonymized)**: Allow users to generate a shareable link to an anonymized version of their game list or a specific subset (e.g., "My Top 10 Completed Games").

## Technical & Architectural Suggestions

These suggestions focus on the underlying structure and could indirectly benefit users through improved stability, maintainability, and a foundation for future features:

*   **Centralized API**: Refactor the Python backend to expose a clear API that any potential web interface would consume. This would reduce code duplication (e.g., F95Zone client logic) and make data synchronization more straightforward.
*   **Robust Database Migrations**: Implement a proper database migration system (e.g., Alembic if fully committing to SQLAlchemy, or a simpler custom solution for SQLite) for the Python backend to handle schema changes more gracefully than just adding columns.
*   **Full SQLAlchemy Integration**: Since SQLAlchemy is a dependency, consider fully utilizing its ORM capabilities for all database interactions in the Python backend. This can simplify queries, improve code readability, and work well with migration tools.

### Potential Future Enhancements & Ideas:

*   **Advanced Filtering & Sorting**: Allow users to filter their game list by more complex criteria (e.g., multiple tags, release date ranges, unplayed games with high ratings) and save these as custom views.
*   **User Themes & Customization**: Allow users to select different themes for the application or even customize colors and fonts.
*   **Game Statistics & Insights**: Show users interesting statistics about their library (e.g., most played genres, average playtime, completion rate).
*   **"Play Next" Suggester**: Based on user ratings, play history, or tags, suggest which game the user might want to play next.
*   **Integration with Other Platforms**: (Optional, complex) Link with Steam, GOG, etc., to see if F95zone games are owned on other platforms or to launch them.
*   **Improved Tag Management**: More robust UI for adding, removing, and editing tags for games. Perhaps a dedicated tag management page.
*   **Community Features (If F95Zone API Allows)**:
    *   View community ratings or reviews directly in the app.
    *   Share game lists or recommendations (anonymously or with F95Zone friends).
*   **Better Mod Handling**: If a game has mods listed on F95zone, provide a way to track/manage them.
*   **Calendar View**: Show upcoming game releases or personal play schedules.
*   **Bulk Editing**: Allow users to edit properties (like status, tags) for multiple games at once.
*   **Image/Cover Management**: Allow users to set custom cover images for games if they don't like the one fetched or if none is available.
*   **Language Support / i18n**: The current structure has `lang/en.json` and `lang/original/en.json`. Properly implement internationalization throughout the application.
    *   Use a library like `Flask-Babel` for the backend.
    *   Ensure all user-facing strings are translatable.
*   **Data Backup & Restore**: Allow users to easily back up their game data (library, statuses, settings) and restore it. This could be a simple JSON export/import.
*   **Configuration for F95Zone Client**: Allow users to configure aspects of the F95Zone client (e.g., request timeouts, retry attempts) via the UI.
*   **Accessibility Improvements (WCAG)**: Ensure the application is usable by people with disabilities.
*   **Plugin/Extension System**: (Very Ambitious) Allow community developers to create plugins to extend YAM's functionality.
*   **"Surprise Me" / Random Game Picker**: A button to pick a random game from the user's library (perhaps with filters like "unplayed").
*   **Tutorial / Onboarding**: For new users, a quick tour of the main features.

### Technical & Architectural Enhancements:

*   **Comprehensive API Documentation**: If the backend API is expanded (see below), document it thoroughly (e.g., using Swagger/OpenAPI).
*   **Automated E2E Testing**: Implement end-to-end tests for critical user flows.
*   **CI/CD Pipeline Refinements**:
    *   Automated builds for different platforms.
    *   Automated deployment (if applicable, e.g., to a staging server or a release page).
*   **Performance Optimization**:
    *   Database query optimization.
    *   Efficient loading of large game libraries.
*   **Security Audit & Hardening**:
    *   Review dependencies for vulnerabilities.
    *   Ensure proper input sanitization.
    *   CSRF protection, XSS prevention for web parts.
*   **Refactor F95Zone Client**:
    *   The `f95apiclient` seems to be a custom implementation. Consider if it can be made more robust, error-handled, or even replaced/contributed to if there's a more standard community library.
    *   Ensure it handles API rate limits gracefully.
*   **Database Schema Migrations**: If the database schema (SQLite) evolves, implement a migration system (e.g., using Alembic for Flask).
*   **Configuration Management**: Centralize and improve how application settings are managed (e.g., moving from `config.py` to environment variables or a more robust config file format).
*   **Logging Improvements**: Standardize logging format, levels, and output (e.g., rotate logs, allow configuring log verbosity).
*   **Background Task Management**: For long-running operations (like full library scans), use a proper background task queue (e.g., Celery with Redis/RabbitMQ). The current `threading` approach might not scale well or offer good error handling/monitoring.
*   **Web UI Enhancements**:
    *   Modernize the JavaScript used (e.g., use a simple framework like Vue.js or Svelte for more dynamic components, or at least organize vanilla JS better).
    *   Improve CSS, perhaps using a utility-first framework or better BEM structuring.

Remember to consult the `README.md` and existing `docs/` for more context on the current application structure.

---
*When considering these, it's good to think about the effort involved versus the potential benefit to your target users. Some QoL changes can significantly improve daily use with relatively less effort, while larger features can expand the app's appeal but require more planning and development.*

### Docker & Deployment:

*   Simplify Docker setup. The `docker-compose.windows.yml` is a bit unusual. Aim for a single `docker-compose.yml` that works across platforms if possible, or clear instructions.
*   Provide a `Dockerfile` that builds a production-ready image.
*   Consider a `wait-for-it.sh` script or similar in Docker to ensure dependencies (like a database, if used) are ready before the app starts.

### Documentation & Developer Experience:

*   **Detailed Setup Guide**: For developers wanting to contribute.
*   **Architectural Overview Diagram**: A visual representation of how components interact.
*   **Code Style & Linting**: Enforce a consistent code style (e.g., Black, Flake8 for Python; Prettier for JS/HTML/CSS).
*   **Update `requirements.txt`**: Ensure it reflects the actual minimal dependencies.
*   **Clean up `NEXT_STEPS.md`**: Remove completed items or integrate them into a roadmap.
*   **Contribution Guidelines**: `CONTRIBUTING.md`.

### Database & Data Management (Python Backend):

*   **SQLAlchemy Models**: Define SQLAlchemy models for all database tables (`app/db/schemas.py` seems to be a start but isn't fully integrated or used in `app.py` for queries like `UPDATE games SET ...`).
*   **Consistent DB Interaction**: Use SQLAlchemy ORM for all DB operations in `app.py` instead of raw SQL queries. This improves type safety, reduces SQL injection risks, and makes code more maintainable.
*   **Robust Database Migrations**: Implement a proper database migration system (e.g., Alembic if fully committing to SQLAlchemy, or a simpler custom solution for SQLite) for the Python backend to handle schema changes more gracefully than just adding columns.
*   **Full SQLAlchemy Integration**: Since SQLAlchemy is a dependency, consider fully utilizing its ORM capabilities for all database interactions in the Python backend. This can simplify queries, improve code readability, and work well with migration tools.