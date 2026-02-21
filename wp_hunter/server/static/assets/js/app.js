// Global state
let currentScanId = null;
let socket = null;
let detailsPollingInterval = null; // Polling interval for scan details
window.currentScanResults = []; // Store results for modal access
window.favoriteSlugs = new Set(); // Fast lookup for favorite state
const SYSTEM_STATUS_POLL_INTERVAL = 15000;
let systemStatusTimer = null;
window.systemStatus = null;
let lastSystemErrorMessage = "";
let lastSystemUpdateMessage = "";
let announcedUpdateVersion = "";

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

function refreshAfterScanEvent(sessionId) {
    loadHistory();
    if (!sessionId) return;

    // If user is already on this scan details view, force-refresh it after DB flush.
    if (isDetailsViewActive() && currentScanId === sessionId) {
        setTimeout(() => { if (currentScanId === sessionId) viewScan(sessionId); }, 250);
        setTimeout(() => { if (currentScanId === sessionId) viewScan(sessionId); }, 1200);
    }
}

async function syncFinalScanResults(sessionId, expectedCount = 0) {
    if (!sessionId) return;
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

function formatBytes(bytes) {
    const size = Number(bytes);
    if (Number.isNaN(size)) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = size;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index += 1;
    }
    return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
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
    const updateBadge = document.getElementById("server-update-badge");
    if (!updateBadge || !data) return;

    const hasLatestVersion = !!(data.latest_version && String(data.latest_version).trim());

    if (data.in_progress) {
        updateBadge.hidden = false;
        updateBadge.disabled = true;
        updateBadge.classList.add("updating");
        updateBadge.textContent = "UPDATING…";
        return;
    }

    updateBadge.classList.remove("updating");
    updateBadge.disabled = false;

    if (data.update_available && hasLatestVersion) {
        const latestVersion = formatVersionLabel(data.latest_version) || "NEW";
        updateBadge.hidden = false;
        updateBadge.textContent = `UPDATE AVAILABLE (${latestVersion})`;

        if (data.latest_version && announcedUpdateVersion !== data.latest_version) {
            announcedUpdateVersion = data.latest_version;
            showToast(
                `New release detected (${latestVersion}). Click UPDATE AVAILABLE to install it.`,
                "warn"
            );
        }
    } else {
        updateBadge.hidden = true;
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
    const updateTime = document.getElementById("update-checked-time");
    const assetPreview = document.getElementById("update-asset-preview");
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
        if (updateTime) {
            updateTime.textContent = data.checked_at
                ? `Checked ${new Date(data.checked_at).toLocaleString()}`
                : "";
        }
        if (assetPreview) {
            const assetName = data.asset_name || data.release_name || "";
            const assetSize = formatBytes(data.asset_size);
            assetPreview.textContent = assetName
                ? `Asset: ${assetName}${assetSize ? ` (${assetSize})` : ""}`
                : "";
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
    loadSystemStatus(true);
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


document.addEventListener('DOMContentLoaded', () => {
    // Initial setup
    // Form listeners removed - updateCommand was empty
    const form = document.getElementById('configForm');
    
    // Load history
    loadHistory();
    
    // Close modal on outside click
    const modalOverlay = document.getElementById('plugin-modal');
    if (modalOverlay) {
        modalOverlay.addEventListener('click', (e) => {
            if (e.target.id === 'plugin-modal') closeModal();
        });
    }

    // Restore view from URL hash on page load
    restoreViewFromHash();
    
    // Listen for hash changes (browser back/forward)
    window.addEventListener('hashchange', restoreViewFromHash);
    
    const updateButton = document.getElementById('update-action-btn');
    if (updateButton) {
        updateButton.addEventListener('click', initiateSystemUpdate);
    }
    const serverUpdateButton = document.getElementById('server-update-badge');
    if (serverUpdateButton) {
        serverUpdateButton.addEventListener('click', initiateSystemUpdate);
    }
    startSystemStatusPolling();
});

// Restore view from URL hash
function restoreViewFromHash() {
    const hash = window.location.hash.replace('#', '');
    if (!hash) return;
    
    // Check for details view: details/123
    if (hash.startsWith('details/')) {
        const scanId = hash.split('/')[1];
        if (scanId && !isNaN(parseInt(scanId))) {
            viewScan(parseInt(scanId));
            return;
        }
    }
    
    // Check for plugin modal: plugin/slug or plugin/slug/scanId
    if (hash.startsWith('plugin/')) {
        const parts = hash.split('/');
        const slug = parts[1];
        const scanId = parts[2] ? parseInt(parts[2]) : null;
        if (slug) {
            // If scanId is provided, set it first
            if (scanId && !isNaN(scanId)) {
                currentScanId = scanId;
            }
            openPluginModalBySlug(slug);
            return;
        }
    }
    
    // Regular tabs
    const validTabs = ['scan', 'history', 'favorites', 'semgrep'];
    if (validTabs.includes(hash)) {
        switchTab(hash);
    }
}

// Open plugin modal by slug (used for hash restoration)
async function openPluginModalBySlug(slug) {
    // First try to find in current scan results
    if (window.currentScanResults && window.currentScanResults.length > 0) {
        const index = window.currentScanResults.findIndex(p => p.slug === slug);
        if (index !== -1) {
            openPluginModal(index);
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
                openPluginModal(0);
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
                    openPluginModal(index);
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
                            // Set currentScanId so closing modal returns to this scan
                            currentScanId = session.id;
                            openPluginModal(index);
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
    window.location.hash = 'history';
}

window.switchTab = function(tabId) {
    // Hide all views
    document.getElementById('scan-view').style.display = 'none';
    document.getElementById('history-view').style.display = 'none';
    document.getElementById('favorites-view').style.display = 'none';
    const detailsView = document.getElementById('scan-details-view');
    if (detailsView) detailsView.style.display = 'none';
    const semgrepView = document.getElementById('semgrep-view');
    if (semgrepView) semgrepView.style.display = 'none';

    // Reset nav active state
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    // Show selected view and set active
    if (tabId === 'scan') {
        document.getElementById('scan-view').style.display = 'block';
        document.getElementById('nav-scan').classList.add('active');
    } else if (tabId === 'history') {
        document.getElementById('history-view').style.display = 'block';
        document.getElementById('nav-history').classList.add('active');
        loadHistory();
    } else if (tabId === 'favorites') {
        document.getElementById('favorites-view').style.display = 'block';
        document.getElementById('nav-favorites').classList.add('active');
        loadFavorites();
    } else if (tabId === 'semgrep') {
        if (semgrepView) semgrepView.style.display = 'block';
        document.getElementById('nav-semgrep').classList.add('active');
        loadSemgrepRules();
    } else if (tabId === 'details') {
        if (detailsView) detailsView.style.display = 'block';
    }

    // Stop details polling when leaving details view
    if (tabId !== 'details' && detailsPollingInterval) {
        clearInterval(detailsPollingInterval);
        detailsPollingInterval = null;
        currentScanId = null;
    }

    // Update URL hash for persistence on refresh (except for details view)
    if (tabId !== 'details') {
        window.location.hash = tabId;
    }
}

function updateCommand() {
    // Removed - was empty function
}

window.runScan = async function() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    
    const requestData = {
        pages: parseInt(formData.get('pages')) || 5,
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
    
    clearTerminal();
    logTerminal('Initializing scan...', 'info');
    
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
            connectWebSocket(currentScanId);
            
            document.getElementById('scan-status').textContent = 'RUNNING';
            document.getElementById('scan-status').className = 'info-value running';
            
            // Navigate to scan details view
            viewScan(currentScanId);
        } else {
            logTerminal('Failed to start scan', 'error');
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
        }
    } catch (error) {
        logTerminal(`Error: ${error.message}`, 'error');
        runBtn.disabled = false;
        runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
    }
}

function connectWebSocket(sessionId) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/scans/${sessionId}`;
    if (socket) socket.close();
    
    socket = new WebSocket(wsUrl);
    socket.onopen = () => logTerminal('WebSocket connected', 'info');
    socket.onmessage = (event) => handleMessage(JSON.parse(event.data));
    socket.onclose = () => logTerminal('WebSocket connection closed', 'info');
    socket.onerror = () => logTerminal('WebSocket error', 'error');
}

function handleMessage(msg) {
    const runBtn = document.getElementById('runBtn');
    
    switch(msg.type) {
        case 'start':
            logTerminal('Scan execution started...', 'info');
            break;
        case 'result':
            logTerminal(`${msg.data.score >= 40 ? '[HIGH RISK]' : '[INFO]'} Found: ${msg.data.slug} (Score: ${msg.data.score})`, msg.data.score >= 40 ? 'high-risk' : 'low-risk');
            document.getElementById('scan-found').textContent = msg.found_count;
            break;
        case 'deduplicated':
            logTerminal(`Scan identical to Session #${msg.original_session_id}. Merging...`, 'warn');
            logTerminal(`Session merged. History updated.`, 'success');
            currentScanId = msg.original_session_id;
            document.getElementById('scan-status').textContent = 'MERGED';
            document.getElementById('scan-status').className = 'info-value completed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            refreshAfterScanEvent(currentScanId);
            break;
        case 'complete':
            logTerminal(`Scan completed. Found: ${msg.total_found}, High Risk: ${msg.high_risk_count}`, 'success');
            document.getElementById('scan-status').textContent = 'COMPLETED';
            document.getElementById('scan-status').className = 'info-value completed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            refreshAfterScanEvent(currentScanId);
            if (currentScanId) {
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
            document.getElementById('scan-status').className = 'info-value failed';
            runBtn.disabled = false;
            runBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
            refreshAfterScanEvent(currentScanId);
            // Stop polling on error
            if (detailsPollingInterval) {
                clearInterval(detailsPollingInterval);
                detailsPollingInterval = null;
            }
            break;
    }
}

function logTerminal(text, type = 'info') {
    const terminal = document.getElementById('terminal-content');
    const div = document.createElement('div');
    div.className = 'line';

    let color = '#ccc';
    if (type === 'error' || type === 'high-risk') color = '#ff5f56';
    if (type === 'success') color = '#27c93f';
    if (type === 'info') color = '#00f3ff';
    if (type === 'warn') color = '#ffbd2e';

    // XSS Prevention: Use textContent instead of innerHTML for user data
    const promptSpan = document.createElement('span');
    promptSpan.className = 'prompt';
    promptSpan.textContent = '$';

    const textSpan = document.createElement('span');
    textSpan.style.color = color;
    textSpan.textContent = ' ' + text;

    div.appendChild(promptSpan);
    div.appendChild(textSpan);

    const existingCursor = terminal.querySelector('.cursor');
    if (existingCursor) existingCursor.remove();

    terminal.appendChild(div);
    const cursor = document.createElement('span');
    cursor.className = 'cursor';
    cursor.textContent = '_';
    div.appendChild(cursor);

    terminal.scrollTop = terminal.scrollHeight;
}

function clearTerminal() {
    const terminal = document.getElementById('terminal-content');
    terminal.innerHTML = '<div class="line"><span class="prompt">$</span> <span class="cmd-text">Ready to scan...</span><span class="cursor">_</span></div>';
}

window.loadHistory = async function() {
    const list = document.getElementById('history-list');
    if (!list) return;
    
    try {
        const response = await fetch(apiNoCacheUrl('/api/scans'));
        const data = await response.json();
        const sessions = data.sessions.sort((a, b) => new Date(b.created_at || b.start_time) - new Date(a.created_at || a.start_time));
        list.innerHTML = sessions.map(s => `
            <tr>
                <td>#${escapeHtml(String(s.id))}</td>
                <td><span class="status-badge ${escapeHtml(s.status).toLowerCase()}">${escapeHtml(s.status)}</span></td>
                <td>${escapeHtml(String(s.total_found))}</td>
                <td>${escapeHtml(String(s.high_risk_count))}</td>
                <td>${escapeHtml(new Date(s.created_at || s.start_time).toLocaleString())}</td>
                <td>
                    <div style="display: flex; gap: 8px;">
                        <button onclick="viewScan(${parseInt(s.id)})" class="action-btn" title="View Results" style="width: 32px; height: 32px; padding: 0; background: #333; color: white;">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                        </button>
                        <button onclick="deleteScan(${parseInt(s.id)})" class="action-btn" title="Delete Scan" style="width: 32px; height: 32px; padding: 0; background: rgba(255, 0, 85, 0.1); color: #ff0055; border: 1px solid rgba(255, 0, 85, 0.2);">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        list.innerHTML = '<tr><td colspan="6">Error loading history</td></tr>';
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

window.loadFavorites = async function() {
    const list = document.getElementById('favorites-list');
    list.innerHTML = '<tr><td colspan="4">Loading...</td></tr>';
    try {
        const resp = await fetch('/api/favorites');
        const data = await resp.json();
        
        window.currentScanResults = data.favorites || [];
        
        list.innerHTML = window.currentScanResults.map((r, index) => `
            <tr>
                <td style="color: #fff;">${escapeHtml(r.slug)}</td>
                <td>${escapeHtml(r.version)}</td>
                <td><span class="${r.score >= 40 ? 'risk-high' : (r.score >= 20 ? 'risk-medium' : 'risk-low')}">${r.score}</span></td>
                <td>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <button onclick="openPluginModal(${index})" class="action-btn" style="height: 28px; padding: 0 12px; background: var(--accent-primary); color: #000; font-size: 10px; font-weight: 700; border-radius: 2px;">DETAILS</button>
                        <button onclick="removeFromFavorites('${escapeHtml(r.slug)}')" class="action-btn" style="width: 28px; height: 28px; padding: 0; background: rgba(255, 0, 85, 0.1); color: #ff0055; border: 1px solid rgba(255, 0, 85, 0.2); border-radius: 2px;" title="Remove Favorite">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');
        if(window.currentScanResults.length === 0) list.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#666;">No favorites yet</td></tr>';
    } catch(e) { 
        console.error(e);
        list.innerHTML = '<tr><td colspan="4">Error loading favorites</td></tr>'; 
    }
}

window.removeFromFavorites = async function(slug) {
    const confirmed = await showConfirm('Remove from favorites?');
    if(!confirmed) return;
    await fetch(`/api/favorites/${slug}`, {method: 'DELETE'});
    window.favoriteSlugs.delete(slug);
    loadFavorites();
}

window.toggleFavorite = async function(slug) {
    const plugin = window.currentScanResults.find(p => p.slug === slug);
    if (!plugin) return;

    const isAlreadyFavorite = isFavoriteSlug(slug);

    if (!isAlreadyFavorite) {
        const response = await fetch('/api/favorites', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(plugin)
        });
        const res = await response.json();
        if (res.success) {
            window.favoriteSlugs.add(slug);
            showToast('Plugin added to favorites', 'success');
        } else {
            showToast('Failed to add favorite', 'error');
        }
    } else {
        const confirmed = await showConfirm('Remove from favorites?');
        if (!confirmed) return;
        await fetch(`/api/favorites/${slug}`, {method: 'DELETE'});
        window.favoriteSlugs.delete(slug);
        showToast('Plugin removed from favorites', 'info');
    }

    if (currentScanId) {
        viewScan(currentScanId);
    }
}

window.viewScan = async function(id) {
    switchTab('details');
    currentScanId = id; // Set current scan ID
    
    // Update URL hash for details view
    window.location.hash = `details/${id}`;
    
    const summary = document.getElementById('details-summary');
    const list = document.getElementById('details-list');
    const title = document.getElementById('details-title');
    title.textContent = `Scan #${id} Details`;
    summary.innerHTML = 'Loading details...';
    list.innerHTML = 'Loading results...';

    // Reset Dashboard UI
    const dashboard = document.getElementById('bulk-dashboard');
    if (dashboard) {
        dashboard.style.display = 'none'; // Hide by default
        // Reset counters
        const els = ['bulk-scanned', 'bulk-total', 'bulk-issues', 'bulk-error-count', 'bulk-warn-count'];
        els.forEach(id => { const el = document.getElementById(id); if(el) el.textContent = '0'; });
        const bar = document.getElementById('bulk-progress-bar');
        if(bar) { bar.style.width = '0%'; bar.style.backgroundColor = 'var(--accent-blue)'; }
        const status = document.getElementById('bulk-status');
        if(status) { status.textContent = 'INITIALIZING...'; status.style.color = 'var(--accent-blue)'; }
        const btn = document.getElementById('btn-bulk-scan');
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> SCAN ALL (SEMGREP)';
        }
    }

    // Check if Semgrep is enabled and update button state
    fetch('/api/semgrep/rules')
        .then(res => res.json())
        .then(rulesData => {
            const activeRulesets = (rulesData.rulesets || []).filter(r => r.enabled).length;
            const activeCustomRules = (rulesData.custom_rules || []).filter(r => r.enabled).length;
            const btn = document.getElementById('btn-bulk-scan');
            
            if (btn && activeRulesets === 0 && activeCustomRules === 0) {
                btn.disabled = true;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15v.01M12 12v.01M12 9v.01M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> SEMGREP DISABLED';
                btn.title = 'Enable rulesets in Semgrep Settings to use this feature';
                btn.style.opacity = '0.6';
            } else if (btn) {
                btn.disabled = false;
                btn.style.opacity = '1';
            }
        })
        .catch(() => {});

    // Check for active bulk scan
    fetch(`/api/semgrep/bulk/${id}/stats`)
        .then(res => res.json())
        .then(data => {
            const hasProgress = data.scanned_count > 0 || data.total_findings > 0;

            if (hasProgress || data.is_running) {
                // If there's progress or running, show the dashboard
                if(dashboard) dashboard.style.display = 'block';

                const btn = document.getElementById('btn-bulk-scan');
                const stopBtn = document.getElementById('btn-bulk-stop');
                const statusEl = document.getElementById('bulk-status');

                if (data.is_running) {
                    // Scan is actively running
                    if(btn) {
                        btn.disabled = true;
                        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> SCANNING...';
                    }
                    if(stopBtn) {
                        stopBtn.style.display = 'inline-flex';
                        stopBtn.disabled = false;
                    }
                    if(statusEl) {
                        statusEl.textContent = `SCANNING (${data.progress}%)`;
                        statusEl.style.color = 'var(--accent-blue)';
                    }
                    pollBulkProgress(id);
                } else if (data.progress < 100 && hasProgress) {
                    // Scan was paused (only if there was actual progress)
                    if(statusEl) {
                        statusEl.textContent = 'PAUSED';
                        statusEl.style.color = '#ffbd2e';
                    }
                    if(btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> RESUME SCAN';
                    }
                    if(stopBtn) stopBtn.style.display = 'none';
                } else if (data.progress >= 100) {
                    // Scan completed
                    if(statusEl) {
                        statusEl.textContent = 'COMPLETED';
                        statusEl.style.color = 'var(--accent-primary)';
                    }
                    if(btn) {
                        btn.disabled = false;
                        btn.textContent = 'SCAN COMPLETE';
                    }
                    if(stopBtn) stopBtn.style.display = 'none';
                }

                // Update stats display
                const totalEl = document.getElementById('bulk-total');
                const scannedEl = document.getElementById('bulk-scanned');
                const progressBar = document.getElementById('bulk-progress-bar');
                const issuesEl = document.getElementById('bulk-issues');
                if (totalEl) totalEl.textContent = data.total_plugins;
                if (scannedEl) scannedEl.textContent = data.scanned_count;
                if (progressBar) progressBar.style.width = `${data.progress}%`;
                if (issuesEl) issuesEl.textContent = data.total_findings;
            }
        })
        .catch(() => {});

    try {
        const sessionResp = await fetch(apiNoCacheUrl(`/api/scans/${id}`));
        const session = await sessionResp.json();

        const config = session.config || {};
        const configHtml = `
            <div style="margin-top: 15px; padding-top: 15px; border-top: 1px dashed #333; grid-column: 1 / -1;">
                <label style="display: block; font-size: 10px; color: var(--text-muted); margin-bottom: 8px; font-family: var(--font-mono);">CONFIGURATION</label>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; font-size: 11px; font-family: var(--font-mono); color: #888;">
                    <span style="background: #1a1a1a; padding: 4px 8px; border-radius: 2px;">SORT: <span style="color: #ccc">${escapeHtml((config.sort || 'UPDATED').toUpperCase())}</span></span>
                    <span style="background: #1a1a1a; padding: 4px 8px; border-radius: 2px;">PAGES: <span style="color: #ccc">${escapeHtml(config.pages || 5)}</span></span>
                    <span style="background: #1a1a1a; padding: 4px 8px; border-radius: 2px;">LIMIT: <span style="color: #ccc">${escapeHtml(config.limit || '∞')}</span></span>
                    <span style="background: #1a1a1a; padding: 4px 8px; border-radius: 2px;">INSTALLS: <span style="color: #ccc">${escapeHtml(config.min_installs || 0)} - ${escapeHtml(config.max_installs || '∞')}</span></span>
                    <span style="background: #1a1a1a; padding: 4px 8px; border-radius: 2px;">UPDATED: <span style="color: #ccc">${escapeHtml(config.min_days || 0)}-${escapeHtml(config.max_days || '∞')}d</span></span>

                    ${config.smart ? '<span style="background: rgba(0, 255, 157, 0.1); color: var(--accent-primary); padding: 4px 8px; border-radius: 2px;">SMART</span>' : ''}
                    ${config.abandoned ? '<span style="background: rgba(255, 0, 85, 0.1); color: var(--accent-secondary); padding: 4px 8px; border-radius: 2px;">ABANDONED</span>' : ''}
                    ${config.user_facing ? '<span style="background: rgba(255, 189, 46, 0.1); color: #ffbd2e; padding: 4px 8px; border-radius: 2px;">USER-FACING</span>' : ''}
                    ${config.themes ? '<span style="background: #333; color: #ccc; padding: 4px 8px; border-radius: 2px;">THEMES</span>' : '<span style="background: #333; color: #ccc; padding: 4px 8px; border-radius: 2px;">PLUGINS</span>'}
                </div>
            </div>
        `;

        summary.innerHTML = `
            <div class="detail-item"><label>STATUS</label><span class="status-badge ${escapeHtml(session.status).toLowerCase()}">${escapeHtml(session.status)}</span></div>
            <div class="detail-item"><label>PLUGINS FOUND</label><span>${session.total_found}</span></div>
            <div class="detail-item"><label>HIGH RISK</label><span class="${session.high_risk_count > 0 ? 'risk-high' : 'risk-low'}">${session.high_risk_count}</span></div>
            <div class="detail-item"><label>DATE</label><span>${new Date(session.created_at || session.start_time).toLocaleString()}</span></div>
            ${configHtml}
        `;

        const resultsResp = await fetch(apiNoCacheUrl(`/api/scans/${id}/results?limit=500`));
        const resultsData = await resultsResp.json();
        window.currentScanResults = resultsData.results || [];
        await refreshFavoriteSlugs();

        if (window.currentScanResults.length > 0) {
            list.innerHTML = window.currentScanResults.map((r, index) => {
                let semgrepBadge = '<span class="tag" style="visibility: hidden; margin: 0; font-size: 9px; width: 85px; display: flex; align-items: center; justify-content: center; height: 24px;"></span>'; // Placeholder for alignment
                if (r.semgrep) {
                    if (r.semgrep.status === 'completed') {
                        const issues = r.semgrep.findings_count;
                        const color = issues > 0 ? '#ff5f56' : '#00ff9d';
                        const label = issues > 0 ? `${issues} ISSUES` : 'CLEAN';
                        semgrepBadge = `<span class="tag" style="background: rgba(${issues>0?'255, 95, 86':'0, 255, 157'}, 0.1); color: ${color}; border: 1px solid rgba(${issues>0?'255, 95, 86':'0, 255, 157'}, 0.3); margin: 0; font-size: 9px; width: 85px; display: flex; align-items: center; justify-content: center; height: 24px;">${label}</span>`;
                    } else if (r.semgrep.status === 'running' || r.semgrep.status === 'pending') {
                        semgrepBadge = `<span class="tag" style="background: rgba(0, 243, 255, 0.1); color: var(--accent-blue); border: 1px solid rgba(0, 243, 255, 0.3); margin: 0; font-size: 9px; width: 85px; display: flex; align-items: center; justify-content: center; height: 24px;">SCANNING</span>`;
                    } else if (r.semgrep.status === 'failed') {
                        semgrepBadge = `<span class="tag" style="background: rgba(255, 0, 85, 0.1); color: #ff0055; border: 1px solid rgba(255, 0, 85, 0.2); margin: 0; font-size: 9px; width: 85px; display: flex; align-items: center; justify-content: center; height: 24px;">FAILED</span>`;
                    }
                }

                const riskClass = (
                    r.relative_risk === 'CRITICAL' || r.relative_risk === 'HIGH'
                ) ? 'risk-high' : (
                    r.relative_risk === 'MEDIUM'
                ) ? 'risk-medium' : (
                    r.score >= 40 ? 'risk-high' : (r.score >= 20 ? 'risk-medium' : 'risk-low')
                );

                return `
                <tr>
                    <td style="color: #fff; font-weight: 500;">${escapeHtml(r.slug)} ${r.is_duplicate ? '<span style="background: rgba(100,100,100,0.3); color: #aaa; padding: 2px 4px; border-radius: 2px; font-size: 9px; margin-left: 5px;">SEEN BEFORE</span>' : ''}</td>
                    <td>${escapeHtml(r.version)}</td>
                    <td><span class="${riskClass}">${r.score}</span></td>
                    <td>${r.days_since_update} days</td>
                    <td>${r.installations}+</td>
                    <td style="display: flex; gap: 5px; align-items: center;">
                        ${semgrepBadge}
                        <button onclick="toggleFavorite('${escapeHtml(r.slug)}')" class="action-btn" style="height: 24px; width: 24px; padding: 0; background: ${isFavoriteSlug(r.slug) ? 'rgba(255, 189, 46, 0.12)' : 'transparent'}; border: 1px solid ${isFavoriteSlug(r.slug) ? 'rgba(255, 189, 46, 0.45)' : 'var(--border-color)'}; color: ${isFavoriteSlug(r.slug) ? '#ffbd2e' : '#666'};" title="${isFavoriteSlug(r.slug) ? 'In Favorites' : 'Add to Favorites'}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                        </button>
                        <a href="${escapeHtml(r.wp_org_link || (r.is_theme ? `https://wordpress.org/themes/${r.slug}/` : `https://wordpress.org/plugins/${r.slug}/`))}" target="_blank" class="action-btn" style="height: 24px; padding: 0 8px; background: #222; color: #ccc; border: 1px solid #333;">WP</a>
                        <button onclick="openPluginModal(${index})" class="action-btn" style="height: 24px; width: auto; background: var(--accent-primary); color: #000;">DETAILS</button>
                    </td>
                </tr>
            `;
            }).join('');
        } else {
            list.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">No results found</td></tr>';
        }

        // Start polling if scan is still running
        if ((session.status || '').toUpperCase() === 'RUNNING') {
            if (detailsPollingInterval) clearInterval(detailsPollingInterval);
            detailsPollingInterval = setInterval(() => {
                if (currentScanId === id) {
                    window.viewScan(id);
                } else {
                    clearInterval(detailsPollingInterval);
                    detailsPollingInterval = null;
                }
            }, 3000); // Refresh every 3 seconds
        } else {
            // Stop polling if scan is not running
            if (detailsPollingInterval) {
                clearInterval(detailsPollingInterval);
                detailsPollingInterval = null;
            }
        }
    } catch (error) {
        summary.innerHTML = `Error: ${escapeHtml(error.message)}`;
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

    if(dashboard) dashboard.style.display = 'block';
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> SCANNING...';
    }
    if(stopBtn) {
        stopBtn.style.display = 'inline-flex';
        stopBtn.disabled = false;
    }
    if(statusEl) {
        statusEl.textContent = 'RESUMING...';
        statusEl.style.color = 'var(--accent-blue)';
        statusEl.style.borderColor = 'rgba(0, 243, 255, 0.2)';
    }
    if(statusDot) {
        statusDot.classList.remove('paused', 'completed');
        statusDot.style.background = 'var(--accent-blue)';
    }

    try {
        const response = await fetch(`/api/semgrep/bulk/${sessionId}`, { method: 'POST' });
        const data = await response.json();

        if(data.success) {
            pollBulkProgress(sessionId);
        } else {
            showToast('Failed to start bulk scan: ' + (data.detail || 'Unknown error'), 'error');
            if(btn) {
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> SCAN ALL (SEMGREP)';
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
        stopBtn.textContent = 'STOPPING...';
    }

    if(statusEl) {
        statusEl.textContent = 'STOPPING...';
        statusEl.style.color = '#ffbd2e';
        statusEl.style.borderColor = 'rgba(255, 189, 46, 0.2)';
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
                statusEl.textContent = 'PAUSED';
                statusEl.style.color = '#ffbd2e';
            }
            if(btn) {
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> RESUME SCAN';
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
    const statusEl = document.getElementById('bulk-status');
    const progressBar = document.getElementById('bulk-progress-bar');
    const scannedEl = document.getElementById('bulk-scanned');
    const totalEl = document.getElementById('bulk-total');
    const issuesEl = document.getElementById('bulk-issues');
    const errorCountEl = document.getElementById('bulk-error-count');
    const warnCountEl = document.getElementById('bulk-warn-count');
    const btn = document.getElementById('btn-bulk-scan');
    const stopBtn = document.getElementById('btn-bulk-stop');

    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/api/semgrep/bulk/${sessionId}/stats`);
            const data = await response.json();

            // Update UI
            if (totalEl) totalEl.textContent = data.total_plugins;
            if (scannedEl) scannedEl.textContent = data.scanned_count;
            if (progressBar) progressBar.style.width = `${data.progress}%`;
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
                    statusEl.textContent = 'PAUSED';
                    statusEl.style.color = '#ffbd2e';
                    statusEl.style.borderColor = 'rgba(255, 189, 46, 0.2)';
                }
                const statusDot = document.getElementById('bulk-status-dot');
                if (statusDot) {
                    statusDot.classList.add('paused');
                    statusDot.style.background = '#ffbd2e';
                }
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> RESUME SCAN';
                }
                if (stopBtn) stopBtn.style.display = 'none';
            } else if (data.progress >= 100) {
                // Scan completed
                clearInterval(interval);
                if (statusEl) {
                    statusEl.textContent = 'COMPLETED';
                    statusEl.style.color = 'var(--accent-primary)';
                    statusEl.style.borderColor = 'rgba(0, 255, 157, 0.2)';
                }
                const statusDot = document.getElementById('bulk-status-dot');
                if (statusDot) {
                    statusDot.classList.add('completed');
                    statusDot.style.background = 'var(--accent-primary)';
                }
                if (progressBar) progressBar.style.backgroundColor = 'var(--accent-primary)';
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'SCAN COMPLETE';
                }
                if (stopBtn) stopBtn.style.display = 'none';
                // Refresh results to show updated badges
                viewScan(sessionId);
            } else {
                // Still running
                if (statusEl) {
                    statusEl.textContent = `SCANNING (${data.progress}%)`;
                    statusEl.style.color = 'var(--accent-blue)';
                    statusEl.style.borderColor = 'rgba(0, 243, 255, 0.2)';
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

    const btn = document.getElementById('btn-deep-scan');
    if(btn) {
        btn.disabled = true;
        btn.textContent = 'SCANNING...';
    }

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
            if(btn) {
                btn.disabled = false;
                btn.textContent = 'DEEP SCAN';
            }
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
        if(btn) {
            btn.disabled = false;
            btn.textContent = 'DEEP SCAN';
        }
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
                const btn = document.getElementById('btn-deep-scan');
                if(btn) {
                    btn.disabled = false;
                    btn.textContent = 'DEEP SCAN';
                }
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
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--accent-primary); border: 1px dashed var(--accent-primary); border-radius: 4px; background: rgba(0,255,157,0.05);">✅ No issues found by Semgrep. Code looks clean.</div>';
        return;
    }

    let html = `<div style="margin-bottom: 15px; font-size: 12px; color: #888;">
        Found <strong style="color: #fff">${scanData.findings.length}</strong> issues
        (ERROR: <span style="color: #ff5f56">${scanData.summary.breakdown.ERROR || 0}</span>,
        WARNING: <span style="color: #ffbd2e">${scanData.summary.breakdown.WARNING || 0}</span>)
    </div>`;

    html += scanData.findings.map(f => `
        <div style="background: #141416; border-left: 3px solid ${f.severity === 'ERROR' ? '#ff5f56' : (f.severity === 'WARNING' ? '#ffbd2e' : '#00f3ff')}; padding: 15px; margin-bottom: 10px; border-radius: 0 4px 4px 0;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="font-weight: 600; font-size: 13px; color: ${f.severity === 'ERROR' ? '#ff5f56' : (f.severity === 'WARNING' ? '#ffbd2e' : '#00f3ff')}">${escapeHtml(f.severity)}: ${escapeHtml(f.rule_id)}</span>
                <span style="font-family: var(--font-mono); font-size: 10px; color: #666;">${escapeHtml(f.file_path)}:${f.line_number}</span>
            </div>
            <div style="font-size: 12px; color: #ccc; margin-bottom: 10px;">${escapeHtml(f.message)}</div>
            ${f.code_snippet ? `<pre style="background: #000; padding: 10px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px; color: #aaa; overflow-x: auto; margin: 0;"><code>${escapeHtml(f.code_snippet)}</code></pre>` : ''}
        </div>
    `).join('');

    container.innerHTML = html;

    const btn = document.getElementById('btn-deep-scan');
    if(btn) {
        btn.disabled = true; // Keep disabled as we have results
        btn.textContent = 'SCAN COMPLETE';
        btn.style.borderColor = 'var(--accent-primary)';
        btn.style.color = 'var(--accent-primary)';
    }
}

window.openPluginModal = function(index) {
    const plugin = window.currentScanResults[index];
    if (!plugin) return;

    // Update URL hash for plugin modal, include scan ID if available
    const scanIdPart = currentScanId ? `/${currentScanId}` : '';
    window.location.hash = `plugin/${plugin.slug}${scanIdPart}`;

    const modal = document.getElementById('plugin-modal');
    const title = document.getElementById('modal-title');
    const content = document.getElementById('modal-content');

    title.textContent = `${escapeHtml(plugin.name || plugin.slug)} (v${escapeHtml(plugin.version)})`;

    const getLink = (url, fallback) => url ? url : fallback;
    const downloadUrl = plugin.download_link || `https://downloads.wordpress.org/plugin/${plugin.slug}.${plugin.version}.zip`;

    let tagsHtml = '';
    if (plugin.is_user_facing) tagsHtml += '<span class="tag warn">USER FACING</span>';
    if (plugin.is_risky_category) tagsHtml += '<span class="tag risk">RISKY CATEGORY</span>';
    if (plugin.author_trusted) tagsHtml += '<span class="tag safe">TRUSTED AUTHOR</span>';
    if (plugin.is_duplicate) tagsHtml += '<span class="tag" style="background: #333;">PREVIOUSLY FOUND</span>';

    const linksHtml = `
        <div class="link-grid">
            ${plugin.download_link ? `<a href="${plugin.download_link}" target="_blank" class="ext-link">📥 Download Zip</a>` : ''}
            <a href="${getLink(plugin.trac_link, plugin.is_theme ? `https://themes.trac.wordpress.org/log/${plugin.slug}/` : `https://plugins.trac.wordpress.org/log/${plugin.slug}/`)}" target="_blank" class="ext-link">📜 View Source (Trac)</a>
            <a href="${getLink(plugin.cve_search_link, `https://cve.mitre.org/cgi-bin/cvekey.cgi?keyword=${plugin.slug}`)}" target="_blank" class="ext-link">🛡️ CVE Search</a>
            <a href="${getLink(plugin.wpscan_link, plugin.is_theme ? `https://wpscan.com/theme/${plugin.slug}` : `https://wpscan.com/plugin/${plugin.slug}`)}" target="_blank" class="ext-link">🔍 WPScan</a>
            <a href="${getLink(plugin.patchstack_link, `https://patchstack.com/database?search=${plugin.slug}`)}" target="_blank" class="ext-link">🩹 Patchstack</a>
            <a href="${getLink(plugin.wordfence_link, `https://www.wordfence.com/threat-intel/vulnerabilities/search?search=${plugin.slug}`)}" target="_blank" class="ext-link">🦁 Wordfence</a>
            <a href="${getLink(
                plugin.google_dork_link,
                `https://www.google.com/search?q=${encodeURIComponent(
                    plugin.is_theme
                        ? `"${plugin.slug}" intext:"${plugin.slug}" ("wordpress theme" OR "wp theme" OR "wordpress.org/themes/${plugin.slug}") (vulnerability OR exploit OR cve) -"wordpress plugin" -"plugins/"`
                        : `"${plugin.slug}" intext:"${plugin.slug}" ("wordpress plugin" OR "wp plugin" OR "wordpress.org/plugins/${plugin.slug}") (vulnerability OR exploit OR cve) -"wordpress theme" -"themes/"`
                )}`
            )}" target="_blank" class="ext-link">🔎 Google Dork</a>
        </div>
    `;

    content.innerHTML = `
        <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: start;">
            <div>
                <div style="display: flex; gap: 20px; margin-bottom: 15px; font-size: 12px; color: #888;">
                    <span>Score: <strong style="color: ${plugin.score >= 40 ? '#ff5f56' : (plugin.score >= 20 ? '#ffbd2e' : '#00ff9d')}">${plugin.score}/100</strong></span>
                    <span>Installs: <strong style="color: #fff">${plugin.installations}+</strong></span>
                    <span>Updated: <strong style="color: #fff">${plugin.days_since_update} days ago</strong></span>
                </div>
                <div>${tagsHtml}</div>
            </div>
            <div style="display: flex; gap: 10px;">
                <button id="btn-deep-scan" onclick="runPluginSemgrep('${escapeHtml(plugin.slug)}', '${escapeHtml(downloadUrl)}')" class="action-btn" style="background: rgba(0, 243, 255, 0.1); border: 1px solid var(--accent-blue); color: var(--accent-blue); width: auto; height: 30px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 5px;"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
                    DEEP SCAN
                </button>
                <button onclick="toggleFavorite('${plugin.slug}')" class="action-btn" style="background: transparent; border: 1px solid var(--accent-primary); color: var(--accent-primary); width: auto; height: 30px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                    FAVORITE
                </button>
            </div>
        </div>

        <div class="section-title">SECURITY RESOURCES</div>
        ${linksHtml}

        <div class="section-title">SEMGREP ANALYSIS</div>
        <div id="semgrep-results-container">
            <div style="text-align: center; padding: 20px; color: #888; font-size: 12px; border: 1px dashed #333; border-radius: 4px; background: rgba(0,0,0,0.2);">
                <p style="margin-bottom: 10px; color: var(--accent-blue);">ℹ️ No Semgrep Analysis Yet</p>
                The initial "Score" is calculated from metadata and changelog analysis only.
                Click <strong>"DEEP SCAN"</strong> to perform a full Semgrep SAST analysis on this target.
            </div>
        </div>
    `;

    // Check if scan already exists
    fetch(`/api/semgrep/scan/${plugin.slug}`)
        .then(res => res.json())
        .then(data => {
            if(data.status === 'completed') {
                loadSemgrepResultsIntoModal(data);
            } else if (data.status === 'running' || data.status === 'pending') {
                document.getElementById('semgrep-results-container').innerHTML = '<div style="text-align: center; padding: 20px; color: var(--accent-blue);">Scan in progress...</div>';
                const btn = document.getElementById('btn-deep-scan');
                if(btn) {
                    btn.disabled = true;
                    btn.textContent = 'SCANNING...';
                }
                pollSemgrepResults(plugin.slug);
            }
        })
        .catch(() => {});

    modal.classList.add('active');

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
    document.getElementById('plugin-modal').classList.remove('active');
    
    // Clear plugin hash when modal closes, revert to previous view or scan
    const currentHash = window.location.hash;
    if (currentHash.startsWith('#plugin/')) {
        // Try to get scanId from URL if currentScanId is not set
        let scanId = currentScanId;
        if (!scanId) {
            const parts = currentHash.split('/');
            if (parts[2] && !isNaN(parseInt(parts[2]))) {
                scanId = parseInt(parts[2]);
            }
        }
        
        // Go back to scan details if we came from there, otherwise go to history
        if (scanId) {
            window.location.hash = `details/${scanId}`;
        } else {
            window.location.hash = 'history';
        }
    }
}

// ==========================================
// SEMGREP RULES MANAGEMENT
// ==========================================

window.loadSemgrepRules = async function() {
    const statusEl = document.getElementById('semgrep-status');
    const ruleCountEl = document.getElementById('semgrep-rule-count');
    const customCountEl = document.getElementById('semgrep-custom-count');
    const rulesListEl = document.getElementById('semgrep-rules-list');

    if (!statusEl) return;

    statusEl.textContent = 'Loading...';
    statusEl.style.color = '#ffbd2e';

    try {
        const response = await fetch('/api/semgrep/rules');
        const data = await response.json();

        // Update status
        if (data.installed) {
            statusEl.textContent = 'INSTALLED';
            statusEl.style.color = 'var(--accent-primary)';
        } else {
            statusEl.textContent = 'NOT INSTALLED';
            statusEl.style.color = 'var(--accent-secondary)';
        }

        // Update counts
        const activeRulesets = (data.rulesets || []).filter(r => r.enabled).length;
        ruleCountEl.textContent = activeRulesets; // Renamed label to "ACTIVE PACKS" in HTML
        customCountEl.textContent = data.custom_rules ? data.custom_rules.length : 0;

        // Clean up UI - Remove old registry count if exists
        const registryCountEl = document.getElementById('semgrep-registry-count');
        if (registryCountEl && registryCountEl.parentNode) {
            registryCountEl.parentNode.style.display = 'none';
        }

        // 1. RENDER RULESETS
        let html = '';

        html += `<h3 style="font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); margin-bottom: 15px; border-bottom: 1px solid #222; padding-bottom: 8px; margin-top: 10px;">📦 SECURITY RULESETS</h3>`;
        html += `<div style="display:flex; gap:10px; align-items:center; margin: -4px 0 14px 0;">
                <input type="text" id="new-ruleset-id" placeholder="p/cwe-top-25 or p/owasp-top-ten" style="flex:1; min-width: 260px; padding: 9px 10px; background: #0a0a0a; border: 1px solid #333; border-radius: 4px; color: #fff; font-family: var(--font-mono); font-size:11px;">
                <button onclick="addSemgrepRuleset()" class="action-btn" style="width:auto; padding:8px 12px; background: rgba(0, 255, 157, 0.1); border: 1px solid rgba(0, 255, 157, 0.35); color: var(--accent-primary); font-size:11px;">
                    ADD RULESET
                </button>
            </div>`;
        html += `<div style="margin: -4px 0 14px 0;">
                <a href="https://semgrep.dev/explore" target="_blank" class="tag safe" style="text-decoration: none; cursor: pointer; padding: 8px 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 8px; border-radius: 4px; border: 1px solid rgba(0, 255, 157, 0.3); background: rgba(0, 255, 157, 0.05); font-size: 11px;">
                    <span>🔍</span> Explore 3000+ Community Rules on Semgrep Registry →
                </a>
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

        // 2. RENDER CUSTOM RULES
        html += `<h3 style="font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); margin-bottom: 15px; border-bottom: 1px solid #222; padding-bottom: 8px; margin-top: 30px;">✏️ CUSTOM RULES</h3>`;

        const customRules = data.custom_rules || [];
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
        statusEl.textContent = 'ERROR';
        statusEl.style.color = 'var(--accent-secondary)';
        rulesListEl.innerHTML = `<div style="text-align: center; color: var(--accent-secondary); padding: 30px;">Error loading rules: ${escapeHtml(error.message)}</div>`;
    }
}

window.toggleRuleset = async function(rulesetId) {
    try {
        const response = await fetch(`/api/semgrep/rulesets/${encodeURIComponent(rulesetId)}/toggle`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            loadSemgrepRules(); // Reload UI
        } else {
            showToast('Failed to toggle ruleset', 'error');
        }
    } catch (error) {
        console.error('Error toggling ruleset:', error);
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
        const data = await response.json();
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
        const data = await response.json();

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
        const data = await response.json();

        if (data.success) {
            loadSemgrepRules(); // Reload UI
        } else {
            showToast('Failed to toggle rule', 'error');
        }
    } catch (error) {
        console.error('Error toggling rule:', error);
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

        const data = await response.json();

        if (data.success) {
            loadSemgrepRules();
        } else {
            showToast('Failed to delete rule: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error deleting rule: ' + error.message, 'error');
    }
}
