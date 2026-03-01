# Parallel sync of WordPress.org plugin metadata to SQLite

import time
import threading
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

from wp_hunter.config import Colors
from wp_hunter.database.plugin_metadata import PluginMetadataRepository

print_lock = threading.Lock()
_sync_session: Optional[requests.Session] = None


# DoS Prevention: Maximum connection pool size
MAX_POOL_SIZE = 50


def get_sync_session(pool_size: int = 100) -> requests.Session:
    global _sync_session
    if _sync_session is None:
        # Limit pool size to prevent resource exhaustion
        safe_pool_size = min(pool_size, MAX_POOL_SIZE)
        _sync_session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=safe_pool_size, pool_maxsize=safe_pool_size, max_retries=3
        )
        _sync_session.mount("https://", adapter)
        _sync_session.mount("http://", adapter)
    return _sync_session


def close_sync_session():
    global _sync_session
    if _sync_session:
        _sync_session.close()
        _sync_session = None


@dataclass
class SyncConfig:
    pages: int = 100
    browse_type: str = "updated"
    workers: int = 10
    rate_limit_delay: float = 0.1


@dataclass
class SyncProgress:
    pages_completed: int = 0
    pages_total: int = 0
    plugins_synced: int = 0
    plugins_failed: int = 0
    current_page: int = 0
    is_running: bool = False
    error: Optional[str] = None


class PluginSyncer:
    def __init__(
        self,
        config: Optional[SyncConfig] = None,
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
        on_page_complete: Optional[Callable[[int, int], None]] = None,
        last_sync_time: Optional[str] = None,
    ):
        self.config = config or SyncConfig()
        self.on_progress = on_progress
        self.on_page_complete = on_page_complete
        self.last_sync_time = last_sync_time
        self.progress = SyncProgress()
        self.stop_event = threading.Event()
        self.repository = PluginMetadataRepository()

    def fetch_page(self, page: int) -> List[Dict[str, Any]]:
        session = get_sync_session(self.config.workers * 2)
        url = "https://api.wordpress.org/plugins/info/1.2/"
        params = {
            "action": "query_plugins",
            "request[browse]": self.config.browse_type,
            "request[page]": page,
            "request[per_page]": 100,
            "request[fields][active_installs]": True,
            "request[fields][short_description]": True,
            "request[fields][description]": True,
            "request[fields][last_updated]": True,
            "request[fields][download_link]": True,
            "request[fields][ratings]": True,
            "request[fields][num_ratings]": True,
            "request[fields][support_threads]": True,
            "request[fields][support_threads_resolved]": True,
            "request[fields][tested]": True,
            "request[fields][requires]": True,
            "request[fields][requires_php]": True,
            "request[fields][author]": True,
            "request[fields][author_profile]": True,
            "request[fields][contributors]": True,
            "request[fields][version]": True,
            "request[fields][tags]": True,
            "request[fields][sections]": True,
            "request[fields][donate_link]": True,
            "request[fields][homepage]": True,
            "request[fields][added]": True,
            "request[fields][downloaded]": True,
            "request[fields][banners]": True,
            "request[fields][icons]": True,
        }

        max_retries = 3
        for attempt in range(max_retries):
            if self.stop_event.is_set():
                return []

            try:
                response = session.get(url, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    return data.get("plugins", []) if data else []

                elif response.status_code == 429:
                    wait_time = 5 * (attempt + 1)
                    with print_lock:
                        print(
                            f"{Colors.YELLOW}[!] Rate limited on page {page}, waiting {wait_time}s...{Colors.RESET}"
                        )
                    time.sleep(wait_time)
                    continue

                else:
                    with print_lock:
                        print(
                            f"{Colors.RED}[!] API error {response.status_code} on page {page}{Colors.RESET}"
                        )
                    return []

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                with print_lock:
                    print(
                        f"{Colors.YELLOW}[!] Network error on page {page}: {e}, retrying...{Colors.RESET}"
                    )
                time.sleep(2 * (attempt + 1))
                continue
            except Exception as e:
                with print_lock:
                    print(
                        f"{Colors.RED}[!] Unexpected error on page {page}: {e}{Colors.RESET}"
                    )
                return []

        return []

    def _process_page(self, page: int) -> int:
        if self.stop_event.is_set():
            return 0

        plugins = self.fetch_page(page)

        if plugins:
            # Check for incremental sync stop condition
            if self.last_sync_time:
                filtered_plugins = []
                for p in plugins:
                    last_updated = p.get("last_updated", "")
                    # Simplified comparison (WP API uses 'YYYY-MM-DD HH:MM:SS' usually)
                    if last_updated and last_updated <= self.last_sync_time:
                        self.stop_event.set()  # Stop entire sync
                        break
                    filtered_plugins.append(p)
                plugins = filtered_plugins

            if not plugins:
                return 0

            saved = self.repository.bulk_upsert(plugins)
            self.progress.plugins_synced += saved
            return saved

        return 0

    def sync(self, verbose: bool = True) -> SyncProgress:
        self.progress = SyncProgress(pages_total=self.config.pages, is_running=True)

        sync_id = self.repository.record_sync_start(self.config.browse_type)

        if verbose:
            print(f"\n{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(f"{Colors.BOLD}🔄 Starting Plugin Metadata Sync{Colors.RESET}")
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(f"  📄 Pages to sync: {self.config.pages}")
            print(f"  🔀 Browse type: {self.config.browse_type}")
            print(f"  👷 Workers: {self.config.workers}")
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")

        pages_to_sync = list(range(1, self.config.pages + 1))
        completed_pages = 0

        try:
            with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
                # Submit all pages
                future_to_page = {
                    executor.submit(self._process_page, page): page
                    for page in pages_to_sync
                }

                for future in as_completed(future_to_page):
                    if self.stop_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    page = future_to_page[future]

                    try:
                        plugin_count = future.result()
                        completed_pages += 1
                        self.progress.pages_completed = completed_pages
                        self.progress.current_page = page

                        if verbose:
                            import sys

                            print(
                                f"  {Colors.GREEN}✓{Colors.RESET} Page {page} done ({plugin_count} plugins) [{completed_pages}/{self.config.pages}]"
                            )
                            sys.stdout.flush()

                        if self.on_page_complete:
                            self.on_page_complete(completed_pages, self.config.pages)

                        if self.on_progress:
                            self.on_progress(self.progress)

                    except Exception as e:
                        self.progress.plugins_failed += 1
                        with print_lock:
                            print(
                                f"{Colors.RED}[!] Error processing page {page}: {e}{Colors.RESET}"
                            )

                    # Small delay to avoid overwhelming API
                    if self.config.rate_limit_delay > 0:
                        time.sleep(self.config.rate_limit_delay)

            self.progress.is_running = False

            if verbose:
                print(f"\n{Colors.GREEN}{'=' * 60}{Colors.RESET}")
                print(f"{Colors.BOLD}✓ Sync Complete!{Colors.RESET}")
                print(f"  📄 Pages synced: {self.progress.pages_completed}")
                print(f"  📦 Plugins saved: {self.progress.plugins_synced}")
                if self.progress.plugins_failed > 0:
                    print(f"  ❌ Failed: {self.progress.plugins_failed}")
                print(f"{Colors.GREEN}{'=' * 60}{Colors.RESET}\n")

            self.repository.record_sync_complete(
                sync_id, self.progress.pages_completed, self.progress.plugins_synced
            )

        except Exception as e:
            self.progress.error = str(e)
            self.progress.is_running = False
            self.repository.record_sync_complete(
                sync_id, completed_pages, self.progress.plugins_synced, str(e)
            )

            if verbose:
                print(f"\n{Colors.RED}[!] Sync failed: {e}{Colors.RESET}")

        finally:
            close_sync_session()

        return self.progress

    def stop(self):
        self.stop_event.set()
