// Global state
let currentScanId = null;
let socket = null;
let detailsPollingInterval = null; // Polling interval for scan details
let detailsBulkPollingInterval = null;
let detailsBulkRunning = false;
let modalReturnHash = 'history';
window.currentScanResults = []; // Store results for modal access
window.favoriteSlugs = new Set(); // Fast lookup for favorite state
const SYSTEM_STATUS_POLL_INTERVAL = 15000;
const SIDEBAR_PREF_KEY = 'wp-hunter-sidebar-collapsed';
const STAR_STRIP_PREF_KEY = 'wp-hunter-star-strip-hidden';
const TAB_TO_VIEW = {
    scan: 'new-scan',
    catalog: 'database',
    history: 'history',
    favorites: 'favorites',
    semgrep: 'semgrep-rules',
    details: 'details',
    'plugin-detail': 'plugin-detail',
};
const VIEW_TO_TAB = {
    'new-scan': 'scan',
    database: 'catalog',
    history: 'history',
    favorites: 'favorites',
    'semgrep-rules': 'semgrep',
    details: 'details',
    'plugin-detail': 'plugin-detail',
};
const RANDOM_PAGES_MIN = 1;
const RANDOM_PAGES_MAX = 50;
const PAGES_FIXED_ATTR = 'data-pages-fixed';
let systemStatusTimer = null;
window.systemStatus = null;
let lastSystemErrorMessage = "";
let lastSystemUpdateMessage = "";
let announcedUpdateVersion = "";

function applySidebarState(collapsed) {
    const layout = document.querySelector('.layout');
    const toggleBtn = document.getElementById('sidebar-toggle');
    const isMobile = window.matchMedia('(max-width: 800px)').matches;

    if (!layout || !toggleBtn) return;

    if (isMobile) {
        layout.classList.remove('sidebar-collapsed');
        toggleBtn.setAttribute('aria-expanded', 'true');
        toggleBtn.setAttribute('aria-label', 'Collapse sidebar');
        toggleBtn.title = 'Collapse sidebar';
        return;
    }

    layout.classList.toggle('sidebar-collapsed', collapsed);
    toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggleBtn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    toggleBtn.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
}

window.toggleSidebarCollapse = function() {
    const layout = document.querySelector('.layout');
    if (!layout) return;

    const isMobile = window.matchMedia('(max-width: 800px)').matches;
    if (isMobile) {
        applySidebarState(false);
        localStorage.setItem(SIDEBAR_PREF_KEY, '0');
        return;
    }

    const willCollapse = !layout.classList.contains('sidebar-collapsed');
    applySidebarState(willCollapse);
    localStorage.setItem(SIDEBAR_PREF_KEY, willCollapse ? '1' : '0');
};

function initializeSidebarToggle() {
    const toggleBtn = document.getElementById('sidebar-toggle');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', window.toggleSidebarCollapse);

    const savedCollapsed = localStorage.getItem(SIDEBAR_PREF_KEY) === '1';
    applySidebarState(savedCollapsed);

    window.addEventListener('resize', () => {
        const shouldCollapse = window.matchMedia('(max-width: 800px)').matches
            ? false
            : localStorage.getItem(SIDEBAR_PREF_KEY) === '1';
        applySidebarState(shouldCollapse);
    });
}

function initializeStarStripDismiss() {
    const starStrip = document.querySelector('.star-strip');
    const closeBtn = document.getElementById('star-strip-close');
    if (!starStrip || !closeBtn) return;

    const setStarStripHidden = (hidden) => {
        starStrip.classList.toggle('is-hidden', hidden);
        document.body.classList.toggle('star-strip-hidden', hidden);
    };

    const hidden = localStorage.getItem(STAR_STRIP_PREF_KEY) === '1';
    setStarStripHidden(hidden);

    closeBtn.addEventListener('click', () => {
        setStarStripHidden(true);
        localStorage.setItem(STAR_STRIP_PREF_KEY, '1');
    });
}

// Prevent stale API responses that force manual F5
const _nativeFetch = window.fetch.bind(window);
window.fetch = function(resource, options = {}) {
    const isApiCall = typeof resource === 'string' && resource.startsWith('/api/');
    if (!isApiCall) return _nativeFetch(resource, options);

    const headers = { ...(options.headers || {}) };
    if (!headers['Cache-Control']) headers['Cache-Control'] = 'no-cache';
    if (!headers['Pragma']) headers['Pragma'] = 'no-cache';

    return _nativeFetch(resource, {
        ...options,
        cache: 'no-store',
        headers
    });
};

function isDetailsViewActive() {
    const detailsView = document.getElementById('scan-details-view');
    return !!detailsView && detailsView.style.display !== 'none';
}

function apiNoCacheUrl(path) {
    const sep = path.includes('?') ? '&' : '?';
    return `${path}${sep}_ts=${Date.now()}`;
}

function getPagesInput() {
    return document.querySelector('#configForm input[name="pages"]');
}

function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function clampPagesValue(value) {
    if (!Number.isFinite(value)) return randomInt(RANDOM_PAGES_MIN, RANDOM_PAGES_MAX);
    return Math.max(RANDOM_PAGES_MIN, Math.min(RANDOM_PAGES_MAX, value));
}

function isPagesFixedByUser() {
    const input = getPagesInput();
    return !!input && input.getAttribute(PAGES_FIXED_ATTR) === '1';
}

function setRandomPagesValue(force = false) {
    const input = getPagesInput();
    if (!input) return;
    if (!force && isPagesFixedByUser()) return;
    input.value = String(randomInt(RANDOM_PAGES_MIN, RANDOM_PAGES_MAX));
    if (!isPagesFixedByUser()) {
        input.setAttribute(PAGES_FIXED_ATTR, '0');
    }
}

function initializePagesAutoRandom() {
    const input = getPagesInput();
    if (!input) return;

    input.setAttribute(PAGES_FIXED_ATTR, '0');
    input.min = String(RANDOM_PAGES_MIN);
    input.max = String(RANDOM_PAGES_MAX);

    const markFixedOrRandom = () => {
        const raw = String(input.value || '').trim();
        if (!raw) {
            input.setAttribute(PAGES_FIXED_ATTR, '0');
            setRandomPagesValue(true);
            return;
        }

        const parsed = Number.parseInt(raw, 10);
        if (!Number.isFinite(parsed)) {
            input.setAttribute(PAGES_FIXED_ATTR, '0');
            setRandomPagesValue(true);
            return;
        }

        const clamped = clampPagesValue(parsed);
        input.value = String(clamped);
        input.setAttribute(PAGES_FIXED_ATTR, '1');
    };

    input.addEventListener('input', () => {
        const raw = String(input.value || '').trim();
        if (!raw) {
            input.setAttribute(PAGES_FIXED_ATTR, '0');
            return;
        }
        const parsed = Number.parseInt(raw, 10);
        if (Number.isFinite(parsed)) {
            input.setAttribute(PAGES_FIXED_ATTR, '1');
        }
    });

    input.addEventListener('blur', markFixedOrRandom);

    setRandomPagesValue(true);
}

function preparePagesValueBeforeScan() {
    const input = getPagesInput();
    if (!input) return randomInt(RANDOM_PAGES_MIN, RANDOM_PAGES_MAX);
    if (!isPagesFixedByUser()) {
        setRandomPagesValue(true);
    }
    const parsed = Number.parseInt(String(input.value || ''), 10);
    const clamped = clampPagesValue(parsed);
    input.value = String(clamped);
    return clamped;
}

function refreshAfterScanEvent(sessionId) {
    loadHistory();
    const catalogView = document.getElementById('catalog-view');
    if (catalogView && catalogView.style.display !== 'none') {
        loadCatalog();
    }
    if (!sessionId) return;

    // If user is already on this scan details view, force-refresh it after DB flush.
    if (isDetailsViewActive() && currentScanId === sessionId) {
        setTimeout(() => { if (currentScanId === sessionId) viewScan(sessionId); }, 250);
        setTimeout(() => { if (currentScanId === sessionId) viewScan(sessionId); }, 1200);
    }
}

async function syncFinalScanResults(sessionId, expectedCount = 0) {
    if (!sessionId || !isDetailsViewActive()) return;
    const targetCount = parseInt(expectedCount || 0);
    for (let i = 0; i < 6; i++) {
        if (currentScanId !== sessionId) return;
        await viewScan(sessionId);
        const currentCount = (window.currentScanResults || []).length;
        if (targetCount <= 0 || currentCount >= targetCount) return;
        await new Promise(r => setTimeout(r, 350 * (i + 1)));
    }
}

// Custom Confirm Implementation
window.showConfirm = function(message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const msgEl = document.getElementById('confirm-message');
        const btnYes = document.getElementById('btn-confirm-yes');
        const btnCancel = document.getElementById('btn-confirm-cancel');

        if (!modal || !msgEl || !btnYes || !btnCancel) {
            // Fallback if modal elements missing
            resolve(window.confirm(message));
            return;
        }

        msgEl.textContent = message;
        modal.classList.add('active');

        // Handlers to cleanup and resolve
        function handleYes() {
            cleanup();
            resolve(true);
        }

        function handleCancel() {
            cleanup();
            resolve(false);
        }

        function cleanup() {
            modal.classList.remove('active');
            btnYes.removeEventListener('click', handleYes);
            btnCancel.removeEventListener('click', handleCancel);
        }

        // Add one-time listeners
        btnYes.addEventListener('click', handleYes);
        btnCancel.addEventListener('click', handleCancel);
    });
}

// Custom Toast Implementation
window.showToast = function(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');

    // Style logic
    let bg = '#141416';
    let color = '#fff';
    let border = '#333';

    if (type === 'success') { bg = 'rgba(0, 255, 157, 0.1)'; color = '#00FF9D'; border = 'rgba(0, 255, 157, 0.3)'; }
    if (type === 'error') { bg = 'rgba(255, 0, 85, 0.1)'; color = '#FF0055'; border = 'rgba(255, 0, 85, 0.3)'; }
    if (type === 'warn') { bg = 'rgba(255, 189, 46, 0.1)'; color = '#FFBD2E'; border = 'rgba(255, 189, 46, 0.3)'; }
    if (type === 'info') { bg = 'rgba(0, 243, 255, 0.1)'; color = '#00F3FF'; border = 'rgba(0, 243, 255, 0.3)'; }

    toast.style.cssText = `
        background: ${bg};
        color: ${color};
        border: 1px solid ${border};
        padding: 12px 15px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        min-width: 250px;
        max-width: 400px;
        animation: slideIn 0.3s ease-out forwards;
        display: flex;
        align-items: center;
        gap: 12px;
        backdrop-filter: blur(5px);
    `;

    let icon = 'ℹ';
    if (type === 'success') icon = '✓';
    if (type === 'error') icon = '✕';
    if (type === 'warn') icon = '⚠';

    toast.innerHTML = `<span style="font-weight: bold; font-size: 14px;">${icon}</span> <span style="line-height: 1.4;">${escapeHtml(message)}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.3s ease-in';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Add animation keyframes
if (!document.getElementById('toast-style')) {
    const style = document.createElement('style');
    style.id = 'toast-style';
    style.innerHTML = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function truncateText(text, length = 160) {
    if (!text) return "";
    const clean = text.replace(/\s+/g, " ").trim();
    if (clean.length <= length) return clean;
    return `${clean.slice(0, length).trim()}…`;
}

function normalizeVersionTag(tag) {
    const value = String(tag || "").trim();
    if (!value) return "";
    return value.replace(/^v+/i, "");
}

function formatVersionLabel(tag) {
    const normalized = normalizeVersionTag(tag);
    return normalized ? `v${normalized}` : "";
}

function renderServerUpdateAlert(data) {
    const sidebar = document.getElementById('sidebar');
    if (!data) return;

    const hasLatestVersion = !!(data.latest_version && String(data.latest_version).trim());

    if (data.in_progress) {
        if (sidebar) sidebar.classList.add('has-update');
        return;
    }

    if (data.update_available && hasLatestVersion) {
        if (sidebar) sidebar.classList.add('has-update');
        const latestVersion = formatVersionLabel(data.latest_version) || "NEW";

        if (data.latest_version && announcedUpdateVersion !== data.latest_version) {
            announcedUpdateVersion = data.latest_version;
            showToast(
                `New release detected (${latestVersion}). Open the update card to install it.`,
                "warn"
            );
        }
    } else {
        if (sidebar) sidebar.classList.remove('has-update');
        announcedUpdateVersion = "";
    }
}

async function loadSystemStatus(force = false) {
    try {
        const url = `/api/system/update${force ? "?force=true" : ""}`;
        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error("Release check failed");
        }
        const data = await resp.json();
        window.systemStatus = data;
        renderSystemStatus(data);
    } catch (err) {
        console.error("System status refresh failed:", err);
        window.systemStatus = window.systemStatus || null;
    }
}

function renderSystemStatus(data) {
    if (!data) return;

    const versionEl = document.getElementById("app-version");
    if (versionEl && data.current_version) {
        versionEl.textContent = `v${data.current_version}`;
    }
    renderServerUpdateAlert(data);

    const updateCallout = document.getElementById("update-callout");
    const updateButton = document.getElementById("update-action-btn");
    const updateDescription = document.getElementById("update-description");
    const updateVersion = document.getElementById("update-latest-version");
    const releaseLink = document.getElementById("update-release-link");
    const updateProgress = document.getElementById("update-progress");
    const updateProgressText = document.getElementById("update-progress-text");

    const hasLatestVersion = !!(data.latest_version && String(data.latest_version).trim());
    if (data.update_available && hasLatestVersion) {
        if (updateCallout) updateCallout.hidden = false;
        if (updateVersion) {
            updateVersion.textContent = formatVersionLabel(data.latest_version) || "New release";
        }
        if (updateDescription) {
            updateDescription.textContent =
                truncateText(data.release_notes) ||
                "Release notes are not available yet.";
        }
        if (releaseLink) {
            releaseLink.href = data.release_url || "#";
        }
        if (updateButton) {
            updateButton.disabled = !!data.in_progress;
            updateButton.textContent = data.in_progress
                ? "INSTALLING…"
                : "INSTALL UPDATE";
        }
    } else if (updateCallout) {
        updateCallout.hidden = true;
    }

    if (data.in_progress) {
        if (updateProgress) updateProgress.hidden = false;
        if (updateProgressText) {
            updateProgressText.textContent =
                data.progress_message || "Downloading update…";
        }
    } else if (updateProgress) {
        updateProgress.hidden = true;
    }

    if (data.last_error && data.last_error !== lastSystemErrorMessage) {
        lastSystemErrorMessage = data.last_error;
        showToast(`Update check failed: ${data.last_error}`, "warn");
    }

    if (
        data.last_update_message &&
        data.last_update_message !== lastSystemUpdateMessage
    ) {
        lastSystemUpdateMessage = data.last_update_message;
        showToast(data.last_update_message, "success");
    }
}

function startSystemStatusPolling() {
    if (systemStatusTimer) {
        clearInterval(systemStatusTimer);
    }
    loadSystemStatus();
    systemStatusTimer = setInterval(() => loadSystemStatus(), SYSTEM_STATUS_POLL_INTERVAL);
}

async function initiateSystemUpdate() {
    if (!window.systemStatus || !window.systemStatus.update_available) {
        showToast("No newer update is available right now.", "info");
        return;
    }

    if (window.systemStatus.in_progress) {
        showToast("An update is already running.", "info");
        return;
    }

    const latestVersion = formatVersionLabel(window.systemStatus.latest_version) || "the latest release";
    const confirmMessage = `${latestVersion} will be downloaded from GitHub Releases and installed automatically. Do you want to continue?`;
    const userConfirmed = await window.showConfirm(confirmMessage);
    if (!userConfirmed) return;

    try {
        const resp = await fetch("/api/system/update", {
            method: "POST",
        });
        if (!resp.ok) {
            const errorText = await resp.text();
            throw new Error(errorText || "Update request failed.");
        }
        const payload = await resp.json();
        showToast(
            payload.message || "Update started. Download and installation are running in the background.",
            "success"
        );
        loadSystemStatus(true);
    } catch (err) {
        console.error("Failed to trigger update:", err);
        showToast(
            `Failed to start update: ${err.message || "unknown error"}`,
            "error"
        );
    }
}

async function refreshFavoriteSlugs() {
    try {
        const resp = await fetch('/api/favorites');
        if (!resp.ok) {
            throw new Error(`Failed to fetch favorites: ${resp.status}`);
        }
        const data = await resp.json();
        window.favoriteSlugs = new Set((data.favorites || []).map(p => p.slug));
    } catch (e) {
        console.error('Failed to refresh favorites:', e);
        window.favoriteSlugs = new Set();
    }
}

function isFavoriteSlug(slug) {
    return window.favoriteSlugs instanceof Set && window.favoriteSlugs.has(slug);
}


document.addEventListener('DOMContentLoaded', async () => {
    // Initial setup
    initializeSidebarToggle();
    initializeStarStripDismiss();
    initializeDashboardChartInteractions();
    initializePagesAutoRandom();

    // Prime favorite cache before any UI render that depends on it
    await refreshFavoriteSlugs();

    // Load history
    loadHistory();

    // Restore view from URL state on page load
    restoreViewFromUrl();

    // Listen for browser back/forward
    window.addEventListener('popstate', restoreViewFromUrl);

    const updateButton = document.getElementById('update-action-btn');
    if (updateButton) {
        updateButton.addEventListener('click', initiateSystemUpdate);
    }
    startSystemStatusPolling();
});

function getUrlState() {
    const url = new URL(window.location.href);
    const params = url.searchParams;

    let view = String(params.get('view') || '').trim().toLowerCase();
    let plugin = String(params.get('plugin') || '').trim();
    const scanRaw = params.get('scan');
    let scanId = scanRaw != null ? parseInt(scanRaw, 10) : null;
    if (!Number.isFinite(scanId)) scanId = null;

    // Backward compatibility: migrate legacy hash URLs.
    const hash = window.location.hash.replace('#', '').trim();
    if (!view && hash) {
        const legacy = hash.toLowerCase();
        if (legacy.startsWith('details/')) {
            view = 'details';
            const parts = legacy.split('/');
            const parsed = parseInt(parts[1], 10);
            if (Number.isFinite(parsed)) scanId = parsed;
        } else if (legacy.startsWith('plugin/')) {
            const parts = hash.split('/');
            plugin = String(parts[1] || '').trim();
            const parsed = parseInt(parts[2], 10);
            if (Number.isFinite(parsed)) scanId = parsed;
            view = scanId ? 'details' : 'history';
        } else {
            const asTab = String(hash || '').toLowerCase();
            if (['scan', 'catalog', 'history', 'favorites', 'semgrep'].includes(asTab)) {
                view = TAB_TO_VIEW[asTab] || 'new-scan';
            }
        }
    }

    return { view, scanId, plugin };
}

function setUrlState(state = {}, options = {}) {
    const { replace = false } = options;
    const current = getUrlState();
    const merged = {
        view: state.view !== undefined ? state.view : current.view,
        scanId: state.scanId !== undefined ? state.scanId : current.scanId,
        plugin: state.plugin !== undefined ? state.plugin : current.plugin,
    };

    const url = new URL(window.location.href);
    url.searchParams.delete('view');
    url.searchParams.delete('scan');
    url.searchParams.delete('plugin');

    if (merged.view) url.searchParams.set('view', String(merged.view));
    if (Number.isFinite(Number(merged.scanId)) && Number(merged.scanId) > 0) {
        url.searchParams.set('scan', String(merged.scanId));
    }
    if (merged.plugin) url.searchParams.set('plugin', String(merged.plugin));

    // Remove hash style URLs completely.
    url.hash = '';

    const nextUrl = `${url.pathname}${url.search}`;
    if (replace) {
        window.history.replaceState({}, '', nextUrl);
    } else {
        window.history.pushState({}, '', nextUrl);
    }
}

function restoreViewFromUrl() {
    const state = getUrlState();

    if (!state.view) {
        setUrlState({ view: 'new-scan' }, { replace: true });
        switchTab('scan');
        return;
    }

    if (state.view !== 'details' && state.view !== 'plugin-detail') {
        modalReturnHash = state.view;
    }

    if (state.view === 'plugin-detail' && state.plugin) {
        if (state.scanId) currentScanId = state.scanId;
        setTimeout(() => openPluginModalBySlug(state.plugin, { syncUrl: false }), 0);
        setUrlState(
            { view: 'plugin-detail', scanId: state.scanId || null, plugin: state.plugin },
            { replace: true }
        );
        return;
    }

    if (state.view === 'details' && state.scanId) {
        viewScan(state.scanId, { syncUrl: false });
        setUrlState({ view: 'details', scanId: state.scanId, plugin: '' }, { replace: true });
        return;
    }

    const tabId = VIEW_TO_TAB[state.view] || 'scan';
    switchTab(tabId, { syncUrl: false });

    setUrlState({ view: TAB_TO_VIEW[tabId] || 'new-scan', plugin: '' }, { replace: true });
}

// Open plugin detail by slug (URL restoration)
async function openPluginModalBySlug(slug, options = {}) {
    // First try to find in current scan results
    if (window.currentScanResults && window.currentScanResults.length > 0) {
        const index = window.currentScanResults.findIndex(p => p.slug === slug);
        if (index !== -1) {
            openPluginModal(index, options);
            return;
        }
    }
    
    // If not found, try to fetch from favorites
    try {
        const resp = await fetch('/api/favorites');
        const data = await resp.json();
        if (data.favorites) {
            const plugin = data.favorites.find(p => p.slug === slug);
            if (plugin) {
                window.currentScanResults = [plugin];
                openPluginModal(0, options);
                return;
            }
        }
    } catch (e) {
        console.error('Failed to load from favorites:', e);
    }
    
    // If currentScanId is set, try to fetch from that scan's results
    if (currentScanId) {
        try {
            const resp = await fetch(`/api/scans/${currentScanId}/results?limit=500`);
            const data = await resp.json();
            if (data.results) {
                const index = data.results.findIndex(p => p.slug === slug);
                if (index !== -1) {
                    window.currentScanResults = data.results;
                    openPluginModal(index, options);
                    return;
                }
            }
        } catch (e) {
            console.error('Failed to load from current scan:', e);
        }
    }
    
    // Last resort: fetch all scans and search through their results
    try {
        const resp = await fetch('/api/scans');
        const data = await resp.json();
        if (data.sessions && data.sessions.length > 0) {
            // Sort by most recent first
            const sessions = data.sessions.sort((a, b) => 
                new Date(b.created_at || b.start_time) - new Date(a.created_at || a.start_time)
            );
            
            // Search through each scan's results
            for (const session of sessions) {
                try {
                    const resultResp = await fetch(`/api/scans/${session.id}/results?limit=500`);
                    const resultData = await resultResp.json();
                    if (resultData.results) {
                        const index = resultData.results.findIndex(p => p.slug === slug);
                        if (index !== -1) {
                            window.currentScanResults = resultData.results;
                            // Set currentScanId so returning goes back to this scan
                            currentScanId = session.id;
                            openPluginModal(index, options);
                            return;
                        }
                    }
                } catch (e) {
                    console.error(`Failed to load scan ${session.id} results:`, e);
                }
            }
        }
    } catch (e) {
        console.error('Failed to load scans:', e);
    }
    
    // If still not found, show error toast and go to history
    showToast('Plugin not found. It may have been removed.', 'error');
    setUrlState({ view: 'history', plugin: '', scanId: null }, { replace: false });
    switchTab('history', { syncUrl: false });
}

window.switchTab = function(tabId, options = {}) {
    const { syncUrl = true } = options;
    // Hide all views
    document.getElementById('scan-view').style.display = 'none';
    document.getElementById('history-view').style.display = 'none';
    document.getElementById('favorites-view').style.display = 'none';
    const catalogView = document.getElementById('catalog-view');
    if (catalogView) catalogView.style.display = 'none';
    const detailsView = document.getElementById('scan-details-view');
    if (detailsView) detailsView.style.display = 'none';
    const semgrepView = document.getElementById('semgrep-view');
    if (semgrepView) semgrepView.style.display = 'none';
    const pluginDetailView = document.getElementById('plugin-detail-view');
    if (pluginDetailView) pluginDetailView.style.display = 'none';

    // Reset nav active state
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    // Show selected view and set active
    if (tabId === 'scan') {
        document.getElementById('scan-view').style.display = 'block';
        document.getElementById('nav-scan').classList.add('active');
        resetDashboardChartCaptions();
    } else if (tabId === 'history') {
        document.getElementById('history-view').style.display = 'block';
        document.getElementById('nav-history').classList.add('active');
        loadHistory();
    } else if (tabId === 'favorites') {
        document.getElementById('favorites-view').style.display = 'block';
        document.getElementById('nav-favorites').classList.add('active');
        loadFavorites();
    } else if (tabId === 'catalog') {
        if (catalogView) catalogView.style.display = 'block';
        const navCatalog = document.getElementById('nav-catalog');
        if (navCatalog) navCatalog.classList.add('active');
        loadCatalog();
    } else if (tabId === 'semgrep') {
        if (semgrepView) semgrepView.style.display = 'block';
        document.getElementById('nav-semgrep').classList.add('active');
        loadSemgrepRules();
    } else if (tabId === 'details') {
        if (detailsView) detailsView.style.display = 'block';
    } else if (tabId === 'plugin-detail') {
        if (pluginDetailView) pluginDetailView.style.display = 'block';
    }

    // Stop details polling when leaving details view
    if (tabId !== 'details') {
        if (detailsPollingInterval) {
            clearInterval(detailsPollingInterval);
            detailsPollingInterval = null;
        }
        if (detailsBulkPollingInterval) {
            clearInterval(detailsBulkPollingInterval);
            detailsBulkPollingInterval = null;
        }
        detailsBulkRunning = false;
        if (tabId !== 'plugin-detail') {
            currentScanId = null;
        }
    }

    // Update URL state for persistence on refresh (except details, handled by viewScan)
    if (syncUrl && tabId !== 'details' && tabId !== 'plugin-detail') {
        setUrlState({ view: TAB_TO_VIEW[tabId] || 'new-scan', scanId: null, plugin: '' }, { replace: false });
    }
}

window.runScan = async function() {
    const form = document.getElementById('configForm');
    const pagesValue = preparePagesValueBeforeScan();
    const formData = new FormData(form);
    
    const requestData = {
        pages: pagesValue,
        limit: parseInt(formData.get('limit')) || 0,
        min_installs: parseInt(formData.get('min_installs')) || 0,
        max_installs: parseInt(formData.get('max_installs')) || 0,
        sort: formData.get('sort') || 'updated',
        smart: formData.get('smart') === 'on',
        abandoned: formData.get('abandoned') === 'on',
        user_facing: formData.get('user_facing') === 'on',
        themes: formData.get('themes') === 'on',
        min_days: parseInt(formData.get('min_days')) || 0,
        max_days: parseInt(formData.get('max_days')) || 0,
        download: 0,
        auto_download_risky: 0,
        // Removed output and format options from request
    };

    // Download options removed from UI, so defaulting to 0

    const runBtn = document.getElementById('runBtn');
    runBtn.disabled = true;
    runBtn.innerHTML = '<span>STARTING...</span>';
    setProgressDetailsButton(false);
    
    clearTerminal();
    logTerminal('Initializing scan...', 'info');
    setScanProgressState(5, 'Starting', 'Submitting scan request');
    
    try {
        const response = await fetch('/api/scans', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });
        
        const data = await response.json();
        
        if (data.session_id) {
            currentScanId = data.session_id;
            logTerminal(`Scan session started: ID ${currentScanId}`, 'success');
            setScanProgressState(8, 'Starting', `Session #${currentScanId} created`);
            connectWebSocket(currentScanId);
            
            document.getElementById('scan-status').textContent = 'RUNNING';
            document.getElementById('scan-status').className = 'metric-value info-value running';
            
        } else {
            logTerminal('Failed to start scan', 'error');
            setScanProgressState(100, 'Failed', 'Scan session could not be started');
            setProgressDetailsButton(false);
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
        }
    } catch (error) {
        logTerminal(`Error: ${error.message}`, 'error');
        setScanProgressState(100, 'Failed', error.message || 'Unknown error');
        setProgressDetailsButton(false);
        runBtn.disabled = false;
        runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
    }
}

function connectWebSocket(sessionId) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/scans/${sessionId}`;
    if (socket) socket.close();
    
    socket = new WebSocket(wsUrl);
    socket.onopen = () => {
        logTerminal('WebSocket connected', 'info');
        setScanProgressState(10, 'Running', 'Realtime channel connected');
    };
    socket.onmessage = (event) => handleMessage(JSON.parse(event.data));
    socket.onclose = () => {
        logTerminal('WebSocket connection closed', 'info');
    };
    socket.onerror = () => {
        logTerminal('WebSocket error', 'error');
        setScanProgressState(100, 'Failed', 'Realtime channel error');
    };
}

function handleMessage(msg) {
    const runBtn = document.getElementById('runBtn');
    
    switch(msg.type) {
        case 'start':
            logTerminal('Scan execution started...', 'info');
            setScanProgressState(12, 'Running', 'Execution started');
            setProgressDetailsButton(false);
            break;
        case 'progress': {
            const percent = Number(msg.percent || 0);
            const current = Number(msg.current || 0);
            const total = Number(msg.total || 0);
            const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
            const detail = total > 0 ? `Processed ${current}/${total} targets` : `Processed ${current} targets`;
            setScanProgressState(safePercent, 'Running', detail);
            break;
        }
        case 'result':
            logTerminal(`${msg.data.score >= 40 ? '[HIGH RISK]' : '[INFO]'} Found: ${msg.data.slug} (Score: ${msg.data.score})`, msg.data.score >= 40 ? 'high-risk' : 'low-risk');
            document.getElementById('scan-found').textContent = msg.found_count;
            appendTrendPoint(msg.found_count);
            setScanProgressState(null, 'Running', `Detected ${msg.found_count} findings`);
            break;
        case 'deduplicated':
            logTerminal(`Scan identical to Session #${msg.original_session_id}. Merging...`, 'warn');
            logTerminal(`Session merged. History updated.`, 'success');
            currentScanId = msg.original_session_id;
            document.getElementById('scan-status').textContent = 'MERGED';
            document.getElementById('scan-status').className = 'metric-value info-value completed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            setScanProgressState(100, 'Merged', `Merged into Session #${msg.original_session_id}`);
            setProgressDetailsButton(true);
            refreshAfterScanEvent(currentScanId);
            break;
        case 'complete':
            logTerminal(`Scan completed. Found: ${msg.total_found}, High Risk: ${msg.high_risk_count}`, 'success');
            document.getElementById('scan-status').textContent = 'COMPLETED';
            document.getElementById('scan-status').className = 'metric-value info-value completed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            setScanProgressState(100, 'Completed', `Found ${msg.total_found} total / ${msg.high_risk_count} high risk`);
            setProgressDetailsButton(true);
            refreshAfterScanEvent(currentScanId);
            if (currentScanId && isDetailsViewActive()) {
                syncFinalScanResults(currentScanId, msg.total_found);
            }
            // Stop polling when scan completes
            if (detailsPollingInterval) {
                clearInterval(detailsPollingInterval);
                detailsPollingInterval = null;
            }
            break;
        case 'error':
            logTerminal(`Error: ${msg.message}`, 'error');
            document.getElementById('scan-status').textContent = 'FAILED';
            document.getElementById('scan-status').className = 'metric-value info-value failed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            setScanProgressState(100, 'Failed', msg.message || 'Scan terminated with an error');
            setProgressDetailsButton(false);
            refreshAfterScanEvent(currentScanId);
            // Stop polling on error
            if (detailsPollingInterval) {
                clearInterval(detailsPollingInterval);
                detailsPollingInterval = null;
            }
            break;
    }
}

function setScanProgressState(percent, stage, detail) {
    const fill = document.getElementById('scan-progress-fill');
    const track = document.getElementById('scan-progress-track');
    const percentLabel = document.getElementById('scan-progress-percent');
    const stageLabel = document.getElementById('scan-stage-text');
    const detailLabel = document.getElementById('scan-stage-subtext');

    if (!fill || !track) return;

    const currentPercent = Number(fill.dataset.percent || '0');
    const resolved = percent == null ? currentPercent : Math.max(0, Math.min(100, Number(percent)));

    fill.style.width = `${resolved}%`;
    fill.dataset.percent = String(resolved);
    track.setAttribute('aria-valuenow', String(Math.round(resolved)));

    if (percentLabel) percentLabel.textContent = `${Math.round(resolved)}%`;
    if (stageLabel && stage) stageLabel.textContent = stage;
    if (detailLabel && detail) detailLabel.textContent = detail;
}

function setProgressDetailsButton(visible) {
    const btn = document.getElementById('scan-progress-details-btn');
    if (!btn) return;
    const shouldShow = Boolean(visible) && Boolean(currentScanId);
    btn.style.display = shouldShow ? 'inline-flex' : 'none';
}

window.openProgressScanDetails = function() {
    if (!currentScanId) return;
    viewScan(currentScanId);
};

function logTerminal(text, type = 'info') {
    const stageMap = {
        error: 'Failed',
        'high-risk': 'Warning',
        success: 'Completed',
        warn: 'Notice',
        info: 'Running'
    };
    const stage = stageMap[type] || 'Running';
    setScanProgressState(null, stage, text);
}

function clearTerminal() {
    setScanProgressState(0, 'Initializing', 'Preparing scan session...');
    setProgressDetailsButton(false);
}

let dashboardTrendPoints = [];

function setDashboardMetric(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = String(value);
}

function setChartCaption(id, text) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
}

function resetDashboardChartCaptions() {
    setChartCaption('dashboard-risk-caption', 'Click bar to open scan');
    setChartCaption('dashboard-trend-caption', 'Click bar to open scan');
}

function bindChartHover(containerId, captionId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const handleEnter = (event) => {
        const point = event.target.closest('.chart-point[data-caption]');
        if (!point || !container.contains(point)) return;
        setChartCaption(captionId, point.getAttribute('data-caption') || '');
    };

    const handleLeave = () => {
        resetDashboardChartCaptions();
    };

    container.addEventListener('mouseover', handleEnter);
    container.addEventListener('focusin', handleEnter);
    container.addEventListener('mouseleave', handleLeave);
    container.addEventListener('focusout', handleLeave);
}

function initializeDashboardChartInteractions() {
    bindChartHover('dashboard-risk-bars', 'dashboard-risk-caption');
    bindChartHover('dashboard-trend-bars', 'dashboard-trend-caption');
    resetDashboardChartCaptions();
}

window.openDashboardScanFromChart = function(scanId, source = 'chart') {
    const parsed = Number(scanId);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    setChartCaption('dashboard-risk-caption', `Opening #${parsed} (${source})`);
    setChartCaption('dashboard-trend-caption', `Opening #${parsed} (${source})`);
    setTimeout(resetDashboardChartCaptions, 1200);
    viewScan(parsed);
};

function renderRecentScans(sessions) {
    const recentList = document.getElementById('dashboard-recent-list');
    const completedRate = document.getElementById('dashboard-completed-rate');
    if (!recentList) return;

    if (!sessions || sessions.length === 0) {
        recentList.innerHTML = '<div class="recent-empty">No scans yet</div>';
        if (completedRate) completedRate.textContent = '0% completed';
        return;
    }

    const completedCount = sessions.filter(s => String(s.status).toLowerCase() === 'completed').length;
    const percent = Math.round((completedCount / sessions.length) * 100);
    if (completedRate) completedRate.textContent = `${percent}% completed`;

    const maxPluginsFound = sessions.reduce((max, session) => {
        const sessionCount = parseInt(session.total_found || 0, 10) || 0;
        return Math.max(max, sessionCount);
    }, 1);

    recentList.innerHTML = sessions.slice(0, 3).map(s => {
        const id = parseInt(s.id, 10) || 0;
        const statusClass = String(s.status || 'unknown').toLowerCase();
        const statusLabel = statusClass === 'merged' ? 'MERGED' : statusClass.toUpperCase();
        const found = parseInt(s.total_found || 0, 10) || 0;
        const highRisk = parseInt(s.high_risk_count || 0, 10) || 0;
        const foundRatio = maxPluginsFound > 0 ? Math.min(100, Math.round((found / maxPluginsFound) * 100)) : 0;
        const foundLevel = foundRatio >= 70 ? 'high' : (foundRatio >= 35 ? 'medium' : 'low');
        const riskLevel = highRisk >= 20 ? 'high' : (highRisk >= 5 ? 'medium' : 'low');
        const riskRatio = found > 0 ? Math.min(100, Math.round((highRisk / found) * 100)) : 0;
        const date = new Date(s.created_at || s.start_time).toLocaleString();
        return `
            <div class="recent-row recent-history-row" tabindex="0" onclick="openDashboardScanFromChart(${id}, 'recent')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openDashboardScanFromChart(${id}, 'recent');}">
                <span class="recent-title recent-history-id">#${id}</span>
                <span class="status-badge ${escapeHtml(statusClass)}">${escapeHtml(statusLabel)}</span>
                <div class="history-found-cell" title="${found} plugins found (relative density ${foundRatio}%)">
                    <span class="history-found-count">${escapeHtml(String(found))}</span>
                    <span class="history-found-label">plugins</span>
                    <span class="history-found-track"><span class="history-found-fill ${foundLevel}" style="width: ${foundRatio}%;"></span></span>
                </div>
                <div class="history-risk-cell" title="${highRisk} high risk / ${found} total (${riskRatio}%)">
                    <span class="history-risk-pill ${riskLevel}">${escapeHtml(String(highRisk))}</span>
                    <span class="history-risk-meter"><span class="history-risk-fill ${riskLevel}" style="width: ${riskRatio}%;"></span></span>
                </div>
                <span class="recent-meta history-date-stamp recent-history-date">${escapeHtml(date)}</span>
                <button class="history-action-open dashboard-history-open" type="button" onclick="event.stopPropagation();openDashboardScanFromChart(${id}, 'recent')" title="Open Scan" aria-label="Open scan #${id}">
                    <span>OPEN</span>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                </button>
            </div>
        `;
    }).join('');
}

function renderRecentFavorites(favorites) {
    const list = document.getElementById('dashboard-favorites-list');
    if (!list) return;

    if (!favorites || favorites.length === 0) {
        list.innerHTML = '<div class="recent-empty">No favorites yet</div>';
        return;
    }

    list.innerHTML = favorites.slice(0, 3).map(plugin => {
        const rawSlug = String(plugin.slug || 'unknown-plugin');
        const slug = escapeHtml(rawSlug);
        const slugJs = JSON.stringify(rawSlug);
        const score = parseInt(plugin.score || 0, 10) || 0;
        const riskLevel = score >= 40 ? 'high' : (score >= 20 ? 'medium' : 'low');
        const scoreRatio = Math.max(0, Math.min(100, score));
        const versionLabel = `v${String(plugin.version || 'n/a')}`;
        return `
            <div class="recent-row recent-favorites-row" tabindex="0" onclick='openPluginModalBySlug(${slugJs})' onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPluginModalBySlug(${slugJs});}">
                <span class="recent-title recent-favorites-slug">${slug}</span>
                <span class="recent-meta history-date-stamp recent-favorites-version">${escapeHtml(versionLabel)}</span>
                <div class="history-risk-cell recent-favorites-risk" title="Risk score ${score}">
                    <span class="history-risk-pill ${riskLevel}">${score}</span>
                    <span class="history-risk-meter"><span class="history-risk-fill ${riskLevel}" style="width: ${scoreRatio}%;"></span></span>
                </div>
                <button class="history-action-open dashboard-history-open" type="button" onclick='event.stopPropagation();openPluginModalBySlug(${slugJs})' title="Open Favorite" aria-label="Open favorite ${slug}">
                    <span>OPEN</span>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                </button>
            </div>
        `;
    }).join('');
}

async function refreshDashboardFavorites() {
    try {
        const response = await fetch('/api/favorites');
        if (!response.ok) throw new Error(`Favorites fetch failed: ${response.status}`);
        const data = await response.json();
        renderRecentFavorites(data.favorites || []);
    } catch (error) {
        renderRecentFavorites([]);
    }
}

function renderRiskBars(sessions) {
    const riskBars = document.getElementById('dashboard-risk-bars');
    const riskCaption = document.getElementById('dashboard-risk-caption');
    if (!riskBars) return;

    if (!sessions || sessions.length === 0) {
        riskBars.innerHTML = '';
        if (riskCaption) riskCaption.textContent = 'No history';
        return;
    }

    const recent = sessions.slice(0, 8).reverse();
    const maxFound = Math.max(1, ...recent.map(s => parseInt(s.total_found || 0)));

    riskBars.innerHTML = recent.map((s) => {
        const id = parseInt(s.id);
        const found = parseInt(s.total_found || 0);
        const high = parseInt(s.high_risk_count || 0);
        const ratio = found > 0 ? high / found : 0;
        const height = Math.max(10, Math.round((found / maxFound) * 100));
        const level = ratio >= 0.35 ? 'high' : (ratio >= 0.15 ? 'medium' : 'low');
        const title = `Scan #${id} | Found ${found} | High ${high}`;
        const caption = `#${id} risk ${high}/${found}`;
        return `
            <button class="bar-item chart-point ${level}" type="button" data-scan-id="${id}" data-caption="${caption}" style="--h:${height}%" title="${title}" onclick="openDashboardScanFromChart(${id}, 'risk')"></button>
        `;
    }).join('');

    if (riskCaption) {
        const highSum = recent.reduce((acc, s) => acc + parseInt(s.high_risk_count || 0), 0);
        riskCaption.textContent = `${highSum} high-risk total - click a bar`;
    }
}

function renderTrendBars() {
    const trendBars = document.getElementById('dashboard-trend-bars');
    const trendCaption = document.getElementById('dashboard-trend-caption');
    if (!trendBars) return;

    if (!dashboardTrendPoints.length) {
        trendBars.innerHTML = '';
        if (trendCaption) trendCaption.textContent = 'No trend data';
        return;
    }

    const maxVal = Math.max(1, ...dashboardTrendPoints.map(item => item.value));
    trendBars.innerHTML = dashboardTrendPoints.map((item) => {
        const value = Number(item.value || 0);
        const h = Math.max(8, Math.round((value / maxVal) * 100));
        const scanId = Number(item.scanId || 0);
        if (scanId > 0) {
            const title = `Scan #${scanId} | Found ${value}`;
            const caption = `#${scanId} found ${value}`;
            return `<button class="spark-item chart-point" type="button" data-scan-id="${scanId}" data-caption="${caption}" style="--h:${h}%" title="${title}" onclick="openDashboardScanFromChart(${scanId}, 'trend')"></button>`;
        }
        return `<div class="spark-item" style="--h:${h}%" title="Live found: ${value}"></div>`;
    }).join('');

    if (trendCaption) trendCaption.textContent = `Recent ${dashboardTrendPoints.length} sessions - click a bar`;
}

function renderTrendBarsFromSessions(sessions) {
    dashboardTrendPoints = (sessions || []).slice(0, 8).reverse().map((s) => ({
        value: parseInt(s.total_found || 0),
        scanId: parseInt(s.id || 0)
    })).slice(-8);
    renderTrendBars();
}

function appendTrendPoint(value) {
    const parsed = parseInt(value || 0);
    if (!Number.isFinite(parsed)) return;
    dashboardTrendPoints.push({
        value: parsed,
        scanId: Number(currentScanId) || 0
    });
    dashboardTrendPoints = dashboardTrendPoints.slice(-8);
    renderTrendBars();
}

function refreshScanDashboard(sessions) {
    const safeSessions = sessions || [];
    const totalScans = safeSessions.length;
    const highRiskTotal = safeSessions.reduce((acc, s) => acc + parseInt(s.high_risk_count || 0), 0);
    setDashboardMetric('dashboard-total-scans', totalScans);
    setDashboardMetric('dashboard-high-risk', highRiskTotal);
    renderRecentScans(safeSessions);
    refreshDashboardFavorites();
    renderRiskBars(safeSessions);
    renderTrendBarsFromSessions(safeSessions);
    resetDashboardChartCaptions();
}

const historySemgrepStatsCache = new Map();
let historySessionsCache = [];
let historyFiltersInitialized = false;
let historyFilteredCache = [];
let historyCurrentPage = 1;
const HISTORY_PAGE_SIZE = 10;
let detailsResultsCache = [];
let detailsSourceCache = [];
let detailsFiltersInitialized = false;
let detailsCurrentPage = 1;
const DETAILS_PAGE_SIZE = 10;
let catalogPluginsCache = [];
let catalogFilteredCache = [];
let catalogFiltersInitialized = false;
let catalogCurrentPage = 1;
const CATALOG_PAGE_SIZE = 10;

function updateTablePagination(prefix, totalItems, currentPage, pageSize) {
    const paginationEl = document.getElementById(`${prefix}-pagination`);
    const infoEl = document.getElementById(`${prefix}-page-info`);
    const currentEl = document.getElementById(`${prefix}-page-current`);
    const prevBtn = document.getElementById(`${prefix}-page-prev`);
    const nextBtn = document.getElementById(`${prefix}-page-next`);

    if (!paginationEl || !infoEl || !currentEl || !prevBtn || !nextBtn) return;

    const total = Math.max(0, parseInt(totalItems || 0, 10) || 0);
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.min(Math.max(1, currentPage), totalPages);

    if (total <= pageSize) {
        paginationEl.style.display = 'none';
    } else {
        paginationEl.style.display = 'flex';
    }

    const start = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
    const end = total === 0 ? 0 : Math.min(total, safePage * pageSize);

    infoEl.textContent = `Showing ${start}-${end} of ${total}`;
    currentEl.textContent = `${safePage} / ${totalPages}`;
    prevBtn.disabled = safePage <= 1;
    nextBtn.disabled = safePage >= totalPages;
}

window.changeHistoryPage = function(delta) {
    const totalPages = Math.max(1, Math.ceil((historyFilteredCache.length || 0) / HISTORY_PAGE_SIZE));
    historyCurrentPage = Math.min(Math.max(1, historyCurrentPage + delta), totalPages);
    renderHistoryRows(historyFilteredCache);
}

window.changeDetailsPage = function(delta) {
    const totalPages = Math.max(1, Math.ceil((detailsResultsCache.length || 0) / DETAILS_PAGE_SIZE));
    detailsCurrentPage = Math.min(Math.max(1, detailsCurrentPage + delta), totalPages);
    renderDetailsRows(detailsResultsCache);
}

window.changeCatalogPage = function(delta) {
    const totalPages = Math.max(1, Math.ceil((catalogFilteredCache.length || 0) / CATALOG_PAGE_SIZE));
    catalogCurrentPage = Math.min(Math.max(1, catalogCurrentPage + delta), totalPages);
    renderCatalogRows(catalogFilteredCache);
}

function getHistorySessionMode(session) {
    const config = session && session.config ? session.config : {};
    return config.themes ? 'theme' : 'plugin';
}

function getHistoryRiskLevel(session) {
    const highRiskCount = parseInt((session && session.high_risk_count) || 0, 10) || 0;
    if (highRiskCount >= 20) return 'high';
    if (highRiskCount >= 5) return 'medium';
    return 'low';
}

function getHistoryFilterState() {
    const queryEl = document.getElementById('history-filter-query');
    const statusEl = document.getElementById('history-filter-status');
    const modeEl = document.getElementById('history-filter-mode');
    const riskEl = document.getElementById('history-filter-risk');

    return {
        query: String(queryEl ? queryEl.value : '').trim().toLowerCase(),
        status: String(statusEl ? statusEl.value : 'all').toLowerCase(),
        mode: String(modeEl ? modeEl.value : 'all').toLowerCase(),
        risk: String(riskEl ? riskEl.value : 'all').toLowerCase()
    };
}

function filterHistorySessions(sessions, filterState) {
    const state = filterState || getHistoryFilterState();

    return (sessions || []).filter((session) => {
        const status = String((session && session.status) || '').toLowerCase();
        const mode = getHistorySessionMode(session);
        const risk = getHistoryRiskLevel(session);
        const dateStr = new Date((session && (session.created_at || session.start_time)) || Date.now()).toLocaleString().toLowerCase();
        const idStr = String((session && session.id) || '').toLowerCase();

        if (state.status !== 'all' && status !== state.status) return false;
        if (state.mode !== 'all' && mode !== state.mode) return false;
        if (state.risk !== 'all' && risk !== state.risk) return false;

        if (state.query) {
            const haystack = `${idStr} ${status} ${mode} ${dateStr}`;
            if (!haystack.includes(state.query)) return false;
        }

        return true;
    });
}

function renderHistoryRows(sessions) {
    const list = document.getElementById('history-list');
    if (!list) return;

    const safeSessions = sessions || [];
    historyFilteredCache = safeSessions;

    const totalPages = Math.max(1, Math.ceil(safeSessions.length / HISTORY_PAGE_SIZE));
    historyCurrentPage = Math.min(Math.max(1, historyCurrentPage), totalPages);
    const pageStart = (historyCurrentPage - 1) * HISTORY_PAGE_SIZE;
    const pagedSessions = safeSessions.slice(pageStart, pageStart + HISTORY_PAGE_SIZE);

    updateTablePagination('history', safeSessions.length, historyCurrentPage, HISTORY_PAGE_SIZE);

    if (safeSessions.length === 0) {
        list.innerHTML = '<tr><td colspan="8" class="favorites-empty">No scans match the current filters</td></tr>';
        return;
    }

    const maxPluginsFound = safeSessions.reduce((max, session) => {
        const sessionCount = parseInt(session.total_found || 0, 10) || 0;
        return Math.max(max, sessionCount);
    }, 1);

    const maxHighRiskCount = safeSessions.reduce((max, session) => {
        const riskCount = parseInt(session.high_risk_count || 0, 10) || 0;
        return Math.max(max, riskCount);
    }, 1);

    list.innerHTML = pagedSessions.map(s => {
        const scanId = parseInt(s.id, 10);
        const totalFound = parseInt(s.total_found || 0, 10) || 0;
        const highRiskCount = parseInt(s.high_risk_count || 0, 10) || 0;
        const foundRatio = maxPluginsFound > 0 ? Math.min(100, Math.round((totalFound / maxPluginsFound) * 100)) : 0;
        const foundLevel = foundRatio >= 70 ? 'high' : (foundRatio >= 35 ? 'medium' : 'low');
        const riskLevel = highRiskCount >= 20 ? 'high' : (highRiskCount >= 5 ? 'medium' : 'low');
        const riskRatio = maxHighRiskCount > 0 ? Math.min(100, Math.round((highRiskCount / maxHighRiskCount) * 100)) : 0;
        const config = s.config || {};
        const isThemeSession = Boolean(config.themes);
        const modeLabel = isThemeSession ? 'THEME' : 'PLUGIN';
        const modeClass = isThemeSession ? 'theme' : 'plugin';
        const statusClass = String(s.status || 'unknown').toLowerCase();
        const statusLabel = statusClass === 'merged' ? 'MERGED' : statusClass.toUpperCase();

        return `
            <tr class="history-row" tabindex="0" onclick="viewScan(${scanId})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();viewScan(${scanId});}">
                <td class="history-col-id">#${escapeHtml(String(s.id))}</td>
                <td class="history-col-status"><span class="status-badge ${escapeHtml(statusClass)}">${escapeHtml(statusLabel)}</span></td>
                <td class="history-col-found">
                    <div class="history-found-cell" title="${totalFound} plugins found (relative density ${foundRatio}%)">
                        <span class="history-found-count">${escapeHtml(String(totalFound))}</span>
                        <span class="history-found-label">plugins</span>
                        <span class="history-found-track"><span class="history-found-fill ${foundLevel}" style="width: ${foundRatio}%;"></span></span>
                    </div>
                </td>
                <td class="history-col-risk">
                    <div class="history-risk-cell" title="${highRiskCount} high risk (relative to max ${maxHighRiskCount}: ${riskRatio}%)">
                        <span class="history-risk-pill ${riskLevel}">${escapeHtml(String(highRiskCount))}</span>
                        <span class="history-risk-meter"><span class="history-risk-fill ${riskLevel}" style="width: ${riskRatio}%;"></span></span>
                    </div>
                </td>
                <td class="history-col-date"><span class="history-date-stamp">${escapeHtml(new Date(s.created_at || s.start_time).toLocaleString())}</span></td>
                <td class="history-col-semgrep">
                    <div id="history-semgrep-${scanId}" class="history-semgrep-cell empty" title="Semgrep status pending">
                        <span id="history-semgrep-count-${scanId}" class="history-semgrep-pill">--</span>
                        <span class="history-semgrep-meter"><span id="history-semgrep-fill-${scanId}" class="history-semgrep-fill" style="width: 0%;"></span></span>
                        <span id="history-semgrep-state-${scanId}" class="history-semgrep-state">WAIT</span>
                    </div>
                </td>
                <td class="history-col-mode">
                    <span class="history-mode-chip ${modeClass}">${escapeHtml(modeLabel)}</span>
                </td>
                <td class="history-col-actions">
                    <div class="history-actions">
                        <span class="history-action-open" aria-hidden="true">
                            <span>Open</span>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                        </span>
                        <button onclick="event.stopPropagation(); deleteScan(${scanId})" class="action-btn history-action-delete" title="Delete Scan" aria-label="Delete scan #${scanId}">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    hydrateHistorySemgrepBadges(pagedSessions);
}

function applyHistoryFilters() {
    historyCurrentPage = 1;
    const filtered = filterHistorySessions(historySessionsCache, getHistoryFilterState());
    renderHistoryRows(filtered);
}

function getCatalogFilterState() {
    const queryEl = document.getElementById('catalog-filter-query');
    const sortEl = document.getElementById('catalog-filter-sort');
    const typeEl = document.getElementById('catalog-filter-type');
    const orderEl = document.getElementById('catalog-filter-order');

    return {
        query: String(queryEl ? queryEl.value : '').trim().toLowerCase(),
        sort: String(sortEl ? sortEl.value : 'last_seen').toLowerCase(),
        type: String(typeEl ? typeEl.value : 'all').toLowerCase(),
        order: String(orderEl ? orderEl.value : 'desc').toLowerCase(),
    };
}

function getCatalogSortValue(item, sortKey) {
    if (sortKey === 'seen_count') return parseInt(item.seen_count || 0, 10) || 0;
    if (sortKey === 'max_score') return parseInt(item.max_score_ever || 0, 10) || 0;
    if (sortKey === 'installs') return parseInt(item.latest_installations || 0, 10) || 0;
    if (sortKey === 'updated_days') {
        const days = parseInt(item.latest_days_since_update, 10);
        return Number.isFinite(days) ? days : Number.POSITIVE_INFINITY;
    }
    if (sortKey === 'slug') return String(item.slug || '').toLowerCase();
    const ts = Date.parse(item.last_seen_at || '');
    return Number.isFinite(ts) ? ts : 0;
}

function filterCatalogPlugins(items, filterState) {
    const state = filterState || getCatalogFilterState();
    const filtered = (items || []).filter((item) => {
        const itemType = item && item.is_theme ? 'theme' : 'plugin';
        if (state.type !== 'all' && itemType !== state.type) return false;

        if (!state.query) return true;
        const haystack = `${String(item.slug || '').toLowerCase()} ${itemType}`;
        return haystack.includes(state.query);
    });

    filtered.sort((a, b) => {
        const av = getCatalogSortValue(a, state.sort);
        const bv = getCatalogSortValue(b, state.sort);

        let diff = 0;
        if (typeof av === 'string' || typeof bv === 'string') {
            diff = String(av).localeCompare(String(bv));
        } else {
            diff = Number(av) - Number(bv);
        }

        if (state.order === 'desc') diff *= -1;
        if (diff !== 0) return diff;

        const aSlug = String(a.slug || '').toLowerCase();
        const bSlug = String(b.slug || '').toLowerCase();
        return aSlug.localeCompare(bSlug);
    });

    return filtered;
}

function renderCatalogDashboard(items) {
    const dashboard = document.getElementById('catalog-dashboard');
    if (!dashboard) return;

    const rows = Array.isArray(items) ? items : [];
    const total = rows.length;

    if (total === 0) {
        dashboard.innerHTML = '';
        return;
    }

    const highCount = rows.filter(r => (parseInt(r && (r.latest_score ?? r.max_score_ever) || 0, 10) || 0) >= 40).length;
    const midCount = rows.filter(r => {
        const score = parseInt(r && (r.latest_score ?? r.max_score_ever) || 0, 10) || 0;
        return score >= 20 && score < 40;
    }).length;
    const lowCount = Math.max(0, total - highCount - midCount);

    let issueCount = 0;
    let cleanCount = 0;
    let waitingCount = 0;
    let failedCount = 0;
    let runningCount = 0;

    rows.forEach((r) => {
        const semgrep = r && r.semgrep ? r.semgrep : null;
        if (!semgrep) {
            waitingCount += 1;
            return;
        }

        const status = String(semgrep.status || '').toLowerCase();
        if (status === 'completed') {
            const findings = parseInt(semgrep.findings_count || 0, 10) || 0;
            if (findings > 0) issueCount += 1;
            else cleanCount += 1;
            return;
        }
        if (status === 'failed') {
            failedCount += 1;
            return;
        }
        if (status === 'running' || status === 'pending') {
            runningCount += 1;
            return;
        }

        waitingCount += 1;
    });

    const scannedCount = issueCount + cleanCount + failedCount;
    const remainingCount = Math.max(0, total - scannedCount);
    const toPct = (value, sum) => {
        if (!sum || sum <= 0) return 0;
        return Math.max(0, Math.min(100, Math.round((value / sum) * 100)));
    };

    dashboard.innerHTML = `
        <div class="details-stat-card details-stat-card-total">
            <div class="details-stat-label">Catalog inventory</div>
            <div class="details-stat-value">${total}</div>
            <div class="details-stat-sub">Unique plugins/themes in database</div>
            <div class="details-stat-track"><span class="details-stat-fill details-fill-blue" style="width:100%"></span></div>
        </div>
        <div class="details-stat-card details-stat-card-progress">
            <div class="details-stat-label">Semgrep progress</div>
            <div class="details-stat-value">${scannedCount} / ${total}</div>
            <div class="details-stat-sub">Processed / Total • ${remainingCount} remaining</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-primary" style="width:${toPct(scannedCount, total)}%"></span>
                <span class="details-stat-fill details-fill-wait" style="width:${toPct(remainingCount, total)}%"></span>
            </div>
        </div>
        <div class="details-stat-card">
            <div class="details-stat-label">Risk split</div>
            <div class="details-stat-value">${highCount} / ${midCount} / ${lowCount}</div>
            <div class="details-stat-sub">High / Medium / Low</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-high" style="width:${toPct(highCount, total)}%"></span>
                <span class="details-stat-fill details-fill-mid" style="width:${toPct(midCount, total)}%"></span>
                <span class="details-stat-fill details-fill-low" style="width:${toPct(lowCount, total)}%"></span>
            </div>
        </div>
        <div class="details-stat-card">
            <div class="details-stat-label">Semgrep</div>
            <div class="details-stat-value">${issueCount} / ${cleanCount} / ${runningCount}</div>
            <div class="details-stat-sub">Issue / Clean / Running</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-issue" style="width:${toPct(issueCount, total)}%"></span>
                <span class="details-stat-fill details-fill-clean" style="width:${toPct(cleanCount, total)}%"></span>
                <span class="details-stat-fill details-fill-wait" style="width:${toPct(waitingCount, total)}%"></span>
                <span class="details-stat-fill details-fill-fail" style="width:${toPct(failedCount, total)}%"></span>
            </div>
        </div>
    `;
}

function renderCatalogRows(items) {
    const list = document.getElementById('catalog-list');
    if (!list) return;

    const safeItems = items || [];
    catalogFilteredCache = safeItems;

    const totalPages = Math.max(1, Math.ceil(safeItems.length / CATALOG_PAGE_SIZE));
    catalogCurrentPage = Math.min(Math.max(1, catalogCurrentPage), totalPages);
    const pageStart = (catalogCurrentPage - 1) * CATALOG_PAGE_SIZE;
    const pagedItems = safeItems.slice(pageStart, pageStart + CATALOG_PAGE_SIZE);

    updateTablePagination('catalog', safeItems.length, catalogCurrentPage, CATALOG_PAGE_SIZE);

    if (safeItems.length === 0) {
        list.innerHTML = '<tr><td colspan="7" class="favorites-empty">No plugins in store</td></tr>';
        return;
    }

    const maxInstalls = pagedItems.reduce((max, item) => {
        const installs = parseInt(item.latest_installations || 0, 10) || 0;
        return Math.max(max, installs);
    }, 1);

    list.innerHTML = pagedItems.map((item) => {
        const slug = String(item.slug || 'unknown-plugin');
        const isTheme = !!item.is_theme;
        const modeClass = isTheme ? 'theme' : 'plugin';
        const modeLabel = isTheme ? 'THEME' : 'PLUGIN';
        const seenCount = parseInt(item.seen_count || 0, 10) || 0;
        const latestScore = parseInt(item.latest_score || 0, 10) || 0;
        const maxScore = parseInt(item.max_score_ever || 0, 10) || 0;
        const score = Math.max(latestScore, maxScore);
        const scoreClass = getRiskClassForResult(score);
        const scoreRatio = Math.max(0, Math.min(100, score));
        const installs = parseInt(item.latest_installations || 0, 10) || 0;
        const rawInstallsRatio = maxInstalls > 0 ? Math.min(100, Math.round((installs / maxInstalls) * 100)) : 0;
        const installsRatio = installs > 0 ? Math.max(4, rawInstallsRatio) : 0;
        const installsLevel = installsRatio >= 70 ? 'high' : (installsRatio >= 35 ? 'medium' : 'low');
        const updatedLabel = getUpdatedLabel(parseDaysSinceUpdate(item.latest_days_since_update));

        const semgrep = item.semgrep || null;
        const semgrepCount = semgrep ? (parseInt(semgrep.findings_count || 0, 10) || 0) : (parseInt(item.latest_semgrep_findings || 0, 10) || 0);
        const semgrepStatus = semgrep ? String(semgrep.status || '').toLowerCase() : '';
        let semgrepTone = 'empty';
        let semgrepState = 'WAIT';
        let semgrepProgress = 0;
        if (semgrepStatus === 'completed') {
            semgrepTone = semgrepCount > 0 ? 'alert' : 'complete';
            semgrepState = semgrepCount > 0 ? 'ISSUE' : 'CLEAN';
            semgrepProgress = 100;
        } else if (semgrepStatus === 'running' || semgrepStatus === 'pending') {
            semgrepTone = 'running';
            semgrepState = 'SCANNING';
            semgrepProgress = 35;
        } else if (semgrepStatus === 'failed') {
            semgrepTone = 'alert';
            semgrepState = 'FAIL';
            semgrepProgress = 100;
        }

        const latestSession = parseInt(item.last_seen_session_id || 0, 10) || 0;
        const wpLink = isTheme ? `https://wordpress.org/themes/${slug}/` : `https://wordpress.org/plugins/${slug}/`;
        const lastSeen = item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : '';

        const pluginJson = JSON.stringify({
            slug,
            name: slug,
            version: item.latest_version || 'n/a',
            score,
            installations: installs,
            days_since_update: parseInt(item.latest_days_since_update || 0, 10) || 0,
            is_theme: isTheme,
            wp_org_link: wpLink,
            trac_link: isTheme ? `https://themes.trac.wordpress.org/log/${slug}/` : `https://plugins.trac.wordpress.org/log/${slug}/`,
        });

        return `
            <tr class="history-row details-results-row" tabindex="0" onclick='openCatalogPlugin(${pluginJson}, ${latestSession})' onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openCatalogPlugin(${pluginJson}, ${latestSession});}">
                <td class="details-col-slug">
                    <span class="details-slug">${escapeHtml(slug)}</span>
                </td>
                <td class="details-col-version"><span class="history-semgrep-pill">${escapeHtml(String(item.latest_version || 'n/a'))}</span></td>
                <td class="details-col-score">
                    <div class="history-risk-cell" title="Risk ${score} (latest ${latestScore}, max ${maxScore})">
                        <span class="history-risk-pill ${scoreClass}">${score}</span>
                        <span class="history-risk-meter"><span class="history-risk-fill ${scoreClass}" style="width:${scoreRatio}%;"></span></span>
                    </div>
                </td>
                <td class="details-col-updated"><span class="history-date-stamp">${escapeHtml(updatedLabel)}</span></td>
                <td class="details-col-installs">
                    <div class="history-found-cell" title="${installs.toLocaleString()} installs / last seen ${escapeHtml(lastSeen)}">
                        <span class="history-found-count">${escapeHtml(formatInstallCount(installs))}</span>
                        <span class="history-found-label">installs</span>
                        <span class="history-found-track"><span class="history-found-fill ${installsLevel}" style="width:${installsRatio}%;"></span></span>
                    </div>
                </td>
                <td class="details-col-semgrep">
                    <div class="history-semgrep-cell ${semgrepTone}">
                        <span class="history-semgrep-pill">${escapeHtml(String(semgrepCount || '--'))}</span>
                        <span class="history-semgrep-meter"><span class="history-semgrep-fill" style="width:${semgrepProgress}%;"></span></span>
                        <span class="history-semgrep-state">${escapeHtml(semgrepState)}</span>
                    </div>
                </td>
                <td class="details-col-actions">
                    <div class="details-row-actions">
                        <span class="history-mode-chip ${modeClass}">${escapeHtml(modeLabel)}</span>
                        <a href="${escapeHtml(wpLink)}" target="_blank" rel="noreferrer noopener" onclick="event.stopPropagation();" class="action-btn details-wp-btn" aria-label="Open on WordPress.org" title="Open on WordPress.org">
                            <span class="wp-logo-icon" aria-hidden="true"></span>
                        </a>
                        <button onclick='event.stopPropagation(); openCatalogPlugin(${pluginJson}, ${latestSession})' class="action-btn details-open-btn">Details</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function applyCatalogFilters() {
    catalogCurrentPage = 1;
    const filtered = filterCatalogPlugins(catalogPluginsCache, getCatalogFilterState());
    renderCatalogDashboard(filtered);
    renderCatalogRows(filtered);
}

function initializeCatalogFilters() {
    if (catalogFiltersInitialized) return;
    const queryEl = document.getElementById('catalog-filter-query');
    const sortEl = document.getElementById('catalog-filter-sort');
    const typeEl = document.getElementById('catalog-filter-type');
    const orderEl = document.getElementById('catalog-filter-order');

    const controls = [queryEl, sortEl, typeEl, orderEl].filter(Boolean);
    if (controls.length === 0) return;

    controls.forEach((control) => {
        const eventName = control.tagName === 'SELECT' ? 'change' : 'input';
        control.addEventListener(eventName, applyCatalogFilters);
    });

    catalogFiltersInitialized = true;
}

window.loadCatalog = async function() {
    const list = document.getElementById('catalog-list');
    if (!list) return;
    renderCatalogDashboard([]);
    list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Loading plugin store...</td></tr>';

    try {
        const pageSize = 1000;
        let offset = 0;
        let total = null;
        const mergedItems = [];

        while (total === null || mergedItems.length < total) {
            const response = await fetch(`/api/catalog/plugins?limit=${pageSize}&offset=${offset}&sort_by=last_seen&order=desc`);
            const data = await response.json();
            const items = data.items || [];

            if (total === null) total = parseInt(data.total || 0, 10) || 0;
            mergedItems.push(...items);

            if (items.length === 0) break;
            offset += items.length;

            // Safety guard to avoid infinite loops on malformed responses.
            if (offset > 200000) break;
        }

        catalogPluginsCache = mergedItems;
        initializeCatalogFilters();
        applyCatalogFilters();
    } catch (error) {
        console.error(error);
        renderCatalogDashboard([]);
        list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Failed to load plugin store</td></tr>';
    }
}

window.openCatalogSession = function(sessionId) {
    if (!sessionId) return;
    viewScan(sessionId);
}

window.openCatalogPlugin = function(plugin, sessionId = 0) {
    if (!plugin || !plugin.slug) return;
    if (sessionId) currentScanId = sessionId;
    window.currentScanResults = [plugin];
    openPluginModal(0);
}

function setDetailsBulkRunLabel(runBtn, label) {
    runBtn.innerHTML = `<span class="semgrep-logo-icon" aria-hidden="true"></span><span class="semgrep-btn-label">${escapeHtml(label)}</span>`;
}

function setDetailsBulkControls(state, meta = {}) {
    const runBtn = document.getElementById('details-bulk-run');
    const stopBtn = document.getElementById('details-bulk-stop');

    if (!runBtn || !stopBtn) return;

    if (state === 'running') {
        const scanned = Number(meta.scanned || 0);
        const total = Number(meta.total || 0);
        const currentSlug = String(meta.currentSlug || '').trim();
        runBtn.disabled = true;
        setDetailsBulkRunLabel(runBtn, 'Scanning...');
        runBtn.title = currentSlug
            ? `Scanning ${scanned}/${total}: ${currentSlug}`
            : `Scanning ${scanned}/${total}`;
        stopBtn.style.display = 'inline-flex';
        stopBtn.disabled = false;
        return;
    }

    if (state === 'paused') {
        runBtn.disabled = false;
        setDetailsBulkRunLabel(runBtn, 'Resume Scan All');
        runBtn.title = 'Bulk Semgrep paused';
        stopBtn.style.display = 'none';
        return;
    }

    if (state === 'completed') {
        runBtn.disabled = false;
        setDetailsBulkRunLabel(runBtn, 'Scan All (Semgrep)');
        const findings = Number(meta.findings || 0);
        runBtn.title = `Completed${Number.isFinite(findings) ? `: ${findings} findings` : ''}`;
        stopBtn.style.display = 'none';
        return;
    }

    runBtn.disabled = false;
    setDetailsBulkRunLabel(runBtn, 'Scan All (Semgrep)');
    runBtn.title = '';
    stopBtn.style.display = 'none';
}

function refreshDetailsRowsPreservePage() {
    const filtered = filterDetailsResults(detailsSourceCache, getDetailsFilterState());
    const totalPages = Math.max(1, Math.ceil((filtered.length || 0) / DETAILS_PAGE_SIZE));
    detailsCurrentPage = Math.min(Math.max(1, detailsCurrentPage), totalPages);
    renderDetailsRows(filtered);
}

function autoAdvanceDetailsPageIfNeeded() {
    const totalPages = Math.max(1, Math.ceil((detailsResultsCache.length || 0) / DETAILS_PAGE_SIZE));
    if (detailsCurrentPage >= totalPages) return;

    const start = (detailsCurrentPage - 1) * DETAILS_PAGE_SIZE;
    const pageRows = (detailsResultsCache || []).slice(start, start + DETAILS_PAGE_SIZE);
    if (pageRows.length === 0) return;

    const hasWaiting = pageRows.some((r) => !r.semgrep || !r.semgrep.status || ['pending'].includes(String(r.semgrep.status).toLowerCase()));
    const hasRunning = pageRows.some((r) => r.semgrep && ['running'].includes(String(r.semgrep.status).toLowerCase()));

    if (!hasWaiting && !hasRunning) {
        detailsCurrentPage = Math.min(detailsCurrentPage + 1, totalPages);
        renderDetailsRows(detailsResultsCache);
    }
}

async function refreshDetailsBulkStatus(sessionId) {
    const statsResp = await fetch(`/api/semgrep/bulk/${sessionId}/stats`);
    const stats = await statsResp.json();

    const resultsResp = await fetch(apiNoCacheUrl(`/api/scans/${sessionId}/results?limit=500`));
    const resultsData = await resultsResp.json();
    window.currentScanResults = resultsData.results || [];
    detailsSourceCache = window.currentScanResults;

    let currentSlug = '';
    const runningItem = window.currentScanResults.find((r) => r.semgrep && ['running', 'pending'].includes(String(r.semgrep.status || '').toLowerCase()));
    if (runningItem) currentSlug = String(runningItem.slug || '');

    renderDetailsDashboard(window.currentScanResults);
    refreshDetailsRowsPreservePage();

    const runningCount = Number(stats.running_count || 0);
    const pendingCount = Number(stats.pending_count || 0);
    const total = Number(stats.total_plugins || 0);
    const scanned = Number(stats.scanned_count || 0);

    if (stats.is_running) {
        setDetailsBulkControls('running', {
            scanned,
            total,
            currentSlug,
        });
        autoAdvanceDetailsPageIfNeeded();
    } else if (runningCount === 0 && pendingCount === 0 && scanned > 0) {
        setDetailsBulkControls('completed', { findings: stats.total_findings || 0 });
    } else if ((runningCount > 0 || pendingCount > 0) && scanned > 0) {
        setDetailsBulkControls('paused');
    } else if (total > 0 && scanned >= total) {
        setDetailsBulkControls('completed', { findings: stats.total_findings || 0 });
    } else {
        setDetailsBulkControls('idle');
    }

    return stats;
}

window.startDetailsBulkSemgrep = async function() {
    if (!currentScanId) return;

    try {
        const rulesResponse = await fetch('/api/semgrep/rules');
        const rulesData = await rulesResponse.json();
        const activeRulesets = (rulesData.rulesets || []).filter(r => r.enabled).length;
        const activeCustomRules = (rulesData.custom_rules || []).filter(r => r.enabled).length;
        if (activeRulesets === 0 && activeCustomRules === 0) {
            showToast('Semgrep is disabled. Enable at least one ruleset first.', 'warn');
            switchTab('semgrep');
            return;
        }
    } catch (e) {
        showToast('Failed to check Semgrep configuration.', 'error');
        return;
    }

    const confirmed = await showConfirm('Start Semgrep scan for all plugins in this scan?');
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/semgrep/bulk/${currentScanId}`, { method: 'POST' });
        const data = await response.json();
        if (!data.success) {
            showToast('Failed to start bulk scan: ' + (data.detail || 'Unknown error'), 'error');
            return;
        }

        detailsBulkRunning = true;
        setDetailsBulkControls('running', { scanned: 0, total: data.count || 0 });

        if (detailsBulkPollingInterval) clearInterval(detailsBulkPollingInterval);
        detailsBulkPollingInterval = setInterval(async () => {
            try {
                const stats = await refreshDetailsBulkStatus(currentScanId);
                if (!stats.is_running) {
                    clearInterval(detailsBulkPollingInterval);
                    detailsBulkPollingInterval = null;
                    detailsBulkRunning = false;
                }
            } catch (err) {
                console.error('Details bulk polling error', err);
            }
        }, 1500);
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

window.stopDetailsBulkSemgrep = async function() {
    if (!currentScanId) return;
    const confirmed = await showConfirm('Stop bulk Semgrep scan?');
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/semgrep/bulk/${currentScanId}/stop`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            setDetailsBulkControls('paused');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function getDetailsFilterState() {
    const queryEl = document.getElementById('details-filter-query');
    const installsEl = document.getElementById('details-filter-installs');
    const sortEl = document.getElementById('details-filter-sort');
    const updatedSortEl = document.getElementById('details-filter-updated-sort');

    return {
        query: String(queryEl ? queryEl.value : '').trim().toLowerCase(),
        installs: String(installsEl ? installsEl.value : 'default').toLowerCase(),
        sort: String(sortEl ? sortEl.value : 'default').toLowerCase(),
        updatedSort: String(updatedSortEl ? updatedSortEl.value : 'default').toLowerCase()
    };
}

function getDetailsSemgrepState(result) {
    const semgrep = result && result.semgrep ? result.semgrep : null;
    if (!semgrep) return 'wait';

    const status = String(semgrep.status || '').toLowerCase();
    if (status === 'running' || status === 'pending') return 'run';
    if (status === 'failed') return 'fail';
    if (status === 'completed') {
        const findings = parseInt(semgrep.findings_count || 0, 10) || 0;
        return findings > 0 ? 'issue' : 'clean';
    }

    return 'wait';
}

function getDetailsSemgrepIssueCount(result) {
    if (!result || !result.semgrep) return 0;
    const status = String(result.semgrep.status || '').toLowerCase();
    if (status !== 'completed') return 0;
    return parseInt(result.semgrep.findings_count || 0, 10) || 0;
}

function getDetailsUpdatedDays(result) {
    const days = parseDaysSinceUpdate(result && result.days_since_update);
    return days == null ? Number.POSITIVE_INFINITY : days;
}

function renderDetailsDashboard(results) {
    const dashboard = document.getElementById('details-dashboard');
    if (!dashboard) return;

    const rows = Array.isArray(results) ? results : [];
    const total = rows.length;

    if (total === 0) {
        dashboard.innerHTML = '';
        return;
    }

    const highCount = rows.filter(r => (parseInt(r && r.score || 0, 10) || 0) >= 40).length;
    const midCount = rows.filter(r => {
        const score = parseInt(r && r.score || 0, 10) || 0;
        return score >= 20 && score < 40;
    }).length;
    const lowCount = Math.max(0, total - highCount - midCount);

    let issueCount = 0;
    let cleanCount = 0;
    let waitingCount = 0;
    let failedCount = 0;
    let runningCount = 0;

    rows.forEach((r) => {
        const semgrep = r && r.semgrep ? r.semgrep : null;
        if (!semgrep) {
            waitingCount += 1;
            return;
        }

        const status = String(semgrep.status || '').toLowerCase();
        if (status === 'completed') {
            const findings = parseInt(semgrep.findings_count || 0, 10) || 0;
            if (findings > 0) issueCount += 1;
            else cleanCount += 1;
            return;
        }
        if (status === 'failed') {
            failedCount += 1;
            return;
        }
        if (status === 'running' || status === 'pending') {
            runningCount += 1;
            return;
        }

        waitingCount += 1;
    });

    const scannedCount = issueCount + cleanCount + failedCount;
    const remainingCount = Math.max(0, total - scannedCount);
    const toPct = (value, sum) => {
        if (!sum || sum <= 0) return 0;
        return Math.max(0, Math.min(100, Math.round((value / sum) * 100)));
    };

    dashboard.innerHTML = `
        <div class="details-stat-card details-stat-card-total">
            <div class="details-stat-label">Scan inventory</div>
            <div class="details-stat-value">${total}</div>
            <div class="details-stat-sub">Total plugins/themes in this scan</div>
            <div class="details-stat-track"><span class="details-stat-fill details-fill-blue" style="width:100%"></span></div>
        </div>
        <div class="details-stat-card details-stat-card-progress">
            <div class="details-stat-label">Semgrep progress</div>
            <div class="details-stat-value">${scannedCount} / ${total}</div>
            <div class="details-stat-sub">Processed / Total • ${remainingCount} remaining</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-primary" style="width:${toPct(scannedCount, total)}%"></span>
                <span class="details-stat-fill details-fill-wait" style="width:${toPct(remainingCount, total)}%"></span>
            </div>
        </div>
        <div class="details-stat-card">
            <div class="details-stat-label">Risk split</div>
            <div class="details-stat-value">${highCount} / ${midCount} / ${lowCount}</div>
            <div class="details-stat-sub">High / Medium / Low</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-high" style="width:${toPct(highCount, total)}%"></span>
                <span class="details-stat-fill details-fill-mid" style="width:${toPct(midCount, total)}%"></span>
                <span class="details-stat-fill details-fill-low" style="width:${toPct(lowCount, total)}%"></span>
            </div>
        </div>
        <div class="details-stat-card">
            <div class="details-stat-label">Semgrep</div>
            <div class="details-stat-value">${issueCount} / ${cleanCount} / ${runningCount}</div>
            <div class="details-stat-sub">Issue / Clean / Running</div>
            <div class="details-stat-track">
                <span class="details-stat-fill details-fill-issue" style="width:${toPct(issueCount, total)}%"></span>
                <span class="details-stat-fill details-fill-clean" style="width:${toPct(cleanCount, total)}%"></span>
                <span class="details-stat-fill details-fill-wait" style="width:${toPct(waitingCount, total)}%"></span>
                <span class="details-stat-fill details-fill-fail" style="width:${toPct(failedCount, total)}%"></span>
            </div>
        </div>
    `;
}

function sortDetailsResults(results, sortState) {
    const safeResults = Array.isArray(results) ? [...results] : [];
    const state = sortState || {};
    const comparators = [];

    if (state.sort === 'semgrep_desc') {
        comparators.push((a, b) => getDetailsSemgrepIssueCount(b) - getDetailsSemgrepIssueCount(a));
        comparators.push((a, b) => (parseInt(b && b.score || 0, 10) || 0) - (parseInt(a && a.score || 0, 10) || 0));
    } else if (state.sort === 'semgrep_asc') {
        comparators.push((a, b) => getDetailsSemgrepIssueCount(a) - getDetailsSemgrepIssueCount(b));
        comparators.push((a, b) => (parseInt(b && b.score || 0, 10) || 0) - (parseInt(a && a.score || 0, 10) || 0));
    } else if (state.sort === 'score_desc') {
        comparators.push((a, b) => (parseInt(b && b.score || 0, 10) || 0) - (parseInt(a && a.score || 0, 10) || 0));
    } else if (state.sort === 'score_asc') {
        comparators.push((a, b) => (parseInt(a && a.score || 0, 10) || 0) - (parseInt(b && b.score || 0, 10) || 0));
    }

    if (state.installs === 'installs_desc') {
        comparators.push((a, b) => (parseInt(b && b.installations || 0, 10) || 0) - (parseInt(a && a.installations || 0, 10) || 0));
    } else if (state.installs === 'installs_asc') {
        comparators.push((a, b) => (parseInt(a && a.installations || 0, 10) || 0) - (parseInt(b && b.installations || 0, 10) || 0));
    }

    if (state.updatedSort === 'updated_newest') {
        comparators.push((a, b) => getDetailsUpdatedDays(a) - getDetailsUpdatedDays(b));
    } else if (state.updatedSort === 'updated_oldest') {
        comparators.push((a, b) => getDetailsUpdatedDays(b) - getDetailsUpdatedDays(a));
    }

    if (comparators.length === 0) return safeResults;

    safeResults.sort((a, b) => {
        for (const comparator of comparators) {
            const diff = comparator(a, b);
            if (diff !== 0) return diff;
        }
        return 0;
    });

    return safeResults;
}

function filterDetailsResults(results, filterState) {
    const state = filterState || getDetailsFilterState();

    const filtered = (results || []).filter((result) => {
        const slug = String((result && result.slug) || '').toLowerCase();
        const version = String((result && result.version) || '').toLowerCase();
        const semgrepState = getDetailsSemgrepState(result);
        const semgrepIssues = getDetailsSemgrepIssueCount(result);
        const risk = getRiskClassForResult(parseInt((result && result.score) || 0, 10) || 0);
        const installs = parseInt((result && result.installations) || 0, 10) || 0;
        const updatedDays = getDetailsUpdatedDays(result);

        if (state.query) {
            const haystack = `${slug} ${version} ${semgrepState} ${risk} ${semgrepIssues} ${installs} ${updatedDays}`;
            if (!haystack.includes(state.query)) return false;
        }

        return true;
    });

    return sortDetailsResults(filtered, state);
}

function applyDetailsFilters() {
    detailsCurrentPage = 1;
    const filtered = filterDetailsResults(detailsSourceCache, getDetailsFilterState());
    renderDetailsRows(filtered);
}

function renderDetailsRows(results) {
    const list = document.getElementById('details-list');
    if (!list) return;

    const safeResults = results || [];
    detailsResultsCache = safeResults;

    const totalPages = Math.max(1, Math.ceil(safeResults.length / DETAILS_PAGE_SIZE));
    detailsCurrentPage = Math.min(Math.max(1, detailsCurrentPage), totalPages);
    const pageStart = (detailsCurrentPage - 1) * DETAILS_PAGE_SIZE;
    const pagedResults = safeResults.slice(pageStart, pageStart + DETAILS_PAGE_SIZE);

    updateTablePagination('details', safeResults.length, detailsCurrentPage, DETAILS_PAGE_SIZE);

    if (safeResults.length === 0) {
        list.innerHTML = '<tr><td colspan="7" class="favorites-empty">No plugins match the current filters</td></tr>';
        return;
    }

    const maxInstalls = safeResults.reduce((max, item) => {
        const installs = parseInt(item.installations || 0, 10) || 0;
        return Math.max(max, installs);
    }, 1);

    list.innerHTML = pagedResults.map((r) => {
        const index = window.currentScanResults.indexOf(r);
        const slug = String(r.slug || 'unknown-plugin');
        const slugJs = JSON.stringify(slug);
        const score = parseInt(r.score || 0, 10) || 0;
        const scoreRatio = Math.max(0, Math.min(100, score));
        const riskClass = getRiskClassForResult(score);
        const installs = parseInt(r.installations || 0, 10) || 0;
        const installsRatio = maxInstalls > 0 ? Math.min(100, Math.round((installs / maxInstalls) * 100)) : 0;
        const installsLevel = installsRatio >= 70 ? 'high' : (installsRatio >= 35 ? 'medium' : 'low');
        const modeClass = r.is_theme ? 'theme' : 'plugin';
        const modeLabel = modeClass.toUpperCase();

        let semgrepTone = 'empty';
        let semgrepCount = '--';
        let semgrepState = 'WAIT';
        let semgrepProgress = 0;
        let semgrepTitle = 'Semgrep has not run for this plugin yet.';
        if (r.semgrep) {
            if (r.semgrep.status === 'completed') {
                const issues = parseInt(r.semgrep.findings_count || 0, 10) || 0;
                semgrepTone = issues > 0 ? 'alert' : 'complete';
                semgrepCount = String(issues);
                semgrepState = issues > 0 ? 'ISSUE' : 'CLEAN';
                semgrepProgress = 100;
                semgrepTitle = issues > 0
                    ? `${issues} finding(s) detected for ${slug}.`
                    : `No findings detected for ${slug}.`;
            } else if (r.semgrep.status === 'running' || r.semgrep.status === 'pending') {
                semgrepTone = 'running';
                semgrepCount = '--';
                semgrepState = 'SCANNING';
                semgrepProgress = 35;
                semgrepTitle = `Semgrep scan is running for ${slug}.`;
            } else if (r.semgrep.status === 'failed') {
                semgrepTone = 'alert';
                semgrepCount = 'ERR';
                semgrepState = 'FAIL';
                semgrepProgress = 100;
                semgrepTitle = `Semgrep scan failed for ${slug}.`;
            }
        }

        const days = parseDaysSinceUpdate(r.days_since_update);
        const updatedLabel = getUpdatedLabel(days);
        const isFav = isFavoriteSlug(slug);
        const wpLink = r.wp_org_link || (r.is_theme ? `https://wordpress.org/themes/${slug}/` : `https://wordpress.org/plugins/${slug}/`);

        return `
            <tr class="history-row details-results-row" tabindex="0" onclick="openPluginModal(${index})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPluginModal(${index});}">
                <td class="details-col-slug">
                    <span class="details-slug">${escapeHtml(slug)}</span>
                    ${r.is_duplicate ? '<span class="details-dup-chip">Seen Before · DB</span>' : ''}
                </td>
                <td class="details-col-version"><span class="history-semgrep-pill">${escapeHtml(String(r.version || 'n/a'))}</span></td>
                <td class="details-col-score">
                    <div class="history-risk-cell" title="Risk score ${score}">
                        <span class="history-risk-pill ${riskClass}">${score}</span>
                        <span class="history-risk-meter"><span class="history-risk-fill ${riskClass}" style="width:${scoreRatio}%;"></span></span>
                    </div>
                </td>
                <td class="details-col-updated"><span class="history-date-stamp">${escapeHtml(updatedLabel)}</span></td>
                <td class="details-col-installs">
                    <div class="history-found-cell" title="${installs.toLocaleString()} installs">
                        <span class="history-found-count">${escapeHtml(formatInstallCount(installs))}</span>
                        <span class="history-found-label">installs</span>
                        <span class="history-found-track"><span class="history-found-fill ${installsLevel}" style="width: ${installsRatio}%;"></span></span>
                    </div>
                </td>
                <td class="details-col-semgrep">
                    <div class="history-semgrep-cell ${semgrepTone}" title="${escapeHtml(semgrepTitle)}">
                        <span class="history-semgrep-pill">${escapeHtml(semgrepCount)}</span>
                        <span class="history-semgrep-meter"><span class="history-semgrep-fill" style="width: ${semgrepProgress}%;"></span></span>
                        <span class="history-semgrep-state">${escapeHtml(semgrepState)}</span>
                    </div>
                </td>
                <td class="details-col-actions">
                    <div class="details-row-actions">
                        <span class="history-mode-chip ${modeClass}">${escapeHtml(modeLabel)}</span>
                        <button onclick='event.stopPropagation(); toggleFavorite(${slugJs})' class="action-btn details-fav-btn${isFav ? ' active' : ''}" title="${isFav ? 'In Favorites' : 'Add to Favorites'}" aria-label="Toggle favorite ${escapeHtml(slug)}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                        </button>
                        <a href="${escapeHtml(wpLink)}" target="_blank" rel="noreferrer noopener" onclick="event.stopPropagation();" class="action-btn details-wp-btn" aria-label="Open on WordPress.org" title="Open on WordPress.org">
                            <span class="wp-logo-icon" aria-hidden="true"></span>
                        </a>
                        <button onclick="event.stopPropagation(); openPluginModal(${index})" class="action-btn details-open-btn">Details</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function initializeHistoryFilters() {
    if (historyFiltersInitialized) return;
    const queryEl = document.getElementById('history-filter-query');
    const statusEl = document.getElementById('history-filter-status');
    const modeEl = document.getElementById('history-filter-mode');
    const riskEl = document.getElementById('history-filter-risk');

    const controls = [queryEl, statusEl, modeEl, riskEl].filter(Boolean);
    if (controls.length === 0) return;

    controls.forEach((control) => {
        const eventName = control.tagName === 'SELECT' ? 'change' : 'input';
        control.addEventListener(eventName, applyHistoryFilters);
    });

    historyFiltersInitialized = true;
}

function initializeDetailsFilters() {
    if (detailsFiltersInitialized) return;
    const queryEl = document.getElementById('details-filter-query');
    const installsEl = document.getElementById('details-filter-installs');
    const sortEl = document.getElementById('details-filter-sort');
    const updatedSortEl = document.getElementById('details-filter-updated-sort');

    const controls = [queryEl, installsEl, sortEl, updatedSortEl].filter(Boolean);
    if (controls.length === 0) return;

    controls.forEach((control) => {
        const eventName = control.tagName === 'SELECT' ? 'change' : 'input';
        control.addEventListener(eventName, applyDetailsFilters);
    });

    detailsFiltersInitialized = true;
}

function getHistorySemgrepState(stats, isThemeSession = false) {
    if (isThemeSession) {
        return {
            cls: 'na',
            state: 'N/A',
            count: '--',
            progress: 0,
            title: 'Semgrep is not available for theme sessions.'
        };
    }

    if (!stats) {
        return {
            cls: 'empty',
            state: 'WAIT',
            count: '--/--',
            progress: 0,
            title: 'Semgrep data is not available for this session yet.'
        };
    }

    const scannedCount = parseInt(stats.scanned_count || 0, 10) || 0;
    const totalPlugins = parseInt(stats.total_plugins || 0, 10) || 0;
    const totalFindings = parseInt(stats.total_findings || 0, 10) || 0;
    const progress = Math.max(0, Math.min(100, parseInt(stats.progress || 0, 10) || 0));
    const safeTotal = totalPlugins > 0 ? totalPlugins : Math.max(scannedCount, 0);
    const pair = safeTotal > 0 ? `${scannedCount}/${safeTotal}` : '--/--';

    if (stats.is_running) {
        return {
            cls: 'running',
            state: 'RUN',
            count: pair,
            progress,
            title: `Semgrep scanning in progress (${progress}% - ${pair}).`
        };
    }

    if (scannedCount === 0) {
        return {
            cls: 'empty',
            state: 'WAIT',
            count: safeTotal > 0 ? `0/${safeTotal}` : '0/0',
            progress: 0,
            title: 'Semgrep has not run for this session yet.'
        };
    }

    if (progress >= 100 || (safeTotal > 0 && scannedCount >= safeTotal)) {
        if (totalFindings > 0) {
            return {
                cls: 'alert',
                state: 'ISSUE',
                count: String(totalFindings),
                progress: 100,
                title: `${totalFindings} findings detected (${pair} analyzed).`
            };
        }
        return {
            cls: 'complete',
            state: 'CLEAN',
            count: pair,
            progress: 100,
            title: `Semgrep completed clean (${pair} analyzed).`
        };
    }

    return {
        cls: 'partial',
        state: 'PART',
        count: pair,
        progress,
        title: `Partial semgrep progress (${pair}, ${totalFindings} findings).`
    };
}

function applyHistorySemgrepBadge(sessionId, stats, isThemeSession = false) {
    const cell = document.getElementById(`history-semgrep-${sessionId}`);
    const stateEl = document.getElementById(`history-semgrep-state-${sessionId}`);
    const countEl = document.getElementById(`history-semgrep-count-${sessionId}`);
    const fillEl = document.getElementById(`history-semgrep-fill-${sessionId}`);
    if (!cell || !stateEl || !countEl || !fillEl) return;

    const state = getHistorySemgrepState(stats, isThemeSession);
    cell.className = `history-semgrep-cell ${state.cls}`;
    cell.title = state.title;
    stateEl.textContent = state.state;
    countEl.textContent = state.count;
    fillEl.style.width = `${state.progress}%`;
}

async function hydrateHistorySemgrepBadges(sessions) {
    const pending = sessions.map(async (session) => {
        const sessionId = parseInt(session.id, 10);
        if (!Number.isFinite(sessionId) || sessionId <= 0) return;

        const config = session.config || {};
        const isThemeSession = Boolean(config.themes);
        if (isThemeSession) {
            applyHistorySemgrepBadge(sessionId, null, true);
            return;
        }

        const cached = historySemgrepStatsCache.get(sessionId);
        if (cached) {
            applyHistorySemgrepBadge(sessionId, cached, false);
            return;
        }

        try {
            const response = await fetch(apiNoCacheUrl(`/api/semgrep/bulk/${sessionId}/stats`));
            if (!response.ok) {
                applyHistorySemgrepBadge(sessionId, null, false);
                return;
            }
            const stats = await response.json();
            historySemgrepStatsCache.set(sessionId, stats);
            applyHistorySemgrepBadge(sessionId, stats, false);
        } catch (error) {
            applyHistorySemgrepBadge(sessionId, null, false);
        }
    });

    await Promise.allSettled(pending);
}

window.loadHistory = async function() {
    try {
        const response = await fetch(apiNoCacheUrl('/api/scans'));
        const data = await response.json();
        const sessions = (data.sessions || []).sort((a, b) => new Date(b.created_at || b.start_time) - new Date(a.created_at || a.start_time));
        historySessionsCache = sessions;
        refreshScanDashboard(sessions);
        initializeHistoryFilters();
        applyHistoryFilters();
    } catch (error) {
        const list = document.getElementById('history-list');
        historySessionsCache = [];
        if (list) list.innerHTML = '<tr><td colspan="8">Error loading history</td></tr>';
        refreshScanDashboard([]);
    }
}
window.refreshHistory = window.loadHistory;

window.deleteScan = async function(id) {
    const confirmed = await showConfirm('Are you sure you want to delete this scan session? This will remove all associated results from the database.');
    if (!confirmed) return;
    try {
        const response = await fetch(`/api/scans/${id}`, { method: 'DELETE' });
        if (response.ok) loadHistory();
        else {
            const err = await response.json();
            showToast('Failed to delete scan: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error deleting scan: ' + error.message, 'error');
    }
}

function formatInstallCount(value) {
    const installs = parseInt(value || 0, 10) || 0;
    if (installs >= 1000000) return `${(installs / 1000000).toFixed(1)}M`;
    if (installs >= 1000) return `${Math.round(installs / 1000)}K`;
    return String(installs);
}

function parseDaysSinceUpdate(value) {
    const parsed = parseInt(value, 10);
    return Number.isFinite(parsed) ? Math.max(0, parsed) : null;
}

function getRiskClassForResult(score) {
    if (score >= 40) return 'high';
    if (score >= 20) return 'medium';
    return 'low';
}

function getRiskColorForClass(riskClass) {
    if (riskClass === 'high') return '#ff5f56';
    if (riskClass === 'medium') return '#ffbd2e';
    return '#00f3ff';
}

function getRiskColorForScore(score) {
    return getRiskColorForClass(getRiskClassForResult(score));
}

function getUpdatedChipClass(daysSinceUpdate) {
    if (daysSinceUpdate == null) return '';
    if (daysSinceUpdate >= 365) return 'old';
    if (daysSinceUpdate >= 180) return 'stale';
    return '';
}

function getUpdatedLabel(daysSinceUpdate) {
    if (daysSinceUpdate == null) return 'N/A';
    if (daysSinceUpdate < 1) return 'today';
    if (daysSinceUpdate < 30) return `${daysSinceUpdate}d ago`;
    if (daysSinceUpdate < 365) return `${Math.round(daysSinceUpdate / 30)}mo ago`;
    return `${Math.round(daysSinceUpdate / 365)}y ago`;
}

window.loadFavorites = async function() {
    const list = document.getElementById('favorites-list');
    if (!list) return;
    list.innerHTML = '<tr><td colspan="7">Loading...</td></tr>';
    try {
        const resp = await fetch('/api/favorites');
        const data = await resp.json();
        
        window.currentScanResults = data.favorites || [];
        renderRecentFavorites(window.currentScanResults);

        const maxInstalls = window.currentScanResults.reduce((max, item) => {
            const installs = parseInt(item.installations || 0, 10) || 0;
            return Math.max(max, installs);
        }, 1);

        list.innerHTML = window.currentScanResults.map((r, index) => {
            const slug = String(r.slug || 'unknown-plugin');
            const slugJs = JSON.stringify(slug);
            const score = parseInt(r.score || 0, 10) || 0;
            const scoreLevel = getRiskClassForResult(score);
            const scoreRatio = Math.max(0, Math.min(100, score));
            const installs = parseInt(r.installations || 0, 10) || 0;
            const installsRatio = maxInstalls > 0 ? Math.min(100, Math.round((installs / maxInstalls) * 100)) : 0;
            const days = parseDaysSinceUpdate(r.days_since_update);
            const updatedClass = getUpdatedChipClass(days);
            const updatedLabel = getUpdatedLabel(days);
            const version = String(r.version || 'n/a');
            const modeClass = r.is_theme ? 'theme' : 'plugin';
            const modeLabel = modeClass.toUpperCase();

            return `
            <tr class="favorites-row" tabindex="0" onclick="openPluginModal(${index})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPluginModal(${index});}">
                <td class="favorites-col-slug">
                    <div class="favorites-slug">${escapeHtml(slug)}</div>
                </td>
                <td class="favorites-col-version"><span class="favorites-version-chip">${escapeHtml(version)}</span></td>
                <td class="favorites-col-installs">
                    <div class="favorites-installs" title="${installs.toLocaleString()} installs">
                        <span class="favorites-installs-count">${escapeHtml(formatInstallCount(installs))}</span>
                        <span class="favorites-installs-track"><span class="favorites-installs-fill" style="width: ${installsRatio}%;"></span></span>
                    </div>
                </td>
                <td class="favorites-col-score">
                    <div class="favorites-score" title="Risk score ${score}">
                        <span class="favorites-score-pill ${scoreLevel}">${score}</span>
                        <span class="favorites-score-meter"><span class="favorites-score-fill ${scoreLevel}" style="width: ${scoreRatio}%;"></span></span>
                    </div>
                </td>
                <td class="favorites-col-updated"><span class="favorites-updated-chip ${updatedClass}">${escapeHtml(updatedLabel)}</span></td>
                <td class="favorites-col-mode"><span class="history-mode-chip ${modeClass}">${escapeHtml(modeLabel)}</span></td>
                <td class="favorites-col-actions">
                    <div class="favorites-actions">
                        <span class="favorites-action-open" aria-hidden="true">
                            <span>Open</span>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                        </span>
                        <button onclick='event.stopPropagation(); removeFromFavorites(${slugJs})' class="action-btn favorites-action-delete" title="Remove Favorite" aria-label="Remove favorite ${escapeHtml(slug)}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
        }).join('');

        if (window.currentScanResults.length === 0) {
            list.innerHTML = '<tr><td colspan="7" class="favorites-empty">No favorites yet</td></tr>';
        }
    } catch(e) { 
        console.error(e);
        list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Error loading favorites</td></tr>'; 
    }
}

window.removeFromFavorites = async function(slug) {
    const confirmed = await showConfirm('Remove from favorites?');
    if(!confirmed) return;
    await fetch(`/api/favorites/${slug}`, {method: 'DELETE'});
    window.favoriteSlugs.delete(slug);
    refreshDashboardFavorites();
    loadFavorites();
}

window.toggleFavorite = async function(slug) {
    const plugin = window.currentScanResults.find(p => p.slug === slug);
    if (!plugin) return;

    // Prevent stale UI state (especially on direct plugin-detail refresh)
    await refreshFavoriteSlugs();
    const isAlreadyFavorite = isFavoriteSlug(slug);

    if (!isAlreadyFavorite) {
        const response = await fetch('/api/favorites', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(plugin)
        });

        let res = { success: false };
        try {
            res = await response.json();
        } catch (_) {
            // keep fallback object
        }

        if (res.success) {
            window.favoriteSlugs.add(slug);
            showToast('Plugin added to favorites', 'success');
        } else {
            // Fallback: if backend said fail due duplicate/constraint, sync and treat as already favorite
            await refreshFavoriteSlugs();
            if (isFavoriteSlug(slug)) {
                showToast('Plugin is already in favorites', 'info');
            } else {
                showToast('Failed to add favorite', 'error');
            }
        }
    } else {
        const confirmed = await showConfirm('Remove from favorites?');
        if (!confirmed) return;
        await fetch(`/api/favorites/${slug}`, {method: 'DELETE'});
        window.favoriteSlugs.delete(slug);
        showToast('Plugin removed from favorites', 'info');
    }

    const state = getUrlState();
    if (state.view === 'plugin-detail') {
        const favBtn = document.getElementById('plugin-fav-btn');
        if (favBtn) {
            favBtn.classList.toggle('active', isFavoriteSlug(slug));
            favBtn.title = isFavoriteSlug(slug) ? 'In Favorites' : 'Add to Favorites';
            favBtn.setAttribute('aria-label', `${isFavoriteSlug(slug) ? 'Remove from' : 'Add to'} favorites`);
        }
    } else if (currentScanId) {
        viewScan(currentScanId);
    }

    refreshDashboardFavorites();
}

window.viewScan = async function(id, options = {}) {
    const { syncUrl = true } = options;
    switchTab('details', { syncUrl: false });
    currentScanId = id;
    if (syncUrl) {
        setUrlState({ view: 'details', scanId: id, plugin: '' }, { replace: false });
    }

    const list = document.getElementById('details-list');
    const title = document.getElementById('details-view-title');
    const desc = document.getElementById('details-view-desc');

    if (title) title.textContent = `SCAN #${id} DETAILS`;
    if (desc) desc.textContent = `Inspect plugins found in scan #${id} and review risk context.`;
    if (list) list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Loading results...</td></tr>';

    try {
        const sessionResp = await fetch(apiNoCacheUrl(`/api/scans/${id}`));
        const session = await sessionResp.json();

        const resultsResp = await fetch(apiNoCacheUrl(`/api/scans/${id}/results?limit=500`));
        const resultsData = await resultsResp.json();
        window.currentScanResults = resultsData.results || [];
        detailsSourceCache = window.currentScanResults;
        await refreshFavoriteSlugs();

        initializeDetailsFilters();
        detailsCurrentPage = 1;
        renderDetailsDashboard(window.currentScanResults);
        applyDetailsFilters();

        if (detailsBulkPollingInterval) {
            clearInterval(detailsBulkPollingInterval);
            detailsBulkPollingInterval = null;
        }
        const bulkStats = await refreshDetailsBulkStatus(id);
        if (bulkStats && bulkStats.is_running) {
            detailsBulkRunning = true;
            detailsBulkPollingInterval = setInterval(async () => {
                try {
                    const stats = await refreshDetailsBulkStatus(id);
                    if (!stats.is_running) {
                        clearInterval(detailsBulkPollingInterval);
                        detailsBulkPollingInterval = null;
                        detailsBulkRunning = false;
                    }
                } catch (err) {
                    console.error('Details bulk polling error', err);
                }
            }, 1500);
        } else {
            detailsBulkRunning = false;
        }

        if ((session.status || '').toUpperCase() === 'RUNNING') {
            if (detailsPollingInterval) clearInterval(detailsPollingInterval);
            detailsPollingInterval = setInterval(() => {
                if (currentScanId === id) {
                    window.viewScan(id);
                } else {
                    clearInterval(detailsPollingInterval);
                    detailsPollingInterval = null;
                }
            }, 3000);
        } else if (detailsPollingInterval) {
            clearInterval(detailsPollingInterval);
            detailsPollingInterval = null;
        }
    } catch (error) {
        setDetailsBulkControls('idle');
        renderDetailsDashboard([]);
        if (list) {
            list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Failed to load scan details</td></tr>';
        }
    }
}

window.downloadScanJSON = async function(id) {
    if (!id) return;
    try {
        const response = await fetch(`/api/scans/${id}/results?limit=9999`); // Get all results
        const data = await response.json();
        const jsonStr = JSON.stringify(data, null, 4);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `scan_${id}_results.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        showToast('Error downloading JSON: ' + error.message, 'error');
    }
}

window.runBulkSemgrep = async function(sessionId) {
    // Check if any rulesets are enabled
    try {
        const rulesResponse = await fetch('/api/semgrep/rules');
        const rulesData = await rulesResponse.json();
        const activeRulesets = (rulesData.rulesets || []).filter(r => r.enabled).length;
        const activeCustomRules = (rulesData.custom_rules || []).filter(r => r.enabled).length;

        if (activeRulesets === 0 && activeCustomRules === 0) {
            showToast('Semgrep is disabled. Please enable at least one ruleset in Semgrep Settings.', 'warn');
            // Redirect to semgrep settings
            switchTab('semgrep');
            return;
        }
    } catch (e) {
        showToast('Failed to check Semgrep configuration.', 'error');
        return;
    }

    const confirmed = await showConfirm('Start bulk Semgrep analysis for ALL plugins in this session? This may take a significant amount of time depending on the number of plugins.');
    if(!confirmed) return;

    const dashboard = document.getElementById('bulk-dashboard');
    const btn = document.getElementById('btn-bulk-scan');
    const stopBtn = document.getElementById('btn-bulk-stop');
    const statusEl = document.getElementById('bulk-status');
    const statusDot = document.getElementById('bulk-status-dot');
    const progressPercent = document.getElementById('bulk-progress-percent');

    if (dashboard) {
        dashboard.style.display = 'grid';
        dashboard.classList.remove('idle');
    }
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> Scanning...';
    }
    if(stopBtn) {
        stopBtn.style.display = 'inline-flex';
        stopBtn.disabled = false;
    }
    if(statusEl) {
        statusEl.textContent = 'Resuming';
        statusEl.className = 'bulk-status-chip';
    }
    if(statusDot) {
        statusDot.classList.remove('paused', 'completed');
        statusDot.style.background = 'var(--accent-blue)';
    }
    if (progressPercent) progressPercent.textContent = '0%';

    try {
        const response = await fetch(`/api/semgrep/bulk/${sessionId}`, { method: 'POST' });
        const data = await response.json();

        if(data.success) {
            pollBulkProgress(sessionId);
        } else {
            showToast('Failed to start bulk scan: ' + (data.detail || 'Unknown error'), 'error');
            if(btn) {
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> Scan All (Semgrep)';
            }
            if(stopBtn) stopBtn.style.display = 'none';
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
    }
}

window.stopBulkSemgrep = async function(sessionId) {
    const confirmed = await showConfirm('Stop the bulk Semgrep scan? You can resume it later from where it left off.');
    if(!confirmed) return;

    const btn = document.getElementById('btn-bulk-scan');
    const stopBtn = document.getElementById('btn-bulk-stop');
    const statusEl = document.getElementById('bulk-status');

    if(stopBtn) {
        stopBtn.disabled = true;
        stopBtn.textContent = 'Stopping...';
    }

    if(statusEl) {
        statusEl.textContent = 'Stopping';
        statusEl.className = 'bulk-status-chip paused';
    }

    const statusDot = document.getElementById('bulk-status-dot');
    if(statusDot) {
        statusDot.classList.add('paused');
        statusDot.style.background = '#ffbd2e';
    }

    try {
        const response = await fetch(`/api/semgrep/bulk/${sessionId}/stop`, { method: 'POST' });
        const data = await response.json();

        if(data.success) {
            showToast('Bulk scan stopped. You can resume anytime.', 'info');
            if(statusEl) {
                statusEl.textContent = 'Paused';
                statusEl.className = 'bulk-status-chip paused';
            }
            if(btn) {
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Resume Scan';
            }
            if(stopBtn) stopBtn.style.display = 'none';
        } else {
            showToast('Failed to stop: ' + (data.detail || 'Unknown error'), 'error');
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function pollBulkProgress(sessionId) {
    const dashboard = document.getElementById('bulk-dashboard');
    const statusEl = document.getElementById('bulk-status');
    const progressBar = document.getElementById('bulk-progress-bar');
    const scannedEl = document.getElementById('bulk-scanned');
    const totalEl = document.getElementById('bulk-total');
    const issuesEl = document.getElementById('bulk-issues');
    const errorCountEl = document.getElementById('bulk-error-count');
    const warnCountEl = document.getElementById('bulk-warn-count');
    const progressPercent = document.getElementById('bulk-progress-percent');
    const btn = document.getElementById('btn-bulk-scan');
    const stopBtn = document.getElementById('btn-bulk-stop');

    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/api/semgrep/bulk/${sessionId}/stats`);
            const data = await response.json();
            if (dashboard) dashboard.classList.remove('idle');

            // Update UI
            const totalPlugins = Number(data.total_plugins || 0);
            const scannedCount = Number(data.scanned_count || 0);
            if (totalEl) totalEl.textContent = String(totalPlugins);
            if (scannedEl) scannedEl.textContent = String(scannedCount);
            if (progressBar) progressBar.style.width = `${data.progress}%`;
            if (progressPercent) progressPercent.textContent = `${data.progress}%`;
            if (issuesEl) issuesEl.textContent = data.total_findings;

            if (data.breakdown) {
                if (errorCountEl) errorCountEl.textContent = data.breakdown.ERROR || 0;
                if (warnCountEl) warnCountEl.textContent = data.breakdown.WARNING || 0;
            }

            // Check if scan was stopped or completed
            if (!data.is_running && data.progress < 100) {
                // Scan was paused
                clearInterval(interval);
                if (statusEl) {
                    statusEl.textContent = 'Paused';
                    statusEl.className = 'bulk-status-chip paused';
                }
                const statusDot = document.getElementById('bulk-status-dot');
                if (statusDot) {
                    statusDot.classList.add('paused');
                    statusDot.style.background = '#ffbd2e';
                }
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Resume Scan';
                }
                if (stopBtn) stopBtn.style.display = 'none';
            } else if (data.progress >= 100) {
                // Scan completed
                clearInterval(interval);
                if (statusEl) {
                    statusEl.textContent = 'Completed';
                    statusEl.className = 'bulk-status-chip completed';
                }
                const statusDot = document.getElementById('bulk-status-dot');
                if (statusDot) {
                    statusDot.classList.add('completed');
                    statusDot.style.background = 'var(--accent-primary)';
                }
                if (progressBar) progressBar.style.backgroundColor = 'var(--accent-primary)';
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Scan Complete';
                }
                if (stopBtn) stopBtn.style.display = 'none';
                // Refresh results to show updated badges
                viewScan(sessionId);
            } else {
                // Still running
                if (statusEl) {
                    statusEl.textContent = `Scanning ${data.progress}%`;
                    statusEl.className = 'bulk-status-chip';
                }
                const statusDot = document.getElementById('bulk-status-dot');
                if (statusDot) {
                    statusDot.classList.remove('paused', 'completed');
                    statusDot.style.background = 'var(--accent-blue)';
                }
            }
        } catch(e) {
            console.error('Polling error', e);
        }
    }, 1000);
}

function setDeepScanButtonState(state) {
    const btn = document.getElementById('btn-deep-scan');
    if (!btn) return;

    const setLabel = (label) => {
        btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg><span>${label}</span>`;
    };

    if (state === 'scanning') {
        btn.disabled = true;
        setLabel('SCANNING...');
        return;
    }

    if (state === 'rescan') {
        btn.disabled = false;
        setLabel('RE-SCAN');
        btn.style.borderColor = 'var(--accent-primary)';
        btn.style.color = 'var(--accent-primary)';
        btn.style.opacity = '1';
        btn.title = 'Run Semgrep scan again';
        return;
    }

    btn.disabled = false;
    setLabel('RE-SCAN');
    btn.style.borderColor = 'var(--accent-blue)';
    btn.style.color = 'var(--accent-blue)';
    btn.style.opacity = '1';
    btn.title = '';
}

window.runPluginSemgrep = async function(slug, downloadUrl) {
    // Check if any rulesets are enabled
    try {
        const rulesResponse = await fetch('/api/semgrep/rules');
        const rulesData = await rulesResponse.json();
        const activeRulesets = (rulesData.rulesets || []).filter(r => r.enabled).length;
        const activeCustomRules = (rulesData.custom_rules || []).filter(r => r.enabled).length;

        if (activeRulesets === 0 && activeCustomRules === 0) {
            showToast('Semgrep is disabled. Please enable at least one ruleset in Semgrep Settings.', 'warn');
            // Redirect to semgrep settings
            switchTab('semgrep');
            return;
        }
    } catch (e) {
        showToast('Failed to check Semgrep configuration.', 'error');
        return;
    }

    const confirmed = await showConfirm(`Run deep Semgrep analysis on ${slug}? This may take a few minutes.`);
    if(!confirmed) return;

    setDeepScanButtonState('scanning');

    try {
        const response = await fetch('/api/semgrep/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ slug: slug, download_url: downloadUrl })
        });

        const data = await response.json();
        if(data.success) {
            showToast('Semgrep scan started in background. Check back in a few minutes.', 'success');
            // Start polling for results
            pollSemgrepResults(slug);
        } else {
            showToast('Failed to start scan', 'error');
            setDeepScanButtonState('rescan');
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
        setDeepScanButtonState('rescan');
    }
}

async function pollSemgrepResults(slug) {
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/api/semgrep/scan/${slug}`);
            const data = await response.json();

            if (data.status === 'completed') {
                clearInterval(interval);
                loadSemgrepResultsIntoModal(data);
            } else if (data.status === 'failed') {
                clearInterval(interval);
                showToast('Semgrep scan failed: ' + (data.error_message || 'Unknown error'), 'error');
                setDeepScanButtonState('rescan');
            }
        } catch(e) {
            clearInterval(interval);
        }
    }, 3000);
}

function loadSemgrepResultsIntoModal(scanData) {
    const container = document.getElementById('semgrep-results-container');
    if (!container) return;

    if (!scanData || !scanData.findings || scanData.findings.length === 0) {
        container.innerHTML = '<div class="plugin-semgrep-empty">No issues found by Semgrep. Code looks clean.</div>';
        setDeepScanButtonState('rescan');
        return;
    }

    const breakdown = (scanData.summary && scanData.summary.breakdown) ? scanData.summary.breakdown : {};

    let html = `<div class="plugin-semgrep-summary">
        Found <strong>${scanData.findings.length}</strong> issues
        (ERROR: <span class="sev-error">${breakdown.ERROR || 0}</span>,
        WARNING: <span class="sev-warning">${breakdown.WARNING || 0}</span>)
    </div>`;

    html += scanData.findings.map((f) => {
        const sev = String(f.severity || 'INFO').toUpperCase();
        const sevClass = sev === 'ERROR' ? 'error' : (sev === 'WARNING' ? 'warning' : 'info');
        const filePath = `${escapeHtml(String(f.file_path || ''))}${f.line_number ? `:${f.line_number}` : ''}`;
        return `
            <article class="plugin-semgrep-item ${sevClass}">
                <header class="plugin-semgrep-item-head">
                    <span class="plugin-semgrep-rule">${escapeHtml(sev)}: ${escapeHtml(String(f.rule_id || 'unknown-rule'))}</span>
                    <span class="plugin-semgrep-file">${filePath}</span>
                </header>
                <p class="plugin-semgrep-message">${escapeHtml(String(f.message || 'No description provided.'))}</p>
                ${f.code_snippet ? `<pre class="plugin-semgrep-code"><code>${escapeHtml(String(f.code_snippet || ''))}</code></pre>` : ''}
            </article>
        `;
    }).join('');

    container.innerHTML = html;

    setDeepScanButtonState('rescan');
}

window.openPluginModal = function(index, options = {}) {
    const { syncUrl = true } = options;
    const plugin = window.currentScanResults[index];
    if (!plugin) return;

    const urlState = getUrlState();
    if (urlState.view && urlState.view !== 'plugin-detail') {
        if (urlState.view === 'details' && urlState.scanId) {
            modalReturnHash = `details/${urlState.scanId}`;
        } else {
            modalReturnHash = urlState.view;
        }
    } else if (!modalReturnHash || String(modalReturnHash).startsWith('plugin/')) {
        modalReturnHash = currentScanId ? `details/${currentScanId}` : 'history';
    }

    if (syncUrl) {
        setUrlState(
            {
                view: 'plugin-detail',
                scanId: currentScanId || urlState.scanId || null,
                plugin: plugin.slug,
            },
            { replace: false }
        );
    }

    switchTab('plugin-detail', { syncUrl: false });

    const title = document.getElementById('plugin-page-title');
    const desc = document.getElementById('plugin-page-desc');
    const content = document.getElementById('plugin-page-content');

    if (title) title.textContent = `${String(plugin.slug || plugin.name || 'PLUGIN').toUpperCase()} DETAILS`;
    if (desc) desc.textContent = `Inspect metadata and Semgrep findings for ${plugin.slug || plugin.name || 'the selected plugin'}.`;
    if (!content) return;

    const downloadUrl = plugin.download_link || `https://downloads.wordpress.org/plugin/${plugin.slug}.${plugin.version}.zip`;

    let tagsHtml = '';
    if (plugin.is_user_facing) tagsHtml += '<span class="tag warn">USER FACING</span>';
    if (plugin.is_risky_category) tagsHtml += '<span class="tag risk">RISKY CATEGORY</span>';
    if (plugin.author_trusted) tagsHtml += '<span class="tag safe">TRUSTED AUTHOR</span>';
    if (plugin.is_duplicate) tagsHtml += '<span class="tag" style="background: #333;">PREVIOUSLY FOUND</span>';

    const isFav = isFavoriteSlug(plugin.slug);
    const pluginScore = parseInt(plugin.score || 0, 10) || 0;
    const pluginScoreColor = getRiskColorForScore(pluginScore);

    content.innerHTML = `
        <section class="plugin-hero">
            <div class="plugin-metrics-grid">
                <article class="plugin-metric-card">
                    <span class="plugin-metric-label">Risk Score</span>
                    <span class="plugin-metric-value" style="color:${pluginScoreColor}">${pluginScore}/100</span>
                    <span class="plugin-metric-sub">Current plugin risk level</span>
                </article>
                <article class="plugin-metric-card">
                    <span class="plugin-metric-label">Installs</span>
                    <span class="plugin-metric-value">${escapeHtml(String(plugin.installations || 0))}+</span>
                    <span class="plugin-metric-sub">Active install footprint</span>
                </article>
                <article class="plugin-metric-card">
                    <span class="plugin-metric-label">Updated</span>
                    <span class="plugin-metric-value">${escapeHtml(String(plugin.days_since_update || 0))}d</span>
                    <span class="plugin-metric-sub">Days since last update</span>
                </article>
                <article class="plugin-metric-card">
                    <span class="plugin-metric-label">Semgrep</span>
                    <span class="plugin-metric-value">${escapeHtml(String((plugin.semgrep && plugin.semgrep.findings_count) || plugin.latest_semgrep_findings || 0))}</span>
                    <span class="plugin-metric-sub">Known findings count</span>
                </article>
            </div>
        </section>

        <section class="plugin-toolbar">
            <div class="plugin-toolbar-tags">${tagsHtml || '<span class="tag">NO TAGS</span>'}</div>
            <div class="plugin-toolbar-actions">
                <button id="plugin-fav-btn" onclick="toggleFavorite('${plugin.slug}')" class="action-btn details-fav-btn plugin-fav-inline${isFav ? ' active' : ''}" title="${isFav ? 'In Favorites' : 'Add to Favorites'}" aria-label="${isFav ? 'Remove from' : 'Add to'} favorites">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                </button>
                <a href="${escapeHtml(downloadUrl)}" target="_blank" rel="noreferrer noopener" class="action-btn plugin-action-download">
                    <span>DOWNLOAD ZIP</span>
                </a>
                <button id="btn-deep-scan" onclick="runPluginSemgrep('${escapeHtml(plugin.slug)}', '${escapeHtml(downloadUrl)}')" class="action-btn plugin-action-secondary">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
                    <span>RE-SCAN</span>
                </button>
            </div>
        </section>

        <section class="plugin-section">
            <div class="section-title">Semgrep Analysis</div>
            <div id="semgrep-results-container">
                <div class="plugin-semgrep-empty">
                    No Semgrep analysis yet. Click <strong>RE-SCAN</strong> to run deep static analysis for this plugin.
                </div>
            </div>
        </section>
    `;

    setDeepScanButtonState('default');

    // Check if scan already exists
    fetch(`/api/semgrep/scan/${plugin.slug}`)
        .then(res => res.json())
        .then(data => {
            if(data.status === 'completed') {
                loadSemgrepResultsIntoModal(data);
            } else if (data.status === 'running' || data.status === 'pending') {
                document.getElementById('semgrep-results-container').innerHTML = '<div class="plugin-semgrep-empty">Semgrep scan in progress...</div>';
                setDeepScanButtonState('scanning');
                pollSemgrepResults(plugin.slug);
            }
        })
        .catch(() => {});

    // Check if Semgrep is enabled and update Deep Scan button state
    fetch('/api/semgrep/rules')
        .then(res => res.json())
        .then(rulesData => {
            const activeRulesets = (rulesData.rulesets || []).filter(r => r.enabled).length;
            const activeCustomRules = (rulesData.custom_rules || []).filter(r => r.enabled).length;
            const btn = document.getElementById('btn-deep-scan');

            if (btn && activeRulesets === 0 && activeCustomRules === 0) {
                btn.disabled = true;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 5px;"><path d="M12 15v.01M12 12v.01M12 9v.01M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> DISABLED';
                btn.title = 'Enable rulesets in Semgrep Settings to use this feature';
                btn.style.opacity = '0.6';
            }
        })
        .catch(() => {});
}

window.closeModal = function() {
    const fallbackHash = currentScanId ? `details/${currentScanId}` : 'history';
    const targetHash =
        modalReturnHash && !String(modalReturnHash).startsWith('plugin/')
            ? modalReturnHash
            : fallbackHash;

    if (String(targetHash).startsWith('details/')) {
        const scanId = parseInt(String(targetHash).split('/')[1], 10);
        const resolvedScan = Number.isFinite(scanId) ? scanId : (currentScanId || null);
        if (resolvedScan) {
            setUrlState({ view: 'details', scanId: resolvedScan, plugin: '' }, { replace: false });
            viewScan(resolvedScan, { syncUrl: false });
            return;
        }
    }

    const tabId = VIEW_TO_TAB[String(targetHash)] || 'history';
    setUrlState({ view: TAB_TO_VIEW[tabId] || 'history', scanId: null, plugin: '' }, { replace: false });
    switchTab(tabId, { syncUrl: false });
}

// ==========================================
// SEMGREP RULES MANAGEMENT
// ==========================================

window.loadSemgrepRules = async function() {
    const rulesListEl = document.getElementById('semgrep-rules-list');

    if (!rulesListEl) return;

    try {
        const response = await fetch('/api/semgrep/rules');
        const data = await response.json();

        // 1. RENDER RULESETS
        let html = '';

        html += `<h3 style="font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); margin-bottom: 15px; border-bottom: 1px solid #222; padding-bottom: 8px; margin-top: 10px;">📦 SECURITY RULESETS</h3>`;
        html += `<div style="display:flex; gap:10px; align-items:center; margin: -4px 0 14px 0;">
                <input type="text" id="new-ruleset-id" placeholder="p/cwe-top-25 or p/owasp-top-ten" style="flex:1; min-width: 260px; padding: 9px 10px; background: #0a0a0a; border: 1px solid #333; border-radius: 4px; color: #fff; font-family: var(--font-mono); font-size:11px;">
                <button onclick="addSemgrepRuleset()" class="action-btn" style="width:auto; padding:8px 12px; background: rgba(0, 255, 157, 0.1); border: 1px solid rgba(0, 255, 157, 0.35); color: var(--accent-primary); font-size:11px;">
                    ADD RULESET
                </button>
            </div>`;

        const formatRulesetLabel = (rs) => {
            const id = String(rs?.id || '').trim();
            if (!id) return 'p/custom';
            if (id.startsWith('p/') || id.startsWith('r/')) return id;
            const known = {
                'owasp-top-ten': 'p/owasp-top-ten',
                'php-security': 'p/php',
                'security-audit': 'p/security-audit'
            };
            return known[id] || `p/${id}`;
        };

        const renderRulesetCard = (rs) => `
                <div style="background: ${!rs.enabled ? 'rgba(30, 30, 30, 0.45)' : '#141416'}; border: 1px solid ${!rs.enabled ? '#333' : 'var(--border-color)'}; border-radius: 4px; padding: 12px 14px; margin-bottom: 8px; opacity: ${!rs.enabled ? '0.7' : '1'};">
                    <div style="display:flex; justify-content:space-between; align-items:center; gap: 10px;">
                        <div style="display:inline-flex; align-items:center; gap:8px; min-width: 0;">
                            <span title="${escapeHtml(rs.id)}" style="font-family: var(--font-mono); font-size: 13px; color: ${!rs.enabled ? '#9a9a9a' : '#fff'}; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(formatRulesetLabel(rs))}</span>
                            <a href="${escapeHtml(rs.url)}" target="_blank" style="font-size: 10px; color: var(--accent-blue); text-decoration: none; white-space: nowrap;">View ↗</a>
                        </div>
                        <div style="display:inline-flex; align-items:center; gap:6px;">
                            <button onclick="toggleRuleset('${escapeHtml(rs.id)}')" class="action-btn" title="${rs.enabled ? 'Set Disabled' : 'Set Active'}" style="width: 32px; height: 18px; border-radius: 20px; padding: 2px; border: 1px solid ${rs.enabled ? 'rgba(0,255,157,0.35)' : 'rgba(120,120,120,0.35)'}; background: ${rs.enabled ? 'rgba(0,255,157,0.85)' : 'rgba(120,120,120,0.45)'}; display:flex; align-items:center; ${rs.enabled ? 'justify-content:flex-end;' : 'justify-content:flex-start;'}">
                                <span style="display:block; width: 14px; height: 14px; border-radius: 999px; background: #f1f1f1; box-shadow: 0 1px 2px rgba(0,0,0,0.35);"></span>
                            </button>
                            ${rs.deletable ? `
                            <button onclick="deleteRuleset('${escapeHtml(rs.id)}', true)" class="action-btn" style="width: 28px; height: 28px; padding: 0; background: rgba(255, 0, 85, 0.1); color: #ff0055; border: 1px solid rgba(255, 0, 85, 0.25);" title="Delete Ruleset">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                            </button>` : ''}
                        </div>
                    </div>
                </div>
            `;

        if (data.rulesets && data.rulesets.length > 0) {
            const coreRulesetIds = new Set(['owasp-top-ten', 'php-security', 'security-audit']);
            const coreRulesets = data.rulesets.filter(rs => coreRulesetIds.has(String(rs.id || '').trim()));
            const extraRulesets = data.rulesets.filter(rs => !coreRulesetIds.has(String(rs.id || '').trim()));

            html += coreRulesets.map(renderRulesetCard).join('');

            if (extraRulesets.length > 0) {
                html += `<div style="margin-top: 10px; margin-bottom: 10px;">
                    <div style="color:#888; font-size:11px; font-family:var(--font-mono); margin-bottom:8px;">Advanced / Extra Rulesets (${extraRulesets.length})</div>
                    ${extraRulesets.map(renderRulesetCard).join('')}
                </div>`;
            }
        } else {
            html += '<div style="text-align: center; color: #666; padding: 12px; border: 1px dashed #333; border-radius: 4px; margin-bottom: 10px;">No rulesets found. Add one above (example: p/cwe-top-25).</div>';
        }

        const customRules = data.custom_rules || [];
        const enabledCustomRules = customRules.filter(rule => rule.enabled).length;
        const allCustomRulesEnabled = customRules.length > 0 && enabledCustomRules === customRules.length;
        const bulkToggleTargetEnabled = !allCustomRulesEnabled;
        const bulkToggleLabel = allCustomRulesEnabled ? 'ALL OFF' : 'ALL ON';
        const bulkToggleStyles = allCustomRulesEnabled
            ? 'background: rgba(255,0,85,0.1); color: #ff0055; border: 1px solid rgba(255,0,85,0.35);'
            : 'background: rgba(0,255,157,0.1); color: var(--accent-primary); border: 1px solid rgba(0,255,157,0.35);';
        const bulkToggleDisabled = customRules.length === 0;
        const bulkToggleDisabledAttr = bulkToggleDisabled
            ? 'disabled title="No custom rules to toggle"'
            : '';
        const bulkToggleResolvedStyles = bulkToggleDisabled
            ? 'opacity:0.6; cursor:not-allowed; border:1px solid #444; color:#777; background:rgba(90,90,90,0.1);'
            : bulkToggleStyles;

        // 2. RENDER CUSTOM RULES
        html += `<div style="display:flex; justify-content:space-between; align-items:center; gap:10px; margin-top:30px; margin-bottom:15px; border-bottom:1px solid #222; padding-bottom:8px;">
                    <h3 style="font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); margin:0;">✏️ CUSTOM RULES</h3>
                    <button
                        onclick="toggleAllCustomRules(${bulkToggleTargetEnabled})"
                        class="action-btn"
                        style="width:auto; padding:6px 10px; font-size:10px; ${bulkToggleResolvedStyles}"
                        ${bulkToggleDisabledAttr}
                    >${bulkToggleLabel}</button>
                </div>`;

        if (customRules.length > 0) {
            html += customRules.map(rule => `
                <div style="background: ${!rule.enabled ? 'rgba(30, 30, 30, 0.5)' : '#141416'}; border: 1px solid ${!rule.enabled ? '#333' : 'var(--accent-primary)'}; border-radius: 4px; padding: 15px; margin-bottom: 10px; opacity: ${!rule.enabled ? '0.6' : '1'}; transition: all 0.2s;">
                    <div style="display: flex; justify-content: space-between; align-items: start;">
                        <div style="flex: 1;">
                            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                                <span style="font-family: var(--font-mono); font-size: 13px; color: ${!rule.enabled ? '#888' : '#fff'}; font-weight: 600; text-decoration: ${!rule.enabled ? 'line-through' : 'none'};">${escapeHtml(rule.id)}</span>
                                <span class="tag ${rule.severity === 'ERROR' ? 'risk' : (rule.severity === 'WARNING' ? 'warn' : '')}" style="font-size: 9px;">${escapeHtml(rule.severity)}</span>
                            </div>
                            <div style="font-size: 11px; color: #888; margin-bottom: 8px;">${escapeHtml(rule.message)}</div>
                            <div style="font-family: var(--font-mono); font-size: 10px; color: #666; background: #0a0a0a; padding: 8px; border-radius: 3px; overflow-x: auto;">
                                ${escapeHtml(rule.pattern || 'Multiple patterns')}
                            </div>
                        </div>
                        <div style="display: flex; gap: 6px; margin-left: 15px; align-items: center;">
                            <button onclick="toggleSemgrepRule('${escapeHtml(rule.id)}')" class="action-btn" title="${rule.enabled ? 'Set Disabled' : 'Set Active'}" style="width: 32px; height: 18px; border-radius: 20px; padding: 2px; border: 1px solid ${rule.enabled ? 'rgba(0,255,157,0.35)' : 'rgba(120,120,120,0.35)'}; background: ${rule.enabled ? 'rgba(0,255,157,0.85)' : 'rgba(120,120,120,0.45)'}; display:flex; align-items:center; ${rule.enabled ? 'justify-content:flex-end;' : 'justify-content:flex-start;'}">
                                <span style="display:block; width: 14px; height: 14px; border-radius: 999px; background: #f1f1f1; box-shadow: 0 1px 2px rgba(0,0,0,0.35);"></span>
                            </button>
                            <button onclick="deleteSemgrepRule('${escapeHtml(rule.id)}')" class="action-btn" style="width: 32px; height: 32px; padding: 0; background: rgba(255, 0, 85, 0.1); color: #ff0055; border: 1px solid rgba(255, 0, 85, 0.2);" title="Delete Rule">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        } else {
            html += '<div style="text-align: center; color: #666; padding: 20px; border: 1px dashed #333; border-radius: 4px;">No custom rules defined. Add one above!</div>';
        }

        rulesListEl.innerHTML = html;

    } catch (error) {
        console.error('Error loading Semgrep rules:', error);
        rulesListEl.innerHTML = `<div style="text-align: center; color: var(--accent-secondary); padding: 30px;">Error loading rules: ${escapeHtml(error.message)}</div>`;
    }
}

window.toggleRuleset = async function(rulesetId) {
    try {
        const response = await fetch(`/api/semgrep/rulesets/${encodeURIComponent(rulesetId)}/toggle`, {
            method: 'POST'
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            showToast('Failed to toggle ruleset: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }

        if (data.success) {
            loadSemgrepRules(); // Reload UI
        } else {
            showToast('Failed to toggle ruleset: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error toggling ruleset:', error);
        showToast('Error toggling ruleset: ' + (error.message || 'unknown error'), 'error');
    }
}

window.deleteRuleset = async function(rulesetId, deletable = true) {
    if (!deletable) {
        showToast('Built-in rulesets cannot be deleted. You can disable them with the toggle.', 'warn');
        return;
    }
    const confirmed = await showConfirm(`Delete ruleset "${rulesetId}"?`);
    if (!confirmed) return;
    try {
        const response = await fetch(`/api/semgrep/rulesets/${encodeURIComponent(rulesetId)}`, {
            method: 'DELETE'
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showToast('Failed to delete ruleset: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }
        if (data.success) {
            showToast(`Ruleset deleted: ${rulesetId}`, 'success');
            loadSemgrepRules();
        } else {
            showToast('Failed to delete ruleset: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error deleting ruleset:', error);
        showToast('Error deleting ruleset: ' + error.message, 'error');
    }
}

window.addSemgrepRuleset = async function() {
    const input = document.getElementById('new-ruleset-id');
    const ruleset = (input?.value || '').trim();

    if (!ruleset) {
        showToast('Please enter a ruleset (example: p/cwe-top-25).', 'warn');
        return;
    }

    if (!/^[a-zA-Z0-9_./:-]+$/.test(ruleset)) {
        showToast('Invalid ruleset format. Use values like p/cwe-top-25.', 'warn');
        return;
    }

    try {
        const response = await fetch('/api/semgrep/rulesets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ruleset })
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            showToast('Failed to add ruleset: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }

        if (data.success) {
            if (input) input.value = '';
            showToast(`Ruleset added: ${ruleset}`, 'success');
            loadSemgrepRules();
        } else {
            showToast('Failed to add ruleset: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error adding ruleset: ' + error.message, 'error');
    }
}

window.toggleSemgrepRule = async function(ruleId) {
    try {
        const response = await fetch(`/api/semgrep/rules/${encodeURIComponent(ruleId)}/toggle`, {
            method: 'POST'
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            showToast('Failed to toggle rule: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }

        if (data.success) {
            loadSemgrepRules(); // Reload UI
        } else {
            showToast('Failed to toggle rule: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error toggling rule:', error);
        showToast('Error toggling rule: ' + (error.message || 'unknown error'), 'error');
    }
}

window.toggleAllCustomRules = async function(enabled) {
    try {
        let response = await fetch('/api/semgrep/rules/actions/toggle-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });

        if (response.status === 404 || response.status === 405) {
            response = await fetch('/api/semgrep/rules/toggle-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });
        }

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            showToast('Failed to update custom rules: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }

        if (data.success) {
            showToast(
                `${enabled ? 'Enabled' : 'Disabled'} ${data.changed}/${data.total} custom rule(s)`,
                'success'
            );
            loadSemgrepRules();
        } else {
            showToast('Failed to update custom rules', 'error');
        }
    } catch (error) {
        showToast('Error updating custom rules: ' + (error.message || 'unknown error'), 'error');
    }
}

window.addSemgrepRule = async function() {
    const ruleId = document.getElementById('new-rule-id').value.trim();
    const pattern = document.getElementById('new-rule-pattern').value.trim();
    const message = document.getElementById('new-rule-message').value.trim();
    const severity = document.getElementById('new-rule-severity').value;

    if (!ruleId || !pattern || !message) {
        showToast('Please fill in all fields: Rule ID, Pattern, and Message.', 'warn');
        return;
    }

    // Validate rule ID format
    if (!/^[a-zA-Z0-9_-]+$/.test(ruleId)) {
        showToast('Rule ID can only contain letters, numbers, hyphens, and underscores.', 'warn');
        return;
    }

    try {
        const response = await fetch('/api/semgrep/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: ruleId,
                pattern: pattern,
                message: message,
                severity: severity,
                languages: ['php']
            })
        });

        const data = await response.json();

        if (data.success) {
            // Clear form
            document.getElementById('new-rule-id').value = '';
            document.getElementById('new-rule-pattern').value = '';
            document.getElementById('new-rule-message').value = '';

            // Reload rules
            loadSemgrepRules();
        } else {
            showToast('Failed to add rule: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error adding rule: ' + error.message, 'error');
    }
}

window.deleteSemgrepRule = async function(ruleId) {
    const confirmed = await showConfirm(`Are you sure you want to delete the rule "${ruleId}"?`);
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(`/api/semgrep/rules/${encodeURIComponent(ruleId)}`, {
            method: 'DELETE'
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            showToast('Failed to delete rule: ' + (data.detail || data.error || `HTTP ${response.status}`), 'error');
            return;
        }

        if (data.success) {
            loadSemgrepRules();
        } else {
            showToast('Failed to delete rule: ' + (data.detail || data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error deleting rule: ' + error.message, 'error');
    }
}
