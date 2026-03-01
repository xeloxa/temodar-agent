"""
WP-Hunter SVN Downloader

Download WordPress plugins from SVN repository.
"""

import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Callable
from dataclasses import dataclass

from wp_hunter.config import Colors


# Thread-safe lock for console output
print_lock = threading.Lock()


@dataclass
class SVNDownloadResult:
    """Result of an SVN download operation."""

    slug: str
    success: bool
    path: Optional[str] = None
    error: Optional[str] = None


class SVNDownloader:
    """
    Download plugins from WordPress.org SVN repository.

    SVN URL format: https://plugins.svn.wordpress.org/{slug}/trunk/
    """

    SVN_BASE_URL = "https://plugins.svn.wordpress.org"

    def __init__(
        self,
        output_dir: str = "./Plugins_SVN",
        workers: int = 5,
        on_progress: Optional[Callable[[str, bool], None]] = None,
    ):
        self.output_dir = Path(output_dir)
        self.workers = workers
        self.on_progress = on_progress
        self.stop_event = threading.Event()

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _check_svn_available(self) -> bool:
        """Check if SVN is available on the system."""
        try:
            result = subprocess.run(
                ["svn", "--version"], capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _sanitize_slug(self, slug: str) -> str:
        """
        Sanitize plugin slug to prevent path traversal attacks.

        Only allows alphanumeric characters, hyphens, and underscores.
        """
        import re

        # Remove any path components (../, ./, etc.)
        safe_slug = Path(slug).name
        # Only allow safe characters
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "", safe_slug)
        if not safe_slug:
            raise ValueError(f"Invalid plugin slug: {slug}")
        return safe_slug

    def download_plugin(
        self, slug: str, version: str = "trunk", force: bool = False
    ) -> SVNDownloadResult:
        """
        Download a single plugin from SVN.

        Args:
            slug: Plugin slug
            version: Version to download (default: trunk, or tags/1.0.0)
            force: Force re-download even if exists
        """
        if self.stop_event.is_set():
            return SVNDownloadResult(slug=slug, success=False, error="Stopped")

        # Path Traversal Prevention: Sanitize slug
        try:
            safe_slug = self._sanitize_slug(slug)
        except ValueError as e:
            return SVNDownloadResult(slug=slug, success=False, error=str(e))

        plugin_dir = self.output_dir / safe_slug

        # Check if already exists
        if plugin_dir.exists() and not force:
            return SVNDownloadResult(
                slug=slug, success=True, path=str(plugin_dir), error="Already exists"
            )

        # Build SVN URL using sanitized slug
        if version == "trunk":
            svn_url = f"{self.SVN_BASE_URL}/{safe_slug}/trunk/"
        else:
            svn_url = f"{self.SVN_BASE_URL}/{safe_slug}/tags/{version}/"

        try:
            # Remove existing directory if force
            if plugin_dir.exists() and force:
                shutil.rmtree(plugin_dir)

            # SVN export (cleaner than checkout, no .svn folders)
            result = subprocess.run(
                ["svn", "export", "--quiet", svn_url, str(plugin_dir)],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
            )

            if result.returncode == 0:
                return SVNDownloadResult(slug=slug, success=True, path=str(plugin_dir))
            else:
                error_msg = (
                    result.stderr.strip() or f"SVN exit code: {result.returncode}"
                )
                return SVNDownloadResult(slug=slug, success=False, error=error_msg)

        except subprocess.TimeoutExpired:
            return SVNDownloadResult(slug=slug, success=False, error="Download timeout")
        except Exception as e:
            return SVNDownloadResult(slug=slug, success=False, error=str(e))

    def download_many(
        self,
        slugs: List[str],
        version: str = "trunk",
        force: bool = False,
        verbose: bool = True,
    ) -> List[SVNDownloadResult]:
        """
        Download multiple plugins in parallel.

        Args:
            slugs: List of plugin slugs
            version: Version to download for all
            force: Force re-download
            verbose: Print progress
        """
        if not self._check_svn_available():
            if verbose:
                print(
                    f"{Colors.RED}[!] SVN is not available. Please install subversion.{Colors.RESET}"
                )
                print(f"    Ubuntu/Debian: sudo apt-get install subversion")
                print(f"    macOS: brew install svn")
                print(f"    Windows: https://tortoisesvn.net/downloads.html")
            return []

        if verbose:
            print(f"\n{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(
                f"{Colors.BOLD}📥 Downloading {len(slugs)} plugins from SVN{Colors.RESET}"
            )
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(f"  📁 Output: {self.output_dir.absolute()}")
            print(f"  👷 Workers: {self.workers}")
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")

        results: List[SVNDownloadResult] = []
        completed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_slug = {
                executor.submit(self.download_plugin, slug, version, force): slug
                for slug in slugs
            }

            for future in as_completed(future_to_slug):
                if self.stop_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                slug = future_to_slug[future]
                completed += 1

                try:
                    result = future.result()
                    results.append(result)

                    if verbose:
                        if result.success:
                            status = f"{Colors.GREEN}✓{Colors.RESET}"
                            if result.error == "Already exists":
                                status = f"{Colors.YELLOW}≡{Colors.RESET}"
                        else:
                            status = f"{Colors.RED}✗{Colors.RESET}"

                        print(f"  [{completed}/{len(slugs)}] {status} {slug}")
                        if not result.success and result.error:
                            print(
                                f"           └─ {Colors.GRAY}{result.error}{Colors.RESET}"
                            )

                    if self.on_progress:
                        self.on_progress(slug, result.success)

                except Exception as e:
                    results.append(
                        SVNDownloadResult(slug=slug, success=False, error=str(e))
                    )
                    if verbose:
                        print(
                            f"  [{completed}/{len(slugs)}] {Colors.RED}✗{Colors.RESET} {slug}: {e}"
                        )

        # Summary
        if verbose:
            success_count = sum(1 for r in results if r.success)
            print(f"\n{Colors.GREEN}{'=' * 60}{Colors.RESET}")
            print(f"{Colors.BOLD}Download Complete!{Colors.RESET}")
            print(f"  ✓ Success: {success_count}")
            print(f"  ✗ Failed: {len(results) - success_count}")
            print(f"  📁 Location: {self.output_dir.absolute()}")
            print(f"{Colors.GREEN}{'=' * 60}{Colors.RESET}\n")

        return results

    def stop(self):
        """Stop the download operation."""
        self.stop_event.set()
