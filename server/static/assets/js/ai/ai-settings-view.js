(function() {
    const AI_SETTINGS_STATUS_STORAGE_KEY = 'temodarAgent.aiSettings.testStatusByProfile';
    const PROVIDER_DEFAULTS = {
        anthropic: {
            displayName: 'Anthropic',
            baseUrl: 'https://api.anthropic.com',
            modelHint: 'claude-sonnet-4-5',
            apiKeyPlaceholder: 'Enter Anthropic API key',
        },
        openai: {
            displayName: 'OpenAI / OpenAI-compatible',
            baseUrl: 'https://api.openai.com/v1',
            modelHint: 'gpt-4.1-mini',
            apiKeyPlaceholder: 'Enter OpenAI API key',
        },
        copilot: {
            displayName: 'GitHub Copilot',
            baseUrl: 'https://api.githubcopilot.com',
            modelHint: 'gpt-4o-mini',
            apiKeyPlaceholder: 'Enter GitHub token',
        },
        gemini: {
            displayName: 'Google Gemini',
            baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
            modelHint: 'gemini-2.5-pro',
            apiKeyPlaceholder: 'Enter Gemini API key',
        },
        grok: {
            displayName: 'xAI Grok',
            baseUrl: 'https://api.x.ai/v1',
            modelHint: 'grok-3-mini',
            apiKeyPlaceholder: 'Enter xAI API key',
        },
    };

    function getProviderDefaults(provider) {
        return PROVIDER_DEFAULTS[String(provider || 'anthropic').trim()] || PROVIDER_DEFAULTS.anthropic;
    }

    function applyProviderFormHints(provider, { preserveBaseUrl = true } = {}) {
        const providerConfig = getProviderDefaults(provider);
        const modelEl = document.getElementById('plugin-ai-model');
        const apiKeyEl = document.getElementById('plugin-ai-api-key');
        const baseUrlEl = document.getElementById('plugin-ai-base-url');
        const apiKeySavedHintEl = document.getElementById('plugin-ai-api-key-saved-hint');
        if (modelEl) {
            modelEl.placeholder = `Type model name and press Enter — e.g. ${providerConfig.modelHint}`;
        }
        if (apiKeyEl) {
            const currentPlaceholder = String(apiKeyEl.dataset.savedPlaceholder || '').trim();
            apiKeyEl.placeholder = currentPlaceholder || providerConfig.apiKeyPlaceholder;
        }
        if (apiKeySavedHintEl) {
            const currentHint = String(apiKeySavedHintEl.dataset.savedHint || '').trim();
            apiKeySavedHintEl.textContent = currentHint;
            apiKeySavedHintEl.style.display = currentHint ? 'block' : 'none';
        }
        if (baseUrlEl) {
            baseUrlEl.placeholder = `${providerConfig.baseUrl} or local compatible endpoint`;
            const current = String(baseUrlEl.value || '').trim();
            if (!preserveBaseUrl || !current) {
                baseUrlEl.value = current;
            }
        }
    }

    function getAiSettingsState() {
        window.aiSettingsViewState = window.aiSettingsViewState || {
            dashboard: null,
            selectedProfileKey: null,
            loading: false,
            testStatusByProfile: loadPersistedTestStatuses(),
            draftModels: [],
        };
        return window.aiSettingsViewState;
    }

    function loadPersistedTestStatuses() {
        try {
            const raw = window.localStorage?.getItem(AI_SETTINGS_STATUS_STORAGE_KEY);
            const parsed = raw ? JSON.parse(raw) : {};
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (_) {
            return {};
        }
    }

    function persistTestStatuses() {
        try {
            window.localStorage?.setItem(
                AI_SETTINGS_STATUS_STORAGE_KEY,
                JSON.stringify(getAiSettingsState().testStatusByProfile || {})
            );
        } catch (_) {
            // Ignore storage errors.
        }
    }

    function setProfileTestStatus(profileKey, entry) {
        const key = String(profileKey || '').trim();
        if (!key) return;
        const state = getAiSettingsState();
        state.testStatusByProfile = state.testStatusByProfile || {};
        state.testStatusByProfile[key] = entry;
        persistTestStatuses();
    }

    function deleteProfileTestStatus(profileKey) {
        const key = String(profileKey || '').trim();
        if (!key) return;
        const state = getAiSettingsState();
        if (state.testStatusByProfile && Object.prototype.hasOwnProperty.call(state.testStatusByProfile, key)) {
            delete state.testStatusByProfile[key];
            persistTestStatuses();
        }
    }

    function prunePersistedTestStatuses() {
        const validKeys = new Set(getProfileList().map((item) => String(item.profile_key || '')).filter(Boolean));
        const state = getAiSettingsState();
        const entries = state.testStatusByProfile || {};
        let changed = false;
        for (const key of Object.keys(entries)) {
            if (!validKeys.has(key)) {
                delete entries[key];
                changed = true;
            }
        }
        if (changed) persistTestStatuses();
    }

    function getProfileList() {
        return Array.isArray(getAiSettingsState().dashboard?.profiles)
            ? getAiSettingsState().dashboard.profiles
            : [];
    }

    function getProfileByKey(profileKey) {
        return getProfileList().find((item) => String(item.profile_key || '') === String(profileKey || '')) || null;
    }

    function getDraftModels() {
        return Array.isArray(getAiSettingsState().draftModels) ? getAiSettingsState().draftModels : [];
    }

    function setDraftModels(models = []) {
        const unique = [];
        for (const item of models) {
            const value = String(item || '').trim();
            if (!value || unique.includes(value)) continue;
            unique.push(value);
        }
        getAiSettingsState().draftModels = unique;
        renderModelChips();
    }

    function addDraftModel(model) {
        const value = String(model || '').trim();
        if (!value) return;
        setDraftModels([...getDraftModels(), value]);
    }

    function removeDraftModel(model) {
        const value = String(model || '').trim();
        setDraftModels(getDraftModels().filter((item) => item !== value));
    }

    function renderModelChips() {
        const container = document.getElementById('ai-settings-model-chips');
        if (!container) return;
        const models = getDraftModels();
        container.innerHTML = models.map((model) => `
            <span class="ai-settings-model-chip">
                <span>${escapeHtml(model)}</span>
                <button type="button" data-model-remove="${escapeHtml(model)}" aria-label="Remove model">×</button>
            </span>
        `).join('');
    }

    function maskApiKeyForTable(value) {
        const raw = String(value || '').trim();
        if (!raw) return 'No key saved';
        if (raw.length <= 8) return `${raw.slice(0, 2)}••••${raw.slice(-2)}`;
        return `${raw.slice(0, 6)}••••••${raw.slice(-4)}`;
    }

    function renderApiKeySummary(profile) {
        if (profile?.api_key_masked) return String(profile.api_key_masked);
        if (profile?.has_api_key) return 'Saved';
        return 'No key saved';
    }

    function getSavedApiKeyPlaceholder(profile) {
        const providerConfig = getProviderDefaults(profile?.provider);
        return profile?.has_api_key
            ? 'Saved API key will be kept unless you enter a new one'
            : providerConfig.apiKeyPlaceholder;
    }

    function getSavedApiKeyHint(profile) {
        if (!profile?.has_api_key) return '';
        const masked = String(profile?.api_key_masked || '').trim();
        return masked
            ? `Saved key: ${masked}. Enter a new key only if you want to replace it.`
            : 'A saved API key already exists. Enter a new key only if you want to replace it.';
    }

    function renderAiSettingsDashboard() {
        const state = getAiSettingsState();
        const dashboard = state.dashboard || { profiles: [], stats: {} };

        const table = document.getElementById('ai-settings-profiles-table');
        const empty = document.getElementById('ai-settings-profiles-empty');
        const tbody = document.getElementById('ai-settings-profiles-list');
        if (!table || !empty || !tbody) return;

        const profiles = Array.isArray(dashboard.profiles) ? dashboard.profiles : [];
        if (!profiles.length) {
            table.style.display = 'none';
            empty.style.display = 'block';
            tbody.innerHTML = '';
            return;
        }

        empty.style.display = 'none';
        table.style.display = 'table';
        tbody.innerHTML = profiles.map((profile) => {
            const isSelected = String(profile.profile_key || '') === String(state.selectedProfileKey || '');
            const profileKey = String(profile.profile_key || '');
            const statusEntry = state.testStatusByProfile?.[profileKey] || null;
            const chipTone = statusEntry?.tone === 'success'
                ? 'is-active'
                : statusEntry?.tone === 'error'
                    ? 'is-error'
                    : '';
            const chipLabel = statusEntry?.label || 'Not tested';
            const models = Array.isArray(profile.models) && profile.models.length ? profile.models.join(', ') : String(profile.model || '—');
            return `
                <tr data-profile-key="${escapeHtml(profileKey)}" class="${isSelected ? 'is-active' : ''}">
                    <td>
                        <div class="ai-profile-name">
                            <strong>${escapeHtml(String(profile.display_name || 'Untitled profile'))}</strong>
                            <span>${escapeHtml(renderApiKeySummary(profile))}</span>
                        </div>
                    </td>
                    <td>${escapeHtml(String(profile.provider_label || profile.provider || '—'))}</td>
                    <td>${escapeHtml(models)}</td>
                    <td><span class="ai-profile-chip ${chipTone}">${escapeHtml(chipLabel)}</span></td>
                </tr>
            `;
        }).join('');
    }

    function fillAiSettingsForm(profile = null) {
        const providerEl = document.getElementById('plugin-ai-provider');
        const modelEl = document.getElementById('plugin-ai-model');
        const nameEl = document.getElementById('plugin-ai-display-name');
        const apiKeyEl = document.getElementById('plugin-ai-api-key');
        const apiKeySavedHintEl = document.getElementById('plugin-ai-api-key-saved-hint');
        const apiKeyToggle = document.getElementById('plugin-ai-api-key-toggle');
        const baseUrlEl = document.getElementById('plugin-ai-base-url');
        const models = Array.isArray(profile?.models) && profile.models.length
            ? profile.models
            : (profile?.model ? [String(profile.model)] : []);
        const provider = String(profile?.provider || 'anthropic');
        if (providerEl) providerEl.value = provider;
        if (modelEl) modelEl.value = '';
        if (nameEl) nameEl.value = String(profile?.display_name || '');
        if (apiKeyEl) {
            apiKeyEl.value = '';
            apiKeyEl.dataset.savedPlaceholder = getSavedApiKeyPlaceholder(profile);
            apiKeyEl.placeholder = apiKeyEl.dataset.savedPlaceholder;
            apiKeyEl.type = 'password';
        }
        if (apiKeyToggle) {
            apiKeyToggle.setAttribute('aria-pressed', 'false');
            apiKeyToggle.setAttribute('title', 'Show API key');
            apiKeyToggle.setAttribute('aria-label', 'Show API key');
        }
        if (apiKeySavedHintEl) {
            const savedHint = getSavedApiKeyHint(profile);
            apiKeySavedHintEl.dataset.savedHint = savedHint;
            apiKeySavedHintEl.textContent = savedHint;
            apiKeySavedHintEl.style.display = savedHint ? 'block' : 'none';
        }
        if (baseUrlEl) baseUrlEl.value = String(profile?.base_url || '');
        setDraftModels(models);
        applyProviderFormHints(provider, { preserveBaseUrl: true });
    }

    function collectAiSettingsPayload() {
        const models = getDraftModels();
        return {
            profile_key: getAiSettingsState().selectedProfileKey || undefined,
            display_name: String(document.getElementById('plugin-ai-display-name')?.value || '').trim() || undefined,
            provider: String(document.getElementById('plugin-ai-provider')?.value || 'anthropic').trim(),
            model: String(models[0] || '').trim(),
            models,
            api_key: String(document.getElementById('plugin-ai-api-key')?.value || '').trim() || undefined,
            base_url: String(document.getElementById('plugin-ai-base-url')?.value || '').trim() || null,
            is_active: false,
        };
    }

    function validateAiSettingsPayload(payload, { requireApiKey = false } = {}) {
        if (!Array.isArray(payload.models) || payload.models.length === 0) return 'At least one model is required.';
        if (!payload.model) return 'Provider model is required.';
        if (requireApiKey && !payload.api_key && payload.provider !== 'copilot') return 'API key is required for this action.';
        const existing = payload.profile_key ? getProfileByKey(payload.profile_key) : null;
        const currentValue = String(payload.api_key || '').trim();
        const savedValue = String(existing?.api_key_masked || '').trim();
        const hasNewVisibleKey = currentValue && currentValue !== savedValue;
        if (!hasNewVisibleKey && !existing?.has_api_key && payload.provider !== 'copilot') {
            return 'API key is required for the first save.';
        }
        return null;
    }

    async function fetchAiSettingsDashboard() {
        const response = await fetch('/api/ai/settings');
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        return data;
    }

    async function loadAiSettingsDashboard() {
        const state = getAiSettingsState();
        if (state.loading) return;
        state.loading = true;
        try {
            const dashboard = await fetchAiSettingsDashboard();
            state.dashboard = dashboard;
            prunePersistedTestStatuses();
            const desiredKey = state.selectedProfileKey || dashboard?.profiles?.[0]?.profile_key || dashboard?.active_profile?.profile_key || null;
            state.selectedProfileKey = desiredKey;
            renderAiSettingsDashboard();
            fillAiSettingsForm(getProfileByKey(desiredKey) || dashboard?.active_profile || null);
        } catch (error) {
            showToast(`Failed to load AI settings: ${error.message}`, 'error');
        } finally {
            state.loading = false;
        }
    }

    async function saveAiSettingsProfile(event) {
        event.preventDefault();
        const payload = collectAiSettingsPayload();
        const validationError = validateAiSettingsPayload(payload);
        if (validationError) {
            showToast(validationError, 'warn');
            return;
        }

        const existing = payload.profile_key ? getProfileByKey(payload.profile_key) : null;
        if (existing && payload.api_key === existing.api_key) {
            delete payload.api_key;
        }

        try {
            const response = await fetch('/api/ai/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

            const state = getAiSettingsState();
            state.selectedProfileKey = data.profile_key || payload.profile_key || null;
            setProfileTestStatus(state.selectedProfileKey, { label: 'Testing...', tone: '' });
            await loadAiSettingsDashboard();
            showToast('AI profile saved.', 'success');
            await testAiSettingsConnection({ silentSuccessToast: true });
        } catch (error) {
            showToast(`Failed to save AI settings: ${error.message}`, 'error');
        }
    }

    async function testAiSettingsConnection(options = {}) {
        const payload = collectAiSettingsPayload();
        const validationError = validateAiSettingsPayload(payload, { requireApiKey: false });
        const state = getAiSettingsState();
        const profileKey = String(payload.profile_key || state.selectedProfileKey || '').trim();
        const existing = payload.profile_key ? getProfileByKey(payload.profile_key) : null;
        if (existing && payload.api_key === existing.api_key) {
            delete payload.api_key;
        }

        if (validationError) {
            if (profileKey) {
                setProfileTestStatus(profileKey, { label: 'Failed', tone: 'error' });
                renderAiSettingsDashboard();
            }
            if (!options.silentValidationToast) showToast(validationError, 'warn');
            return false;
        }

        if (profileKey) {
            setProfileTestStatus(profileKey, { label: 'Testing...', tone: '' });
            renderAiSettingsDashboard();
        }

        try {
            const response = await fetch('/api/ai/settings/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
            const resolvedKey = String(data.profile_key || profileKey || '').trim();
            if (resolvedKey) {
                setProfileTestStatus(resolvedKey, { label: 'Success', tone: 'success' });
                if (resolvedKey !== profileKey) deleteProfileTestStatus(profileKey);
                renderAiSettingsDashboard();
            }
            if (!options.silentSuccessToast) showToast('AI connection test passed.', 'success');
            return true;
        } catch (error) {
            if (profileKey) {
                setProfileTestStatus(profileKey, { label: 'Failed', tone: 'error' });
                renderAiSettingsDashboard();
            }
            if (!options.silentErrorToast) showToast(`AI connection test failed: ${error.message}`, 'error');
            return false;
        }
    }

    function selectAiSettingsProfile(profileKey) {
        const state = getAiSettingsState();
        state.selectedProfileKey = profileKey;
        renderAiSettingsDashboard();
        fillAiSettingsForm(getProfileByKey(profileKey));
    }

    function bindAiSettingsEvents() {
        const list = document.getElementById('ai-settings-profiles-list');
        if (list && !list.dataset.bound) {
            list.addEventListener('click', (event) => {
                const row = event.target.closest('[data-profile-key]');
                if (!row) return;
                selectAiSettingsProfile(row.getAttribute('data-profile-key'));
            });
            list.dataset.bound = '1';
        }

        const modelChips = document.getElementById('ai-settings-model-chips');
        if (modelChips && !modelChips.dataset.bound) {
            modelChips.addEventListener('click', (event) => {
                const button = event.target.closest('[data-model-remove]');
                if (!button) return;
                removeDraftModel(button.getAttribute('data-model-remove'));
            });
            modelChips.dataset.bound = '1';
        }

        const form = document.getElementById('plugin-ai-settings-form');
        if (form && !form.dataset.bound) {
            form.addEventListener('submit', saveAiSettingsProfile);
            form.dataset.bound = '1';
        }

        const newBtn = document.getElementById('ai-settings-new-profile-btn');
        if (newBtn && !newBtn.dataset.bound) {
            newBtn.addEventListener('click', () => {
                getAiSettingsState().selectedProfileKey = null;
                fillAiSettingsForm(null);
                renderAiSettingsDashboard();
            });
            newBtn.dataset.bound = '1';
        }

        const providerEl = document.getElementById('plugin-ai-provider');
        if (providerEl && !providerEl.dataset.bound) {
            providerEl.addEventListener('change', () => {
                applyProviderFormHints(providerEl.value, { preserveBaseUrl: true });
                renderModelChips();
            });
            providerEl.dataset.bound = '1';
        }

        const modelEl = document.getElementById('plugin-ai-model');
        if (modelEl && !modelEl.dataset.bound) {
            modelEl.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                const value = String(modelEl.value || '').trim();
                if (!value) return;
                addDraftModel(value);
                modelEl.value = '';
            });
            modelEl.dataset.bound = '1';
        }

        const apiKeyToggle = document.getElementById('plugin-ai-api-key-toggle');
        if (apiKeyToggle && !apiKeyToggle.dataset.bound) {
            apiKeyToggle.addEventListener('click', () => {
                const input = document.getElementById('plugin-ai-api-key');
                if (!input) return;
                const shouldReveal = input.type === 'password';
                input.type = shouldReveal ? 'text' : 'password';
                apiKeyToggle.setAttribute('aria-pressed', shouldReveal ? 'true' : 'false');
                apiKeyToggle.setAttribute('title', shouldReveal ? 'Hide API key' : 'Show API key');
                apiKeyToggle.setAttribute('aria-label', shouldReveal ? 'Hide API key' : 'Show API key');
            });
            apiKeyToggle.dataset.bound = '1';
        }

        const advancedToggle = document.getElementById('plugin-ai-advanced-toggle');
        const advancedPanel = document.getElementById('plugin-ai-advanced-panel');
        const runtimeStrategyChip = document.getElementById('plugin-ai-runtime-strategy-chip');
        const runtimeApprovalChip = document.getElementById('plugin-ai-runtime-approval-chip');
        const strategySelect = document.getElementById('plugin-ai-strategy');
        const approvalSelect = document.getElementById('plugin-ai-approval-mode');
        const runtimeFieldIds = [
            'plugin-ai-strategy',
            'plugin-ai-loop-mode',
            'plugin-ai-trace-enabled',
            'plugin-ai-structured-enabled',
            'plugin-ai-output-schema',
            'plugin-ai-tasks-json',
            'plugin-ai-approval-mode',
            'plugin-ai-retry-preset',
            'plugin-ai-fanout-json',
            'plugin-ai-before-run-json',
            'plugin-ai-after-run-json',
        ];
        const chatColumn = document.querySelector('.plugin-ai-chat-column');
        if (typeof window.hydratePluginAiRuntimePrefs === 'function') {
            window.hydratePluginAiRuntimePrefs();
        }
        if (typeof window.refreshPluginAiRuntimeSummary === 'function') {
            window.refreshPluginAiRuntimeSummary();
        }
        if (runtimeStrategyChip && !runtimeStrategyChip.dataset.bound) {
            runtimeStrategyChip.addEventListener('click', () => {
                if (typeof window.cyclePluginAiStrategy === 'function') {
                    window.cyclePluginAiStrategy();
                }
            });
            runtimeStrategyChip.dataset.bound = '1';
        }
        if (runtimeApprovalChip && !runtimeApprovalChip.dataset.bound) {
            runtimeApprovalChip.addEventListener('click', () => {
                if (typeof window.cyclePluginAiApprovalMode === 'function') {
                    window.cyclePluginAiApprovalMode();
                }
            });
            runtimeApprovalChip.dataset.bound = '1';
        }
        [strategySelect, approvalSelect].forEach((element) => {
            if (!element || element.dataset.summaryBound === '1') return;
            element.addEventListener('change', () => {
                if (typeof window.syncPluginAiApprovalModeUi === 'function') {
                    window.syncPluginAiApprovalModeUi();
                }
                if (typeof window.persistPluginAiRuntimePrefs === 'function') {
                    window.persistPluginAiRuntimePrefs();
                }
                if (typeof window.refreshPluginAiRuntimeSummary === 'function') {
                    window.refreshPluginAiRuntimeSummary();
                }
            });
            element.dataset.summaryBound = '1';
        });
        runtimeFieldIds.forEach((fieldId) => {
            const element = document.getElementById(fieldId);
            if (!element || element.dataset.runtimePersistBound === '1') return;
            const eventName = element.tagName === 'TEXTAREA' || element.type === 'text' ? 'input' : 'change';
            element.addEventListener(eventName, () => {
                if (typeof window.persistPluginAiRuntimePrefs === 'function') {
                    window.persistPluginAiRuntimePrefs();
                }
                if (typeof window.refreshPluginAiRuntimeSummary === 'function') {
                    window.refreshPluginAiRuntimeSummary();
                }
            });
            element.dataset.runtimePersistBound = '1';
        });
        if (advancedToggle && advancedPanel && !advancedToggle.dataset.bound) {
            if (chatColumn) {
                chatColumn.classList.toggle('is-advanced-open', !advancedPanel.hasAttribute('hidden'));
            }
            advancedToggle.addEventListener('click', () => {
                const nextExpanded = advancedPanel.hasAttribute('hidden');
                if (nextExpanded) {
                    advancedPanel.removeAttribute('hidden');
                } else {
                    advancedPanel.setAttribute('hidden', 'hidden');
                }
                if (chatColumn) {
                    chatColumn.classList.toggle('is-advanced-open', nextExpanded);
                }
                advancedToggle.setAttribute('aria-expanded', nextExpanded ? 'true' : 'false');
                if (typeof window.refreshPluginAiRuntimeSummary === 'function') {
                    window.refreshPluginAiRuntimeSummary();
                }
            });
            advancedToggle.dataset.bound = '1';
        }
    }

    window.loadAiSettingsDashboard = loadAiSettingsDashboard;
    window.bindAiSettingsEvents = bindAiSettingsEvents;
})();
