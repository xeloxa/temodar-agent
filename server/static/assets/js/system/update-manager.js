(function() {
    const runtime = window.temodarAgentRuntime;

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

        if (data.latest_version && runtime.getAnnouncedUpdateVersion() !== data.latest_version) {
            runtime.setAnnouncedUpdateVersion(data.latest_version);
            showToast(
                `New release detected (${latestVersion}). Open the update card to install it.`,
                "warn"
            );
        }
        return;
    }

    if (sidebar) sidebar.classList.remove('has-update');
    runtime.setAnnouncedUpdateVersion("");
}

async function loadSystemStatus(force = false) {
    try {
        const url = `/api/system/update${force ? "?force=true" : ""}`;
        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error("Release check failed");
        }
        const data = await resp.json();
        runtime.setSystemStatus(data);
        renderSystemStatus(data);
    } catch (err) {
        console.error("System status refresh failed:", err);
        runtime.setSystemStatus(runtime.getSystemStatus() || null);
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

    const hasLatestVersion = !!(data.latest_version && String(data.latest_version).trim());
    if (data.update_available && hasLatestVersion) {
        if (updateCallout) updateCallout.hidden = false;
        if (updateVersion) {
            updateVersion.textContent = formatVersionLabel(data.latest_version) || "New release";
        }
        if (updateDescription) {
            updateDescription.textContent =
                truncateText(data.release_notes) ||
                data.message ||
                "Pull the latest image and rerun the container manually.";
        }
        if (releaseLink) {
            releaseLink.href = data.release_url || "#";
        }
        if (updateButton) {
            updateButton.disabled = false;
            updateButton.textContent = "COPY UPDATE COMMAND";
        }
    } else if (updateCallout) {
        updateCallout.hidden = true;
    }

    if (updateProgress) {
        updateProgress.hidden = true;
    }

    if (data.last_error && data.last_error !== runtime.getLastSystemErrorMessage()) {
        runtime.setLastSystemErrorMessage(data.last_error);
        showToast(`Update check failed: ${data.last_error}`, "warn");
    }

    if (
        data.last_update_message &&
        data.last_update_message !== runtime.getLastSystemUpdateMessage()
    ) {
        runtime.setLastSystemUpdateMessage(data.last_update_message);
        showToast(data.last_update_message, "success");
    }
}

function startSystemStatusPolling() {
    const activeTimer = runtime.getSystemStatusTimer();
    if (activeTimer) {
        clearInterval(activeTimer);
    }

    loadSystemStatus();
    runtime.setSystemStatusTimer(
        setInterval(() => loadSystemStatus(), runtime.getSystemPollInterval())
    );
}

async function initiateSystemUpdate() {
    const systemStatus = runtime.getSystemStatus();
    if (!systemStatus || !systemStatus.update_available) {
        showToast("No newer update is available right now.", "info");
        return;
    }

    const latestVersion =
        formatVersionLabel(systemStatus.latest_version) || "the latest release";
    const confirmMessage = `${latestVersion} is available. Temodar Agent no longer runs host-side update scripts automatically. Do you want to copy the manual Docker update command?`;
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
        const updateCommand = String(payload.update_command || "").trim();
        if (!updateCommand) {
            showToast(payload.message || "Manual update instructions are unavailable right now.", "info");
            return;
        }

        await navigator.clipboard.writeText(updateCommand);
        showToast(payload.message || "Manual Docker update command copied to clipboard.", "success");
        loadSystemStatus(true);
    } catch (err) {
        console.error("Failed to prepare update helper:", err);
        showToast(
            `Failed to prepare manual update instructions: ${err.message || "unknown error"}`,
            "error"
        );
    }
}

window.startSystemStatusPolling = startSystemStatusPolling;
window.initiateSystemUpdate = initiateSystemUpdate;
})();
