(function() {
    const runtime = window.temodarAgentRuntime;

    function getRunButtonMarkup() {
        return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>RUN SCAN</span>';
    }

    function resetRunButton(runBtn) {
        if (!runBtn) return;
        runBtn.disabled = false;
        runBtn.innerHTML = getRunButtonMarkup();
    }

    function buildScanRequestData(form) {
        const pagesValue = preparePagesValueBeforeScan();
        const formData = new FormData(form);

        return {
            pages: pagesValue,
            limit: parseInt(formData.get('limit'), 10) || 0,
            min_installs: parseInt(formData.get('min_installs'), 10) || 0,
            max_installs: parseInt(formData.get('max_installs'), 10) || 0,
            sort: formData.get('sort') || 'updated',
            smart: formData.get('smart') === 'on',
            abandoned: formData.get('abandoned') === 'on',
            user_facing: formData.get('user_facing') === 'on',
            themes: formData.get('themes') === 'on',
            min_days: parseInt(formData.get('min_days'), 10) || 0,
            max_days: parseInt(formData.get('max_days'), 10) || 0,
        };
    }

    function setRunButtonStarting(runBtn) {
        if (!runBtn) return;
        runBtn.disabled = true;
        runBtn.innerHTML = '<span>STARTING...</span>';
    }

    function setScanStatusUi(label, tone) {
        const statusEl = document.getElementById('scan-status');
        if (!statusEl) return;
        statusEl.textContent = label;
        statusEl.className = `metric-value info-value ${tone}`;
    }

    function markScanRunning() {
        setScanStatusUi('RUNNING', 'running');
    }

    function markScanCompleted() {
        setScanStatusUi('COMPLETED', 'completed');
    }

    function markScanCancelled() {
        setScanStatusUi('CANCELLED', 'cancelled');
    }

    function markScanFailed() {
        setScanStatusUi('FAILED', 'failed');
    }

    function markScanMerged() {
        setScanStatusUi('MERGED', 'completed');
    }

    function startScanDetailsPolling(sessionId) {
        stopDetailsPolling();
        const poller = setInterval(() => {
            if (runtime.getCurrentScanId() === sessionId) {
                window.viewScan(sessionId);
                return;
            }
            clearInterval(poller);
            runtime.setDetailsPollingInterval(null);
        }, 3000);
        runtime.setDetailsPollingInterval(poller);
    }

    function stopDetailsPolling() {
        const interval = runtime.getDetailsPollingInterval();
        if (interval) {
            clearInterval(interval);
            runtime.setDetailsPollingInterval(null);
        }
    }

    function closeActiveSocket() {
        const currentSocket = runtime.getSocket();
        if (currentSocket) currentSocket.close();
    }

    function setCurrentScanResults(results) {
        window.currentScanResults = Array.isArray(results) ? results : [];
    }

    function getCurrentScanResults() {
        return Array.isArray(window.currentScanResults) ? window.currentScanResults : [];
    }

    window.refreshAfterScanEvent = function(sessionId) {
        loadHistory();
        const catalogView = document.getElementById('catalog-view');
        if (catalogView && catalogView.style.display !== 'none') {
            loadCatalog();
        }
        if (!sessionId) return;

        if (isDetailsViewActive() && runtime.getCurrentScanId() === sessionId) {
            setTimeout(() => {
                if (runtime.getCurrentScanId() === sessionId) window.viewScan(sessionId);
            }, 250);
            setTimeout(() => {
                if (runtime.getCurrentScanId() === sessionId) window.viewScan(sessionId);
            }, 1200);
        }
    };

    window.syncFinalScanResults = async function(sessionId, expectedCount = 0) {
        if (!sessionId || !isDetailsViewActive()) return;
        const targetCount = parseInt(expectedCount || 0, 10);
        for (let i = 0; i < 6; i += 1) {
            if (runtime.getCurrentScanId() !== sessionId) return;
            await window.viewScan(sessionId);
            const currentCount = getCurrentScanResults().length;
            if (targetCount <= 0 || currentCount >= targetCount) return;
            await new Promise((resolve) => setTimeout(resolve, 350 * (i + 1)));
        }
    };

    window.setScanProgressState = function(percent, stage, detail) {
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
    };

    window.setProgressDetailsButton = function(visible) {
        const btn = document.getElementById('scan-progress-details-btn');
        if (!btn) return;
        const shouldShow = Boolean(visible) && Boolean(runtime.getCurrentScanId());
        btn.style.display = shouldShow ? 'inline-flex' : 'none';
    };

    window.openProgressScanDetails = function() {
        if (!runtime.getCurrentScanId()) return;
        window.viewScan(runtime.getCurrentScanId());
    };

    window.logTerminal = function(text, type = 'info') {
        const stageMap = {
            error: 'Failed',
            'high-risk': 'Warning',
            success: 'Completed',
            warn: 'Notice',
            info: 'Running'
        };
        const stage = stageMap[type] || 'Running';
        window.setScanProgressState(null, stage, text);
    };

    window.clearTerminal = function() {
        window.setScanProgressState(0, 'Initializing', 'Preparing scan session...');
        window.setProgressDetailsButton(false);
    };

    window.connectWebSocket = function(sessionId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/scans/${sessionId}`;
        closeActiveSocket();

        const ws = new WebSocket(wsUrl);
        runtime.setSocket(ws);

        ws.onopen = () => {
            if (runtime.getSocket() !== ws) return;
            window.logTerminal('WebSocket connected', 'info');
            window.setScanProgressState(10, 'Running', 'Realtime channel connected');
        };
        ws.onmessage = (event) => {
            if (runtime.getSocket() !== ws) return;
            const payload = JSON.parse(event.data);
            window.handleMessage(payload, sessionId);
        };
        ws.onclose = () => {
            if (runtime.getSocket() !== ws) return;
            window.logTerminal('WebSocket connection closed', 'info');
            window.reconcileScanStatus(sessionId);
        };
        ws.onerror = () => {
            if (runtime.getSocket() !== ws) return;
            window.logTerminal('WebSocket error', 'error');
            window.reconcileScanStatus(sessionId);
        };
    };

    window.reconcileScanStatus = async function(sessionId) {
        if (!sessionId) return;
        if (runtime.getCurrentScanId() !== sessionId) return;

        const runBtn = document.getElementById('runBtn');
        try {
            const response = await fetch(apiNoCacheUrl(`/api/scans/${sessionId}`));
            if (!response.ok) return;
            const session = await response.json();
            const status = String(session.status || '').toLowerCase();
            const totalFound = Number(session.total_found || 0);
            const highRiskCount = Number(session.high_risk_count || 0);

            if (status === 'completed') {
                markScanCompleted();
                window.setScanProgressState(100, 'Completed', `Found ${totalFound} total / ${highRiskCount} high risk`);
                window.setProgressDetailsButton(true);
                window.refreshAfterScanEvent(sessionId);
            } else if (status === 'cancelled') {
                markScanCancelled();
                window.setScanProgressState(100, 'Cancelled', `Found ${totalFound} total / ${highRiskCount} high risk`);
                window.setProgressDetailsButton(true);
                window.refreshAfterScanEvent(sessionId);
            } else if (status === 'failed') {
                markScanFailed();
                window.setScanProgressState(100, 'Failed', 'Scan terminated with an error');
                window.setProgressDetailsButton(false);
                window.refreshAfterScanEvent(sessionId);
            }
        } catch (error) {
            console.error('Failed to reconcile scan status:', error);
        } finally {
            resetRunButton(runBtn);
        }
    };

    window.handleMessage = function(msg, sourceSessionId = null) {
        const runBtn = document.getElementById('runBtn');
        const currentScanId = runtime.getCurrentScanId();

        if (sourceSessionId && currentScanId && Number(sourceSessionId) !== Number(currentScanId)) return;
        if (msg && msg.session_id && currentScanId && Number(msg.session_id) !== Number(currentScanId)) return;

        switch (msg.type) {
            case 'start':
                window.logTerminal('Scan execution started...', 'info');
                window.setScanProgressState(12, 'Running', 'Execution started');
                window.setProgressDetailsButton(false);
                break;
            case 'progress': {
                const percent = Number(msg.percent || 0);
                const current = Number(msg.current || 0);
                const total = Number(msg.total || 0);
                const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
                const detail = total > 0 ? `Processed ${current}/${total} targets` : `Processed ${current} targets`;
                window.setScanProgressState(safePercent, 'Running', detail);
                break;
            }
            case 'result':
                window.logTerminal(`${msg.data.score >= 40 ? '[HIGH RISK]' : '[INFO]'} Found: ${msg.data.slug} (Score: ${msg.data.score})`, msg.data.score >= 40 ? 'high-risk' : 'low-risk');
                document.getElementById('scan-found').textContent = msg.found_count;
                appendTrendPoint(msg.found_count);
                window.setScanProgressState(null, 'Running', `Detected ${msg.found_count} findings`);
                break;
            case 'deduplicated':
                window.logTerminal(`Scan identical to Session #${msg.original_session_id}. Merging...`, 'warn');
                window.logTerminal('Session merged. History updated.', 'success');
                runtime.setCurrentScanId(msg.original_session_id);
                markScanMerged();
                resetRunButton(runBtn);
                window.setScanProgressState(100, 'Merged', `Merged into Session #${msg.original_session_id}`);
                window.setProgressDetailsButton(true);
                window.refreshAfterScanEvent(runtime.getCurrentScanId());
                break;
            case 'cancelled':
                window.logTerminal(`Scan cancelled. Found: ${msg.total_found || 0}, High Risk: ${msg.high_risk_count || 0}`, 'warn');
                markScanCancelled();
                resetRunButton(runBtn);
                window.setScanProgressState(100, 'Cancelled', `Found ${msg.total_found || 0} total / ${msg.high_risk_count || 0} high risk`);
                window.setProgressDetailsButton(true);
                window.refreshAfterScanEvent(runtime.getCurrentScanId());
                stopDetailsPolling();
                break;
            case 'complete':
                window.logTerminal(`Scan completed. Found: ${msg.total_found}, High Risk: ${msg.high_risk_count}`, 'success');
                markScanCompleted();
                resetRunButton(runBtn);
                window.setScanProgressState(100, 'Completed', `Found ${msg.total_found} total / ${msg.high_risk_count} high risk`);
                window.setProgressDetailsButton(true);
                window.refreshAfterScanEvent(runtime.getCurrentScanId());
                if (runtime.getCurrentScanId() && isDetailsViewActive()) {
                    window.syncFinalScanResults(runtime.getCurrentScanId(), msg.total_found);
                }
                stopDetailsPolling();
                break;
            case 'error':
                window.logTerminal(`Error: ${msg.message}`, 'error');
                markScanFailed();
                resetRunButton(runBtn);
                window.setScanProgressState(100, 'Failed', msg.message || 'Scan terminated with an error');
                window.setProgressDetailsButton(false);
                window.refreshAfterScanEvent(runtime.getCurrentScanId());
                stopDetailsPolling();
                break;
            default:
                break;
        }
    };

    window.runScan = async function() {
        const form = document.getElementById('configForm');
        const runBtn = document.getElementById('runBtn');
        const requestData = buildScanRequestData(form);

        setRunButtonStarting(runBtn);
        window.setProgressDetailsButton(false);
        window.clearTerminal();
        window.logTerminal('Initializing scan...', 'info');
        window.setScanProgressState(5, 'Starting', 'Submitting scan request');

        try {
            const response = await fetch('/api/scans', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData)
            });
            const data = await response.json();

            if (!data.session_id) {
                window.logTerminal('Failed to start scan', 'error');
                window.setScanProgressState(100, 'Failed', 'Scan session could not be started');
                window.setProgressDetailsButton(false);
                resetRunButton(runBtn);
                return;
            }

            runtime.setCurrentScanId(data.session_id);
            window.logTerminal(`Scan session started: ID ${runtime.getCurrentScanId()}`, 'success');
            window.setScanProgressState(8, 'Starting', `Session #${runtime.getCurrentScanId()} created`);
            window.connectWebSocket(runtime.getCurrentScanId());
            markScanRunning();
        } catch (error) {
            window.logTerminal(`Error: ${error.message}`, 'error');
            window.setScanProgressState(100, 'Failed', error.message || 'Unknown error');
            window.setProgressDetailsButton(false);
            resetRunButton(runBtn);
        }
    };

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

    function resolvePluginModalReturnHash(urlState) {
        if (urlState.view && urlState.view !== 'plugin-detail') {
            if (urlState.view === 'details' && urlState.scanId) {
                return `details/${urlState.scanId}`;
            }
            return urlState.view;
        }

        const currentReturnHash = runtime.getModalReturnHash();
        if (!currentReturnHash || String(currentReturnHash).startsWith('plugin/')) {
            return runtime.getCurrentScanId() ? `details/${runtime.getCurrentScanId()}` : 'history';
        }

        return currentReturnHash;
    }

    function initializePluginAiPanel(plugin) {
        bindPluginAiUiEvents();
        const state = typeof window.getPluginAiState === 'function' ? window.getPluginAiState() : {};
        const samePlugin = String(state.plugin || '').trim() === String(plugin.slug || '').trim() && !!state.isTheme === !!plugin.is_theme;

        if (!samePlugin) {
            beginPluginAiView(plugin.slug, !!plugin.is_theme);
            renderPluginAiMessages([]);
            renderPluginAiActivity([]);
            setPluginAiBadge('Idle');
            setPluginAiStatus(`Preparing AI context for ${plugin.slug || plugin.name || 'plugin'}...`);
            setPluginAiComposerEnabled(false);
            return;
        }

        refreshPluginAiRenderedState();
        setPluginAiBadge(state.sending ? 'Running' : (typeof window.buildPluginAiThreadBadge === 'function' ? window.buildPluginAiThreadBadge() : 'Ready'));
        setPluginAiStatus(state.sending
            ? 'Restoring AI chat…'
            : `Restoring AI context for ${plugin.slug || plugin.name || 'plugin'}...`);
        setPluginAiComposerEnabled(!state.sending && !!state.threadId);
    }

    function buildPluginTagsHtml(plugin) {
        let tagsHtml = '';
        if (plugin.is_user_facing) tagsHtml += '<span class="tag warn">USER FACING</span>';
        if (plugin.is_risky_category) tagsHtml += '<span class="tag risk">RISKY CATEGORY</span>';
        if (plugin.author_trusted) tagsHtml += '<span class="tag safe">TRUSTED AUTHOR</span>';
        if (plugin.is_duplicate) tagsHtml += '<span class="tag" style="background: #333;">PREVIOUSLY FOUND</span>';
        return tagsHtml || '<span class="tag">NO TAGS</span>';
    }

    function buildPluginModalViewModel(plugin) {
        const artifactType = plugin.is_theme ? 'theme' : 'plugin';
        const artifactVersion = plugin.version || 'latest';
        const downloadUrl = plugin.download_link || `https://downloads.wordpress.org/${artifactType}/${plugin.slug}.${artifactVersion}.zip`;
        const pluginSlug = String(plugin.slug || '');
        const pluginScore = parseInt(plugin.score || 0, 10) || 0;

        return {
            pluginSlug,
            pluginSlugJs: JSON.stringify(pluginSlug),
            downloadUrl,
            downloadUrlJs: JSON.stringify(String(downloadUrl || '')),
            tagsHtml: buildPluginTagsHtml(plugin),
            isFav: isFavoriteSlug(plugin.slug),
            pluginScore,
            pluginScoreColor: getRiskColorForScore(pluginScore),
            semgrepFindings: String((plugin.semgrep && plugin.semgrep.findings_count) || plugin.latest_semgrep_findings || 0),
        };
    }

    function renderPluginModalContent(plugin, content) {
        if (!content) return null;
        const vm = buildPluginModalViewModel(plugin);

        content.innerHTML = `
            <section class="plugin-hero">
                <div class="plugin-metrics-grid">
                    <article class="plugin-metric-card"><span class="plugin-metric-label">Risk Score</span><span class="plugin-metric-value" style="color:${vm.pluginScoreColor}">${vm.pluginScore}/100</span><span class="plugin-metric-sub">Current plugin risk level</span></article>
                    <article class="plugin-metric-card"><span class="plugin-metric-label">Installs</span><span class="plugin-metric-value">${escapeHtml(String(plugin.installations || 0))}+</span><span class="plugin-metric-sub">Active install footprint</span></article>
                    <article class="plugin-metric-card"><span class="plugin-metric-label">Updated</span><span class="plugin-metric-value">${escapeHtml(String(plugin.days_since_update || 0))}d</span><span class="plugin-metric-sub">Days since last update</span></article>
                    <article class="plugin-metric-card"><span class="plugin-metric-label">Semgrep</span><span class="plugin-metric-value">${escapeHtml(vm.semgrepFindings)}</span><span class="plugin-metric-sub">Known findings count</span></article>
                </div>
            </section>

            <section class="plugin-toolbar">
                <div class="plugin-toolbar-tags">${vm.tagsHtml}</div>
                <div class="plugin-toolbar-actions">
                    <button id="plugin-fav-btn" onclick='toggleFavorite(${vm.pluginSlugJs})' class="action-btn details-fav-btn plugin-fav-inline${vm.isFav ? ' active' : ''}" title="${vm.isFav ? 'In Favorites' : 'Add to Favorites'}" aria-label="${vm.isFav ? 'Remove from' : 'Add to'} favorites">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
                    </button>
                    <a href="${escapeHtml(vm.downloadUrl)}" target="_blank" rel="noreferrer noopener" class="action-btn plugin-action-download"><span>DOWNLOAD ZIP</span></a>
                    <button id="btn-deep-scan" onclick='runPluginSemgrep(${vm.pluginSlugJs}, ${vm.downloadUrlJs})' class="action-btn plugin-action-secondary">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
                        <span>RE-SCAN</span>
                    </button>
                </div>
            </section>

            <section class="plugin-section">
                <div class="section-title">Semgrep Analysis</div>
                <div id="semgrep-results-container"><div class="plugin-semgrep-empty">No Semgrep analysis yet. Click <strong>RE-SCAN</strong> to run deep static analysis for this plugin.</div></div>
            </section>
        `;

        return vm;
    }

    function preloadPluginSemgrepState(slug) {
        fetch(`/api/semgrep/scan/${slug}`)
            .then((res) => res.json())
            .then((data) => {
                if (data.status === 'completed') {
                    loadSemgrepResultsIntoModal(data);
                } else if (data.status === 'running' || data.status === 'pending') {
                    document.getElementById('semgrep-results-container').innerHTML = '<div class="plugin-semgrep-empty">Semgrep scan in progress...</div>';
                    setDeepScanButtonState('scanning');
                    pollSemgrepResults(slug);
                }
            })
            .catch(() => {});
    }

    function preloadPluginSemgrepAvailability() {
        fetch('/api/semgrep/rules')
            .then((res) => res.json())
            .then((rulesData) => {
                const activeRulesets = (rulesData.rulesets || []).filter((r) => r.enabled).length;
                const activeCustomRules = (rulesData.custom_rules || []).filter((r) => r.enabled).length;
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

    function loadSemgrepResultsIntoModal(scanData) {
        const container = document.getElementById('semgrep-results-container');
        if (!container) return;

        const findings = Array.isArray(scanData && scanData.findings) ? scanData.findings : null;
        const summary = (scanData && scanData.summary && typeof scanData.summary === 'object') ? scanData.summary : {};
        const totalFindings = Number(summary.total_findings || 0);
        const completedAt = scanData && scanData.completed_at ? String(scanData.completed_at) : '';
        const isCompleted = String((scanData && scanData.status) || '').toLowerCase() === 'completed';
        const summaryErrors = Array.isArray(summary.errors) ? summary.errors.filter(Boolean) : [];

        if (!scanData || !isCompleted || findings === null) {
            container.innerHTML = '<div class="plugin-semgrep-empty">Semgrep result is incomplete or unavailable right now. Please retry the scan or refresh this plugin view.</div>';
            setDeepScanButtonState('rescan');
            return;
        }

        if (findings.length === 0 && totalFindings === 0) {
            const completedLabel = completedAt ? ` Last completed: <strong>${escapeHtml(completedAt)}</strong>.` : '';
            const warningHtml = summaryErrors.length
                ? `<div class="plugin-semgrep-summary" style="border-left-color: var(--warn); margin-bottom: 12px;">Scan completed with parser/runtime warnings:<br>${summaryErrors.slice(0, 5).map((error) => `• ${escapeHtml(String(error))}`).join('<br>')}</div>`
                : '';
            container.innerHTML = `${warningHtml}<div class="plugin-semgrep-empty">No issues were reported by the latest completed Semgrep scan.${completedLabel}</div>`;
            setDeepScanButtonState('rescan');
            return;
        }

        const breakdown = (summary && summary.breakdown) ? summary.breakdown : {};
        const warningHtml = summaryErrors.length
            ? `<div class="plugin-semgrep-summary" style="border-left-color: var(--warn); margin-bottom: 12px;">Scan completed with parser/runtime warnings:<br>${summaryErrors.slice(0, 5).map((error) => `• ${escapeHtml(String(error))}`).join('<br>')}</div>`
            : '';

        let html = `${warningHtml}<div class="plugin-semgrep-summary">Found <strong>${findings.length}</strong> issues (ERROR: <span class="sev-error">${breakdown.ERROR || 0}</span>, WARNING: <span class="sev-warning">${breakdown.WARNING || 0}</span>)</div>`;

        html += findings.map((f) => {
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

    async function pollSemgrepResults(slug) {
        const interval = setInterval(async () => {
            try {
                const response = await fetch(`/api/semgrep/scan/${slug}`);
                const data = await response.json();

                if (data.status === 'completed') {
                    clearInterval(interval);
                    loadSemgrepResultsIntoModal(data);
                    const summaryErrors = Array.isArray(data && data.summary && data.summary.errors) ? data.summary.errors.filter(Boolean) : [];
                    if (summaryErrors.length) {
                        showToast(`Semgrep scan completed with ${summaryErrors.length} warning(s). Findings were preserved.`, 'warn');
                    }
                } else if (data.status === 'failed') {
                    clearInterval(interval);
                    showToast('Semgrep scan failed: ' + (data.error_message || 'Unknown error'), 'error');
                    setDeepScanButtonState('rescan');
                }
            } catch (e) {
                clearInterval(interval);
            }
        }, 3000);
    }

    window.runPluginSemgrep = async function(slug, downloadUrl) {
        try {
            const rulesResponse = await fetch('/api/semgrep/rules');
            const rulesData = await rulesResponse.json();
            const activeRulesets = (rulesData.rulesets || []).filter((r) => r.enabled).length;
            const activeCustomRules = (rulesData.custom_rules || []).filter((r) => r.enabled).length;

            if (activeRulesets === 0 && activeCustomRules === 0) {
                showToast('Semgrep is disabled. Please enable at least one ruleset in Semgrep Settings.', 'warn');
                switchTab('semgrep');
                return;
            }
        } catch (e) {
            showToast('Failed to check Semgrep configuration.', 'error');
            return;
        }

        const confirmed = await showConfirm(`Run deep Semgrep analysis on ${slug}? This may take a few minutes.`);
        if (!confirmed) return;

        setDeepScanButtonState('scanning');

        try {
            const response = await fetch('/api/semgrep/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ slug, download_url: downloadUrl })
            });

            const data = await response.json();
            if (data.success) {
                showToast('Semgrep scan started in background. Check back in a few minutes.', 'success');
                pollSemgrepResults(slug);
            } else {
                showToast('Failed to start scan', 'error');
                setDeepScanButtonState('rescan');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
            setDeepScanButtonState('rescan');
        }
    };

    window.viewScan = async function(id, options = {}) {
        const { syncUrl = true } = options;
        switchTab('details', { syncUrl: false });
        runtime.setCurrentScanId(id);
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
            setCurrentScanResults(resultsData.results || []);
            runtime.setDetailsSourceCache(getCurrentScanResults());
            await refreshFavoriteSlugs();

            initializeDetailsFilters();
            runtime.setDetailsCurrentPage(1);
            window.renderDetailsDashboard(getCurrentScanResults());
            applyDetailsFilters();

            const existingBulkInterval = runtime.getDetailsBulkPollingInterval();
            if (existingBulkInterval) {
                clearInterval(existingBulkInterval);
                runtime.setDetailsBulkPollingInterval(null);
            }
            const bulkStats = await window.refreshDetailsBulkStatus(id);
            if (bulkStats && bulkStats.is_running) {
                const bulkTimer = setInterval(async () => {
                    try {
                        const stats = await window.refreshDetailsBulkStatus(id);
                        if (!stats.is_running) {
                            clearInterval(bulkTimer);
                            runtime.setDetailsBulkPollingInterval(null);
                        }
                    } catch (err) {
                        console.error('Details bulk polling error', err);
                    }
                }, 1500);
                runtime.setDetailsBulkPollingInterval(bulkTimer);
            }

            if ((session.status || '').toUpperCase() === 'RUNNING') {
                startScanDetailsPolling(id);
            } else {
                stopDetailsPolling();
            }
        } catch (error) {
            window.setDetailsBulkControls('idle');
            window.renderDetailsDashboard([]);
            if (list) list.innerHTML = '<tr><td colspan="7" class="favorites-empty">Failed to load scan details</td></tr>';
        }
    };

    window.openPluginModal = function(index, options = {}) {
        const { syncUrl = true } = options;
        const plugin = getCurrentScanResults()[index];
        if (!plugin) return;

        const urlState = getUrlState();
        runtime.setModalReturnHash(resolvePluginModalReturnHash(urlState));

        if (syncUrl) {
            setUrlState({
                view: 'plugin-detail',
                scanId: runtime.getCurrentScanId() || urlState.scanId || null,
                plugin: plugin.slug,
            }, { replace: false });
        }

        switchTab('plugin-detail', { syncUrl: false });

        const title = document.getElementById('plugin-page-title');
        const desc = document.getElementById('plugin-page-desc');
        const content = document.getElementById('plugin-page-content');

        if (title) title.textContent = String(plugin.slug || plugin.name || 'PLUGIN').toUpperCase();
        if (desc) desc.textContent = `Inspect metadata and Semgrep findings for ${plugin.slug || plugin.name || 'the selected plugin'}.`;

        initializePluginAiPanel(plugin);
        if (!content) return;

        renderPluginModalContent(plugin, content);
        setDeepScanButtonState('default');
        ensurePluginAiThread(plugin);
        preloadPluginSemgrepState(plugin.slug);
        preloadPluginSemgrepAvailability();
    };

    window.closeModal = function() {
        const fallbackHash = runtime.getCurrentScanId() ? `details/${runtime.getCurrentScanId()}` : 'history';
        const currentReturnHash = runtime.getModalReturnHash();
        const targetHash = currentReturnHash && !String(currentReturnHash).startsWith('plugin/') ? currentReturnHash : fallbackHash;

        if (String(targetHash).startsWith('details/')) {
            const scanId = parseInt(String(targetHash).split('/')[1], 10);
            const resolvedScan = Number.isFinite(scanId) ? scanId : (runtime.getCurrentScanId() || null);
            if (resolvedScan) {
                setUrlState({ view: 'details', scanId: resolvedScan, plugin: '' }, { replace: false });
                window.viewScan(resolvedScan, { syncUrl: false });
                return;
            }
        }

        const tabId = runtime.getViewToTab()[String(targetHash)] || 'history';
        setUrlState({ view: runtime.getTabToView()[tabId] || 'history', scanId: null, plugin: '' }, { replace: false });
        switchTab(tabId, { syncUrl: false });
    };
})();
