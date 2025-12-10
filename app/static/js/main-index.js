document.addEventListener('DOMContentLoaded', function () {
    // Read data passed from the template
    const configElement = document.getElementById('app-config');
    const pushoverConfigMissing = configElement ? configElement.dataset.pushoverConfigMissing === 'true' : false;

    const toggleViewBtn = document.getElementById('toggle-view-btn');
    const playedGamesList = document.getElementById('played-games-list');

    function updateButtonTextContent(button, isGridView) {
        if (!button) return;
        if (isGridView) {
            button.textContent = 'Switch to List View';
        } else {
            button.textContent = 'Switch to Grid View';
        }
    }

    if (toggleViewBtn && playedGamesList) {
        let currentView = localStorage.getItem('gamesView') || 'list-view';

        playedGamesList.classList.remove('list-view', 'grid-view');
        playedGamesList.classList.add(currentView);
        updateButtonTextContent(toggleViewBtn, currentView === 'grid-view');

        toggleViewBtn.addEventListener('click', function () {
            const isListCurrently = playedGamesList.classList.contains('list-view');
            currentView = isListCurrently ? 'grid-view' : 'list-view';

            playedGamesList.classList.remove('list-view', 'grid-view');
            playedGamesList.classList.add(currentView);
            localStorage.setItem('gamesView', currentView);
            updateButtonTextContent(toggleViewBtn, currentView === 'grid-view');
        });
    }

    document.querySelectorAll('.sync-btn').forEach(function (button) {
        const form = button.closest('form');
        if (form) {
            form.addEventListener('submit', function () {
                const btn = this.querySelector('.sync-btn');
                if (btn) {
                    const syncText = btn.querySelector('.sync-text');
                    const syncSpinner = btn.querySelector('.sync-spinner');
                    if (syncText) syncText.style.display = 'none';
                    if (syncSpinner) syncSpinner.style.display = 'inline-block';
                    btn.disabled = true;
                }
            });
        }
    });

    if (pushoverConfigMissing) {
        // Check if the main content area is visible (i.e., user is on the main games tab)
        // This is a proxy to avoid showing this confirm dialog on other pages if this script is loaded globally
        const mainContentVisible = document.querySelector('.played-games-section');
        if (mainContentVisible) {
            if (window.confirm("Pushover notification details are not configured. Would you like to go to the settings page to add them?")) {
                // We need to get the URL for settings_route from the template, or hardcode if it's static
                // For now, assuming it might be available on a global window object or passed via another data attribute if needed.
                // Simplest for now: use a relative path if your app structure allows, or get it from a data attribute.
                const settingsUrl = configElement ? configElement.dataset.settingsUrl : '/settings';
                window.location.href = settingsUrl;
            }
        }
    }

    // Convert UTC dates to Local Time
    const localDateElements = document.querySelectorAll('.local-date');
    localDateElements.forEach(el => {
        const utcDateStr = el.getAttribute('data-utc');
        if (utcDateStr && utcDateStr !== 'None' && utcDateStr !== 'N/A') {
            const date = new Date(utcDateStr);
            if (!isNaN(date.getTime())) {
                const options = {
                    weekday: 'short',
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                };
                el.textContent = date.toLocaleString(undefined, options);
            }
        }
    });

}); 