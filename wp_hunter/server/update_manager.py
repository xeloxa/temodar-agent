"""
Automatic updater for the WP-Hunter dashboard.

Downloads the latest GitHub release, copies the files over the current
installation, and refreshes dependencies. Designed to be triggered through
the dashboard so security researchers can keep the local UI up to date.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from wp_hunter import __version__

logger = logging.getLogger("wp_hunter.update")


class UpdateManager:
    RELEASE_API_URL = "https://api.github.com/repos/xeloxa/wp-hunter/releases/latest"
    CHECK_INTERVAL = timedelta(minutes=30)
    DEPLOY_EXCLUDE_DIRS = {".git", "venv", "__pycache__", "sessions", "semgrep_results"}
    DEPLOY_EXCLUDE_FILES = {"wp_hunter.log", "wp_hunter.db"}
    STATE_FILE_NAME = "update_state.json"

    def __init__(self) -> None:
        self._cache: Optional[Dict] = None
        self._cache_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self._in_progress = False
        self._progress_message: str = ""
        self._last_error: Optional[str] = None
        self._last_update_message: Optional[str] = None

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def state_file(self) -> Path:
        state_dir = Path.home() / ".wp-hunter"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / self.STATE_FILE_NAME

    def _load_state(self) -> Dict[str, str]:
        try:
            if not self.state_file.exists():
                return {}
            with self.state_file.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                return {}
            return {
                str(key): str(value)
                for key, value in raw.items()
                if isinstance(value, str)
            }
        except Exception:
            logger.warning("Failed to load updater state file.", exc_info=True)
            return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        try:
            with self.state_file.open("w", encoding="utf-8") as handle:
                json.dump(state, handle)
        except Exception:
            logger.warning("Failed to persist updater state file.", exc_info=True)

    def _set_installed_release_tag(self, tag_name: str) -> None:
        normalized = (tag_name or "").strip()
        if not normalized:
            return
        state = self._load_state()
        state["installed_release_tag"] = normalized
        state["installed_at"] = datetime.utcnow().isoformat() + "Z"
        self._save_state(state)

    def _normalized_version(self, version: Optional[str]) -> Tuple[int, ...]:
        if not version:
            return ()
        cleaned = version.strip().lstrip("vV")
        parts = cleaned.replace("-", ".").replace("_", ".").split(".")
        nums: List[int] = []
        for part in parts:
            digits = "".join(ch for ch in part if ch.isdigit())
            if digits:
                nums.append(int(digits))
            else:
                nums.append(0)
        return tuple(nums)

    def _is_newer_release(self, latest_version: Optional[str]) -> bool:
        current_tuple = self._normalized_version(__version__)
        latest_tuple = self._normalized_version(latest_version)
        if not latest_tuple:
            return False
        length = max(len(current_tuple), len(latest_tuple))
        current_tuple += (0,) * (length - len(current_tuple))
        latest_tuple += (0,) * (length - len(latest_tuple))
        return latest_tuple > current_tuple

    def _release_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": "WP-Hunter Update Agent",
        }

    def _download_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "WP-Hunter Update Agent",
        }

    def _fetch_release(self, force: bool = False) -> Dict:
        with self._lock:
            now = datetime.utcnow()
            if (
                not force
                and self._cache
                and self._cache_time
                and (now - self._cache_time) < self.CHECK_INTERVAL
            ):
                return self._cache
        response = requests.get(
            self.RELEASE_API_URL,
            headers=self._release_headers(),
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        release_info = self._build_release_payload(payload)
        with self._lock:
            self._cache = release_info
            self._cache_time = now
        return release_info

    def _build_release_payload(self, data: Dict) -> Dict:
        assets = data.get("assets") or []
        asset = self._choose_asset(assets, data.get("zipball_url"))
        download_url = data.get("zipball_url") or asset.get("browser_download_url") or asset.get("url")
        return {
            "tag_name": data.get("tag_name"),
            "name": data.get("name") or data.get("tag_name"),
            "body": data.get("body") or "",
            "published_at": data.get("published_at"),
            "html_url": data.get("html_url"),
            "zipball_url": data.get("zipball_url"),
            "asset_name": asset.get("name"),
            "asset_size": asset.get("size"),
            "asset_url": asset.get("browser_download_url") or asset.get("url"),
            "download_url": download_url,
            "update_available": self._is_newer_release(data.get("tag_name")),
        }

    def _choose_asset(self, assets: list, fallback_url: Optional[str]) -> Dict:
        if assets:
            preferred = next((a for a in assets if str(a.get("name", "")).lower().endswith(".zip")), None)
            chosen = preferred or assets[0]
            return {
                "name": chosen.get("name"),
                "size": chosen.get("size"),
                "browser_download_url": chosen.get("browser_download_url"),
                "url": chosen.get("url"),
            }
        return {
            "name": (fallback_url and Path(urlparse(fallback_url).path).name) or "source-archive",
            "size": None,
            "browser_download_url": fallback_url,
            "url": fallback_url,
        }

    def _set_progress(self, message: str) -> None:
        with self._lock:
            self._progress_message = message
        logger.debug("Update progress: %s", message)

    def _download_asset(self, url: str) -> Path:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix or ".zip"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self._set_progress("Downloading release asset…")
        with requests.get(url, headers=self._download_headers(), stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
        return Path(temp_path)

    def _extract_archive(self, archive_path: Path) -> Tuple[Path, Path]:
        extract_root = Path(tempfile.mkdtemp(prefix="wp-hunter-update-"))
        if zipfile.is_zipfile(archive_path):
            shutil.unpack_archive(str(archive_path), str(extract_root), format="zip")
        else:
            shutil.unpack_archive(str(archive_path), str(extract_root))
        entries = [child for child in extract_root.iterdir() if child.is_dir()]
        release_root = entries[0] if len(entries) == 1 else extract_root
        return release_root, extract_root

    def _deploy_release(self, release_root: Path) -> None:
        if not (release_root / "wp_hunter").exists():
            raise RuntimeError("Release archive does not contain expected project files.")

        copied_entries = 0
        for child in release_root.iterdir():
            if child.name in self.DEPLOY_EXCLUDE_DIRS or child.name in self.DEPLOY_EXCLUDE_FILES:
                continue
            dest = self.project_root / child.name
            if child.is_dir():
                shutil.copytree(
                    child,
                    dest,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*self.DEPLOY_EXCLUDE_DIRS, *self.DEPLOY_EXCLUDE_FILES),
                )
                copied_entries += 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, dest)
                copied_entries += 1
        if copied_entries == 0:
            raise RuntimeError("Release archive had no deployable files.")
        self._last_update_message = "Release files copied. Please restart the dashboard."

    def _install_dependencies(self) -> None:
        requirements = self.project_root / "requirements.txt"
        if not requirements.exists():
            return
        self._set_progress("Installing Python dependencies…")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Dependency installation failed:\n"
                f"{result.stdout.strip()}\n"
                f"{result.stderr.strip()}"
            )
        self._set_progress("Dependencies installed.")

    def get_status(self, force: bool = False) -> Dict:
        release = None
        try:
            release = self._fetch_release(force)
            self._last_error = None
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Unable to refresh release info: %s", exc)
            if not self._cache:
                raise
            release = self._cache
        with self._lock:
            in_progress = self._in_progress
            progress_message = self._progress_message
            last_error = self._last_error
            last_update = self._last_update_message
        state = self._load_state()
        installed_tag = state.get("installed_release_tag")
        latest_tag = release.get("tag_name")
        already_installed = bool(
            installed_tag
            and latest_tag
            and self._normalized_version(installed_tag) == self._normalized_version(latest_tag)
        )
        update_available = bool(release.get("update_available")) and not already_installed
        status = {
            "current_version": __version__,
            "latest_version": release.get("tag_name"),
            "release_name": release.get("name"),
            "release_notes": release.get("body"),
            "release_url": release.get("html_url"),
            "release_published_at": release.get("published_at"),
            "asset_name": release.get("asset_name"),
            "asset_size": release.get("asset_size"),
            "asset_url": release.get("asset_url"),
            "download_url": release.get("download_url"),
            "zipball_url": release.get("zipball_url"),
            "update_available": update_available,
            "already_installed_release": already_installed,
            "installed_release_tag": installed_tag,
            "checked_at": (self._cache_time.isoformat() + "Z") if self._cache_time else None,
            "in_progress": in_progress,
            "progress_message": progress_message,
            "last_error": last_error,
            "last_update_message": last_update,
        }
        return status

    def start_update(self) -> str:
        with self._lock:
            if self._in_progress:
                raise RuntimeError("An update is already running")
            self._in_progress = True
            self._progress_message = "Preparing update…"
            self._last_error = None
        try:
            release_status = self.get_status(force=True)
            if not release_status.get("update_available"):
                raise RuntimeError("No newer release is available right now.")
            download_url = release_status.get("download_url") or release_status.get("asset_url")
            if not download_url:
                raise RuntimeError("Release does not expose a downloadable asset.")
            latest_tag = release_status.get("latest_version") or ""
            thread = threading.Thread(
                target=self._run_update,
                args=(download_url, latest_tag),
                daemon=True,
            )
            thread.start()
            return "Update download has begun."
        except Exception:
            with self._lock:
                self._in_progress = False
                self._progress_message = ""
            raise

    def _run_update(self, asset_url: str, latest_tag: str) -> None:
        archive_path: Optional[Path] = None
        extract_dir: Optional[Path] = None
        try:
            archive_path = self._download_asset(asset_url)
            self._set_progress("Extracting files…")
            release_root, extract_dir = self._extract_archive(archive_path)
            self._set_progress("Applying release files…")
            self._deploy_release(release_root)
            self._install_dependencies()
            self._set_installed_release_tag(latest_tag)
            self._last_update_message = "Update complete. Restart the dashboard to pick up the new version."
            self._last_error = None
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Automatic update failed")
        finally:
            with self._lock:
                self._in_progress = False
                self._progress_message = ""
            if archive_path and archive_path.exists():
                archive_path.unlink(missing_ok=True)
            if extract_dir and extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)


manager = UpdateManager()
