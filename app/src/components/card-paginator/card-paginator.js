"use strict";

/**
 * @event
 * Handles errors generated by the application.
 * @param {String} message Error message
 * @param {String} source File where the error occurred
 * @param {number} lineno Line containing the instruction that generated the error
 * @param {number} colno Column containing the statement that generated the error
 * @param {Error} error Application generated error
 */
window.onerror = function (message, source, lineno, colno, error) {
    window.EM.onerror("card-paginator.js", {
        message: message,
        line: lineno,
        column: colno,
        error: error,
    });
};

class CardPaginator extends HTMLElement {
    constructor() {
        super();

        /**
         * Maximum number of selectors available at any time 
         * for the user to be used. It must be an odd value.
         */
        this.MAX_VISIBLE_PAGES = 5;
        /**
         * Maximum number of cards viewable per page.
         */
        this._cardsForPage = 8;
        /**
         * Dictionary used by NeDB to filter results from the database.
         * `{}` selects all records.
         * @type Object
         */
        this._searchQuery = {};
        /**
         * Dictionary used by NeDB to sort results from the database.
         * @type Object
         */
        this._sortQuery = {name: 1};
        /**
         * Function called when the `play` event occurs on a GameCard.
         * @type function
         */
        this._playEventListener = null;
        /**
         * Function called when the `update` event occurs on a GameCard.
         * @type function
         */
        this._updateEventListener = null;
        /**
         * Function called when the `delete` event occurs on a GameCard.
         * @type function
         */
        this._deleteEventListener = null;
        /**
         * Indicates whether the component is loading data.
         * @type Boolean
         */
        this._isLoading = false;
        /**
         * Current view of the paginator
         * @type String
         */
        this._currentView = 'list';
    }

    //#region Properties
    /**
     * Sets the function called when the `play` 
     * event occurs on a GameCard.
     * @param {function} f
     */
    set playListener(f) {
        this._playEventListener = f;
    }

    /**
     * Sets the function called when the `update` 
     * event occurs on a GameCard.
     * @param {function} f
     */
    set updateListener(f) {
        this._updateEventListener = f;
    }

    /**
     * Sets the function called when the `delete` 
     * event occurs on a GameCard.
     * @param {function} f
     */
    set deleteListener(f) {
        this._deleteEventListener = f;
    }
    //#endregion Properties

    /**
     * Triggered once the element is added to the DOM
     */
    connectedCallback() {
        // Prepare DOM
        this._prepareDOM();
        window.API.log.info("Paginator connected to DOM");

        // Set up view toggle
        this._currentView = 'list';
        this._updateViewClass();
        const toggleBtn = document.getElementById('toggle-view-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                // On mobile, always use list view
                if (window.innerWidth <= 600) return;
                this._currentView = this._currentView === 'list' ? 'grid' : 'list';
                this._updateViewClass();
                // Update button text/icon
                if (this._currentView === 'grid') {
                    toggleBtn.innerHTML = '<i class="material-icons left">view_list</i>Switch to List View';
                } else {
                    toggleBtn.innerHTML = '<i class="material-icons left">view_module</i>Switch to Grid View';
                }
            });
        }
        // Listen for resize to force list view on mobile
        window.addEventListener('resize', () => {
            if (window.innerWidth <= 600 && this._currentView !== 'list') {
                this._currentView = 'list';
                this._updateViewClass();
                if (toggleBtn) {
                    toggleBtn.innerHTML = '<i class="material-icons left">view_module</i>Switch to Grid View';
                }
            }
        });
    }

    //#region Events
    /**
     * @private
     * Select the page following the one currently active.
     * @param {MouseEvent} e
     */
    _nextPage(e) {
        // Ignore event if the button is disabled
        const disabled = e.target.parentNode.classList.contains("disabled");

        // Obtain the ID of the currently selected page selector
        const index = this._getCurrentIndex();

        // Switch page
        if (index !== -1 && !disabled) {
            this._switchContext(index + 1);
            window.API.log.info(`Switched context to ${index + 1} after user click (nextPage)`);
        }
    }

    /**
     * @private
     * Select the page preceding the one currently active.
     * @param {MouseEvent} e
     */
    _prevPage(e) {
        // Ignore event if the button is disabled
        const disabled = e.target.parentNode.classList.contains("disabled");

        // Obtain the ID of the currently selected page selector
        const index = this._getCurrentIndex();

        // Switch page
        if (index !== -1 && !disabled) {
            this._switchContext(index - 1);
            window.API.log.info(`Switched context to ${index - 1} after user click (prevPage)`);
        }
    }

    /**
     * @private
     * Select the first page.
     */
    _firstPage() {
        // Switch page
        this._switchContext(0);
        window.API.log.info("Switched context to 0 after user click (firstPage)");
    }

    /**
     * @private
     * Select the last page.
     */
    async _lastPage() {
        // Get the number of pages
        const nPages = await this._countPages();
        
        // Switch page
        this._switchContext(nPages - 1);
        window.API.log.info(`Switched context to ${nPages - 1} after user click (lastPage)`);
    }

    /**
     * @private
     * Generated when clicking on a selector, changes the displayed page.
     * @param {MouseEvent} e
     */
    async _selectPage(e) {
        const selectorID = e.target.parentNode.id;
        const index = parseInt(selectorID.replace("selector_", ""));
        const shouldSwitch = await this._shouldISwitch(index)
            .catch(e => window.API.reportError(e, "20101", "this._shoudISwitch", "_selectPage", `Index: ${index}`));
        if (shouldSwitch) {
            this._switchContext(index);
            window.API.log.info(`Switched context to ${index} after user click`);
        }
    }

    /**
     * Switch page when the right/left arrow on keyboard are pressed.
     * @param {KeyboardEvent} e
     */
    _keyboardShortcut(e) {
        // Local variables
        const keyPageMap = {
            ArrowRight: "#next-page",
            ArrowLeft: "#prev-page"
        };

        // Check if the key pressed is valid and 
        // avoid new query if the component is already loading
        const validShortcut = ["ArrowRight", "ArrowLeft"].includes(e.key);
        if (validShortcut && !this._isLoading) {

            // Obtain the ID of the currently selected page selector
            const index = this._getCurrentIndex();

            // Check if we are on the first/last page
            const selector = this.querySelector(keyPageMap[e.key]);
            const disabled = selector ? selector.classList.contains("disabled") : true;

            if (index !== -1 && !disabled) {
                // Calculate the new index
                const nextIndex = e.key === "ArrowRight" ? index + 1: index -1;

                // Switch page
                this._switchContext(nextIndex);
                window.API.log.info(`Switched context to ${nextIndex} after user shortcut`);
            }
        }
    }

    //#endregion Events

    //#region Public methods
    
    /**
     * @public
     * Load and show the first page of the records in the database.
     * @param {number} [index] Index of the page to show. Default: 0
     */
    async load(index = 0) {
        // Check if the switch is necessary
        const shouldSwitch = await this._shouldISwitch(index)
            .catch(e => window.API.reportError(e, "20102", "this._shoudISwitch", "load", `Index: ${index}`));
        
        // Avoid new query if the component is already loading
        if (shouldSwitch && !this._isLoading) {
            window.API.log.info(`Loading paginator at page ${index}`);
            this._switchContext(index);
        }
    }

    /**
     * @public
     * Find all games that contain the specified value in the title.
     * @param {String} name Case-sensitive value to search
     */
    async search(value) {
        const FIRST_PAGE = 0;
        
        // Build the query (regex with case insensitive)
        this._searchQuery = this._buildSearchQuery(value);
        
        // Check if the switch is necessary
        const shouldSwitch = await this._shouldISwitch(FIRST_PAGE)
            .catch(e => window.API.reportError(e, "20103", "this._shoudISwitch", "search", `Index: ${FIRST_PAGE}`));
        
        if (shouldSwitch && !this._isLoading) {
            window.API.log.info(`Searching for '${value}' in paginator`);
            
            // Load the first page
            this._switchContext(FIRST_PAGE);
        }
    }

    /**
     * @public
     * Reload the current page.
     * Useful after adding/removing a card.
     * @param {Boolean} [force] Force the reload
     */
    async reload(force) {
        // Get the current index
        const currentIndex = this._getCurrentIndex();
        const index = currentIndex !== -1 ? currentIndex : 0;

        // Check if the switch is necessary
        const shouldSwitch = await this._shouldISwitch(index)
            .catch(e => window.API.reportError(e, "20104", "this._shoudISwitch", "reload", `Index: ${index}`));
        
        if ((shouldSwitch || force) && !this._isLoading) {
            window.API.log.info(`Reloading page ${index}`);
            this._switchContext(index);
        }
    }

    /**
     * @public
     * Sort the gamecards with the specified method.
     * @deprecated Need improvement
     */
    sort(method) {
        // Avoid new query if the component is already loading
        if (this._isLoading) return;

        if(!method) this._sortQuery = {name: 1};
    }

    /**
     * @public
     * Set the number of visible cards based on the parent's window size.
     * @param {Number[]} size Size of the parent
     */
    visibleCardsOnParentSize(size) {
        // Destructure the array
        const [width, height] = size;

        // Card size
        const cardWidth = 300;
        const cardHeight = 400;
        
        // Get the number of rows and columns that can be visible if appended
        const MAX_COLUMNS = 4;
        const columns = Math.min(Math.floor(width / cardWidth), MAX_COLUMNS);
        const rows = Math.floor(height/cardHeight);

        // Set at least 1 cards
        const candidateCards = columns * rows;
        this._cardsForPage = Math.max(1, candidateCards);

        // Reload page
        this.reload();
    }
    //#endregion Public methods

    //#region Private methods

    /**
     * Load the HTML file and define the buttons of the custom component.
     */
    _prepareDOM() {
        /* Defines the HTML code of the custom element */
        const template = document.createElement("template");
        
        /* Synchronous read of the HTML template */
        const pathHTML = window.API.join(
            window.API.appDir,
            "src",
            "components",
            "card-paginator",
            "card-paginator.html"
        );
        template.innerHTML = window.IO.readSync(pathHTML);
        this.appendChild(template.content.cloneNode(true));
        
        /* Define elements in DOM */
        this.root = this.querySelector("#paginator-root");
        this.content = this.querySelector("#pagination-content");
        this.pageSelectorsParent = this.querySelector("#pagination-page-selectors");
        this.preload = document.querySelector(".pagination-preload");

        /* Bind function to use this */
        this._countPages = this._countPages.bind(this);
        this._getCurrentIndex = this._getCurrentIndex.bind(this);
        this._manageNextPrecButtons = this._manageNextPrecButtons.bind(this);
        this._createSelectorButton = this._createSelectorButton.bind(this);
        this._createPrevButton = this._createPrevButton.bind(this);
        this._createNextButton = this._createNextButton.bind(this);
        this._keyboardShortcut = this._keyboardShortcut.bind(this);
        this._prevPage = this._prevPage.bind(this);
        this._nextPage = this._nextPage.bind(this);
        this._firstPage = this._firstPage.bind(this);
        this._lastPage = this._lastPage.bind(this);
        this._switchPage = this._switchPage.bind(this);
        this._selectPage = this._selectPage.bind(this);
        this._getStartEndPages = this._getStartEndPages.bind(this);
        this._switchContext = this._switchContext.bind(this);
        this._createPageSelectors = this._createPageSelectors.bind(this);
        this.visibleCardsOnParentSize = this.visibleCardsOnParentSize.bind(this);

        /* Add keyboard hooks */
        window.addEventListener("keydown", this._keyboardShortcut, true);
        
        window.API.log.info("Paginator prepared");
    }

    //#region Utility
    /**
     * @private
     * Count the number of pages that will be fetched with the current settings.
     */
    async _countPages() {
        const recordsNumber = await window.GameDB.count(this._searchQuery)
            .catch(e => window.API.reportError(e, "20108", "window.GameDB.count", "_countPages", `Query: ${this._searchQuery}`));
        return Math.ceil(recordsNumber / this._cardsForPage);
    }

    /**
     * @private
     * Gets the ID of the currently selected page selector.
     */
    _getCurrentIndex() {
        // Local variables
        let index = -1;

        // Get the active page, if none is found return -1
        const activePage = this.querySelector("li.active");
        if(activePage) {
            // Parse and return the current index
            index = parseInt(activePage.id.replace("selector_", ""), 10);
        }
        return index;
    }

    /**
     * @private
     * Shows or hides the buttons for the previous/next page 
     * depending on the currently selected page selector.
     */
    async _manageNextPrecButtons() {
        // Get the elements
        const index = this._getCurrentIndex();
        if(index === -1) return;

        // Get elements
        const prevPageSelector = this.querySelector("#prev-page");
        const nextPageSelector = this.querySelector("#next-page");
        
        // Manage the prev button
        let toAdd = index === 0 ? "disabled" : "enabled";
        let toRemove = index === 0 ? "enabled" : "disabled";
        prevPageSelector.classList.remove(toRemove);
        prevPageSelector.classList.add(toAdd);

        // Manage the next button
        const nPages = await this._countPages();
        toAdd = index === nPages - 1 ? "disabled" : "enabled";
        toRemove = index === nPages - 1 ? "enabled" : "disabled";
        nextPageSelector.classList.remove(toRemove);
        nextPageSelector.classList.add(toAdd);
    }

    /**
     * @private
     * Obtains the records of the page specified by `index`.
     * @param {number} index Index of the page to prepare
     * @param {number} size Size of each page
     * @returns {Promise<Object[]>} List of records fetched from the database
     */
    async _paginate(index, size) {
        return await window.GameDB.search(this._searchQuery, this._sortQuery, index, size, size)
            .catch(e => window.API.reportError(e, "20105", "window.GameDB.search", "_paginate"));
    }

    /**
     * @private
     * Load the page with the index used as argument.
     * @param {number} index Index of the page to load
     */
    async _switchPage(index) {
        // Get the properties of the selected records
        const records = await this._paginate(index, this._cardsForPage)
            .catch(e => window.API.reportError(e, "20106", "this._paginate", "_switchPage"));

        // Remove all columns
        const elements = this.content.querySelectorAll("div.col");
        elements.forEach(e => e.remove());

        // Create the game-cards
        const cardsPromiseLoad = [];
        const cards = [];
        for(const r of records) {
            const gamecard = document.createElement("game-card");
            gamecard.addEventListener("play", this._playEventListener);
            gamecard.addEventListener("update", this._updateEventListener);
            gamecard.addEventListener("delete", this._deleteEventListener);
            const promise = gamecard.loadData(r._id);

            cards.push(gamecard);
            cardsPromiseLoad.push(promise);
        }

        // Wait for all the cards to be loaded
        await Promise.all(cardsPromiseLoad)
            .catch(e => window.API.reportError(e, "20107", "Promise.all", "_switchPage"));

        for(const card of cards) {
            // Create responsive column
            const column = this._createGridColumn();

            // Append card to DOM
            this.content.appendChild(column);
            column.appendChild(card);

            // Check for game updates AFTER the card is attached to DOM
            card.checkUpdate();
        }
    }

    /**
     * @private
     * Gets the range of page indexes to display "around" the index passed as a parameter.
     * @param {number} index Index of the page to be displayed
     */
    async _getStartEndPages(index) {
        // Local variables
        const nPages = await this._countPages();

        // If there aren't enough pages...
        if (nPages <= this.MAX_VISIBLE_PAGES) {
            if (index < 0 || index > nPages) {
                throw new Error(`index (${index}) must be between (0) and (${nPages})`);
            }
            return {
                start: 0,
                end: nPages - 1,
            };
        }

        // ...else, get the side number of visible page selectors
        const pageSideRange = Math.floor((this.MAX_VISIBLE_PAGES / 2));
        let start = index - pageSideRange;
        let end = index + pageSideRange;

        // Manage the "border" cases
        if (start < 0) {
            start = 0;
            end = this.MAX_VISIBLE_PAGES - 1;
        }
        if (end > nPages - 1) {
            start = nPages - this.MAX_VISIBLE_PAGES - 1;
            end = nPages - 1;
        }

        return {
            start: start,
            end: end,
        };
    }

    /**
     * @private
     * Change the page, showing the content and setting the page selectors appropriately.
     * @param {number} index Index of the page to be displayed
     */
    _switchContext(index) {
        // Define function
        const animationOnSwitchContext = (async () => {
            // Check if the page is altready loading
            if (!this._isLoading) {
                // Set global variable
                this._isLoading = true;

                // Show a circle preload and hide the content
                this.preload.style.display = "flex";
                this.content.style.display = "none";

                // Load the first page
                await this._switchPage(index)
                    .catch(e => window.API.reportError(e, "20109", "this._switchPage", "animationOnSwitchContext", `Index: ${index}`));

                // Prepare the page selectors
                const limitPages = await this._getStartEndPages(index)
                    .catch(e => window.API.reportError(e, "20110", "this._getStartEndPages", "animationOnSwitchContext", `Index: ${index}`));

                // Remove all the page selectors
                this.pageSelectorsParent.querySelectorAll("li").forEach(n => n.remove());

                // Avoid creating selectors if there are no pages
                if (limitPages.end - limitPages.start > 0) {
                    await this._createPageSelectors(limitPages.start, limitPages.end + 1, index);

                    // Set the current page as active
                    const current = this.pageSelectorsParent.querySelector(`#selector_${index}`);
                    current.classList.add("active");

                    // Enable/disable the next/prev buttons
                    await this._manageNextPrecButtons()
                        .catch(e => window.API.reportError(e, "20111", "this._manageNextPrecButtons", "animationOnSwitchContext"));
                }

                // Hide the circle preload and show the content
                this.preload.style.display = "none";
                this.content.style.display = "block";

                // Set global variable
                this._isLoading = false;
            }
        });

        // Execute switch
        window.requestAnimationFrame(animationOnSwitchContext);
    }

    /**
     * @private
     * Check if a query produces new results to be paged 
     * or if you can avoid doing so because the new values 
     * are the same as those already present.
     * @param {number} index Index of the new page to be displayed
     */
    async _shouldISwitch(index) {
        // Get the records that should be paginated
        const records = await this._paginate(index, this._cardsForPage);
        const toPaginateIDs = records.map(r => r.id); // Obtains the game ID's

        // Get the records that are in the page
        const gamecards = this.content.querySelectorAll("game-card");
        const paginatedIDs = Array.from(gamecards).map(g => g.info.id); // Obtains the game ID's

        // Check the lenght because "checker" check only 
        // if an array contains, not if it is equals.
        // See https://stackoverflow.com/questions/53606337/check-if-array-contains-all-elements-of-another-array
        if(toPaginateIDs.length !== paginatedIDs.length) return true;

        /**
         * Check if the elements of `arr` are all contained in `target`.
         * @param {Array} arr 
         * @param {Array} target 
         */
        const checker = (arr, target) => target.every(v => arr.includes(v));

        return !checker(toPaginateIDs, paginatedIDs);
    }

    /**
     * @private
     * Build the search querywith the given parameters
     * @param {String} name Name of the game
     */
    _buildSearchQuery(name) {
        // Local variables
        let query = {};

        if (name.trim() !== "") {
            const re = new RegExp(name, "i");
            query = {
                name: re
            };
        }
        return query;
    }
    //#endregion Utility

    //#region Creation
    /**
     * @private
     * Create the button to select the previous page selector.
     */
    _createPrevButton() {
        const prev = document.createElement("li");
        prev.classList.add("waves-effect");
        prev.id = "prev-page";
        prev.onclick = this._prevPage;

        // Create and add the icon
        const icon = document.createElement("a");
        icon.classList.add("material-icons", "md-chevron_left");
        prev.appendChild(icon);

        return prev;
    }

    /**
     * @private
     * Create the button to select the next page selector.
     */
    _createNextButton() {
        const next = document.createElement("li");
        next.classList.add("waves-effect");
        next.id = "next-page";
        next.onclick = this._nextPage;

        // Create and add the icon
        const icon = document.createElement("a");
        icon.classList.add("material-icons", "md-chevron_right");
        next.appendChild(icon);

        return next;
    }

    /**
     * @private
     * Create the button to select the first page.
     */
    _createFirstPageButton() {
        const selector = document.createElement("li");
        selector.classList.add("waves-effect");
        selector.id = "first-page";
        selector.onclick = this._firstPage;

        // Create and add the icon
        const icon = document.createElement("a");
        icon.classList.add("material-icons", "md-first_page");
        selector.appendChild(icon);

        return selector;
    }

    /**
     * @private
     * Create the button to select the last page.
     */
    _createLastPageButton() {
        const selector = document.createElement("li");
        selector.classList.add("waves-effect");
        selector.id = "last-page";
        selector.onclick = this._lastPage;

        // Create and add the icon
        const icon = document.createElement("a");
        icon.classList.add("material-icons", "md-last_page");
        selector.appendChild(icon);

        return selector;
    }

    /**
     * @private
     * Create a generic page selector.
     * @param {number} index Index of the page associated with the selector
     */
    _createSelectorButton(index) {
        const li = document.createElement("li");
        li.id = `selector_${index}`;
        li.classList.add("waves-effect");

        // Create the page number
        const a = document.createElement("a");
        a.innerText = index + 1;
        li.appendChild(a);

        // Add the event listener
        li.onclick = this._selectPage;
        return li;
    }

    /**
     * @private
     * Create a responsive column that will hold a single gamecard.
     */
    _createGridColumn() {
        // Create a simil-table layout with materialize-css
        // "s10" means that the element occupies 10 of 12 columns with small screens
        // "offset-s2" means that on small screens 2 of 12 columns are spaced (from left)
        // "m5" means that the element occupies 5 of 12 columns with medium screens
        // "offset-m1" means that on medium screens 1 of 12 columns are spaced (from left)
        // "l4" means that the element occupies 4 of 12 columns with large screens
        // "xl3" means that the element occupies 3 of 12 columns with very large screens
        // The 12 columns are the base layout provided by materialize-css
        const column = document.createElement("div");
        column.classList.add("col", "s10", "offset-s2", "m5", "offset-m1", "l4", "xl3");
        return column;
    }

    /**
     * @private
     * Creates page selectors with index between `start` and `end`.
     * @param {number} start Create pages from the one with this index
     * @param {number} end Create pages up to this index (excluded)
     * @param {number} selected Selector index to be selected from those created
     */
    async _createPageSelectors(start, end, selected) {
        // Validate parameters
        if(selected < start || selected > end) 
            throw new Error(`selected (${selected}) must be between start (${start}) and end (${end})`);
        
        if(start > end) {
            throw new Error("Start greater than end");
        }

        // Create and adds the page selectors
        for (let i = start; i < end; i++) {
            const li = this._createSelectorButton(i);
            this.pageSelectorsParent.appendChild(li);
        }

        // Create the first/last page selector
        const first = this._createFirstPageButton();
        const last = this._createLastPageButton();

        // Add the first page selector as first child
        // then the last page selector
        if (start > 0) this.pageSelectorsParent.insertBefore(first, this.pageSelectorsParent.firstChild);
        if (end < (await this._countPages()) - 1) this.pageSelectorsParent.appendChild(last);

        // Create the previous/next page selector
        const prev = this._createPrevButton();
        const next = this._createNextButton();

        // Add the previous page selector as first child
        // then the next page selector
        this.pageSelectorsParent.insertBefore(prev, this.pageSelectorsParent.firstChild);
        this.pageSelectorsParent.appendChild(next);
    }
    //#endregion Creation

    //#endregion Private methods

    //#region View toggle
    /**
     * @private
     * Update the view class of the content based on the current view
     */
    _updateViewClass() {
        if (!this.content) return;
        this.content.classList.remove('grid-view', 'list-view');
        if (this._currentView === 'grid' && window.innerWidth > 600) {
            this.content.classList.add('grid-view');
        } else {
            this.content.classList.add('list-view');
        }
    }
    //#endregion View toggle
}

// Let the browser know that <card-paginator> is served by our new class
customElements.define("card-paginator", CardPaginator);