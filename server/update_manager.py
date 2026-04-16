"""
Release status manager for the Temodar Agent dashboard.

Checks for newer releases and provides manual helper commands for image-based
updates without mutating the host environment.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from app_meta import __version__, get_runtime_metadata

logger = logging.getLogger("temodar_agent.update")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ReleaseMetadataService:
    """Release metadata fetching, normalization, and validation."""

    def __init__(
        self,
        *,
        release_api_url: str,
        allowed_release_hosts: set[str],
    ) -> None:
        self.release_api_url = release_api_url
        self.allowed_release_hosts = allowed_release_hosts

    def normalized_version(self, version: Optional[str]) -> Tuple[int, ...]:
        if not version:
            return ()
        cleaned = version.strip().lstrip("vV")
        parts = cleaned.replace("-", ".").replace("_", ".").split(".")
        nums: List[int] = []
        for part in parts:
            digits = "".join(ch for ch in part if ch.isdigit())
            nums.append(int(digits) if digits else 0)
        return tuple(nums)

    def is_newer_release(self, current_version: Optional[str], latest_version: Optional[str]) -> bool:
        current_tuple = self.normalized_version(current_version)
        latest_tuple = self.normalized_version(latest_version)
        if not latest_tuple:
            return False
        length = max(len(current_tuple), len(latest_tuple))
        current_tuple += (0,) * (length - len(current_tuple))
        latest_tuple += (0,) * (length - len(latest_tuple))
        return latest_tuple > current_tuple

    def release_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Temodar Agent Update Agent",
        }

    def build_release_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        html_url = data.get("html_url")
        if html_url:
            parsed = urlparse(str(html_url))
            if parsed.hostname not in self.allowed_release_hosts:
                raise ValueError(f"Unsupported release URL host: {parsed.hostname}")
        return {
            "tag_name": data.get("tag_name"),
            "name": data.get("name") or data.get("tag_name"),
            "body": data.get("body") or "",
            "published_at": data.get("published_at"),
            "html_url": html_url,
        }

    def empty_release_payload(self) -> Dict[str, Any]:
        return {
            "tag_name": None,
            "name": None,
            "body": "",
            "published_at": None,
            "html_url": None,
            "update_available": False,
        }

    def fetch_release(self) -> Dict[str, Any]:
        parsed = urlparse(self.release_api_url)
        if parsed.hostname not in self.allowed_release_hosts:
            raise ValueError(f"Unsupported release API host: {parsed.hostname}")
        response = requests.get(
            self.release_api_url,
            headers=self.release_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return self.build_release_payload(response.json())


class UpdateManager:
    RELEASE_API_URL = "https://api.github.com/repos/xeloxa/temodar-agent/releases/latest"
    CHECK_INTERVAL = timedelta(minutes=30)
    ALLOWED_RELEASE_HOSTS = {
        "api.github.com",
        "github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
    HELPER_IMAGE = "xeloxa/temodar-agent:latest"
    HELPER_DATA_VOLUME = "temodar-agent-data"
    HELPER_PLUGINS_VOLUME = "temodar-agent-plugins"
    HELPER_SEMGREP_VOLUME = "temodar-agent-semgrep"
    HELPER_PORT = 8080
    MESSAGE_UP_TO_DATE = "Temodar Agent is already running the latest available release."
    MESSAGE_UPDATE_AVAILABLE = "A newer release is available. Pull the latest image and rerun the container manually."
    MESSAGE_DEGRADED = "Release information is temporarily unavailable. Version details may be incomplete right now."
    MESSAGE_MANUAL_UPDATE_ONLY = (
        "Automatic updates are no longer supported. Pull the latest image and rerun the container manually."
    )

    def __init__(self) -> None:
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._startup_auto_check_done = False
        self._release_metadata = ReleaseMetadataService(
            release_api_url=self.RELEASE_API_URL,
            allowed_release_hosts=self.ALLOWED_RELEASE_HOSTS,
        )

    def _runtime_metadata_payload(self) -> Dict[str, Any]:
        metadata = get_runtime_metadata()
        return {
            "current_version": metadata.current_version,
            "current_tag": metadata.current_tag,
            "build_id": metadata.build_id,
            "runtime_status": metadata.status,
        }

    def _fetch_release(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            now = utc_now()
            if (
                not force
                and self._cache
                and self._cache_time
                and (now - self._cache_time) < self.CHECK_INTERVAL
            ):
                return self._cache

        release_info = self._release_metadata.fetch_release()
        with self._lock:
            self._cache = release_info
            self._cache_time = now
        return release_info

    def _empty_release_payload(self) -> Dict[str, Any]:
        return self._release_metadata.empty_release_payload()

    def _resolve_release_for_status(self, force: bool) -> Dict[str, Any]:
        should_fetch = force
        if not force:
            with self._lock:
                if not self._startup_auto_check_done:
                    self._startup_auto_check_done = True
                    should_fetch = True

        if should_fetch:
            try:
                release = self._fetch_release(force)
                self._last_error = None
                return release
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Unable to refresh release info: %s", exc)
                with self._lock:
                    cached_release = self._cache
                if cached_release:
                    return cached_release
                return self._empty_release_payload()

        with self._lock:
            cached_release = self._cache
        if cached_release:
            return cached_release
        return self._empty_release_payload()

    def _build_manual_update_command(self) -> str:
        return (
            f"docker pull {self.HELPER_IMAGE}\n"
            f"docker rm -f temodar-agent >/dev/null 2>&1 || true\n"
            f"docker run -d --name temodar-agent -p {self.HELPER_PORT}:8080 "
            f"-v {self.HELPER_DATA_VOLUME}:/home/appuser/.temodar-agent "
            f"-v {self.HELPER_PLUGINS_VOLUME}:/app/Plugins "
            f"-v {self.HELPER_SEMGREP_VOLUME}:/app/semgrep_results "
            f"{self.HELPER_IMAGE}"
        )

    def _resolve_status_label(
        self,
        *,
        runtime_status: str,
        latest_version: Optional[str],
        update_available: bool,
        release_error: Optional[str],
    ) -> str:
        if runtime_status == "degraded":
            return "degraded"
        if release_error and not latest_version:
            return "degraded"
        if update_available:
            return "update_available"
        return "up_to_date"

    def _resolve_status_message(self, status_label: str, runtime_status: str) -> str:
        if status_label == "update_available":
            return self.MESSAGE_UPDATE_AVAILABLE
        if status_label == "degraded":
            if runtime_status == "degraded":
                return "Runtime version metadata is incomplete. Release information may be unreliable right now."
            return self.MESSAGE_DEGRADED
        return self.MESSAGE_UP_TO_DATE

    def _build_status_payload(self, release: Dict[str, Any]) -> Dict[str, Any]:
        runtime_metadata = self._runtime_metadata_payload()
        current_release_ref = runtime_metadata["current_tag"]
        if current_release_ref == "unknown":
            current_release_ref = runtime_metadata["current_version"]
        latest_version = release.get("tag_name")
        update_available = self._release_metadata.is_newer_release(current_release_ref, latest_version)
        checked_at = self._cache_time.isoformat().replace("+00:00", "Z") if self._cache_time else None
        status_label = self._resolve_status_label(
            runtime_status=runtime_metadata["runtime_status"],
            latest_version=latest_version,
            update_available=update_available,
            release_error=self._last_error,
        )
        helper_command = self._build_manual_update_command() if update_available else None

        return {
            "current_version": runtime_metadata["current_version"],
            "current_tag": runtime_metadata["current_tag"],
            "build_id": runtime_metadata["build_id"],
            "runtime_status": runtime_metadata["runtime_status"],
            "latest_version": latest_version,
            "release_name": release.get("name"),
            "release_notes": release.get("body"),
            "release_url": release.get("html_url"),
            "release_published_at": release.get("published_at"),
            "update_available": update_available,
            "status": status_label,
            "message": self._resolve_status_message(status_label, runtime_metadata["runtime_status"]),
            "update_command": helper_command,
            "manual_update_required": update_available,
            "manual_update_message": self.MESSAGE_MANUAL_UPDATE_ONLY if update_available else None,
            "checked_at": checked_at,
            "last_error": self._last_error,
        }

    def get_status(self, force: bool = False) -> Dict[str, Any]:
        release = self._resolve_release_for_status(force)
        return self._build_status_payload(release)

    def get_manual_update_payload(self) -> Dict[str, Any]:
        status = self.get_status(force=True)
        return {
            "status": status["status"],
            "message": self.MESSAGE_MANUAL_UPDATE_ONLY,
            "current_version": status["current_version"],
            "current_tag": status["current_tag"],
            "latest_version": status["latest_version"],
            "update_available": status["update_available"],
            "update_command": status["update_command"],
            "manual_update_required": status["manual_update_required"],
            "manual_update_only": True,
            "deprecated": True,
        }


manager = UpdateManager()
