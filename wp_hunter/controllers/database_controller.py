"""
Database Controller for WP-Hunter
"""

import json
import csv
from pathlib import Path
from typing import Optional

from wp_hunter.config import Colors
from wp_hunter.database.plugin_metadata import PluginMetadataRepository
from wp_hunter.downloaders.svn_downloader import SVNDownloader


def display_db_stats() -> None:
    """Show database statistics."""
    repo = PluginMetadataRepository()
    stats = repo.get_stats()

    print(f"\n{Colors.CYAN}{'=' * 50}{Colors.RESET}")
    print(f"{Colors.BOLD}📊 Database Statistics{Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 50}{Colors.RESET}")
    print(f"  📦 Total records: {stats['total_records']:,}")
    print(f"  🔌 Unique plugins: {stats['unique_plugins']:,}")
    print(f"  ⭐ Popular (10k+): {stats['popular_10k']:,}")
    print(f"  🌟 Very Popular (100k+): {stats['popular_100k']:,}")
    print(f"  🕐 Last sync: {stats['last_sync'] or 'Never'}")
    print(f"{Colors.CYAN}{'=' * 50}{Colors.RESET}\n")


def query_database(
    min_installs: int = 0,
    max_installs: int = 0,
    min_rating: int = 0,
    tags: Optional[str] = None,
    search: Optional[str] = None,
    author: Optional[str] = None,
    requires_php: Optional[str] = None,
    tested_wp: Optional[str] = None,
    abandoned: bool = False,
    min_days: int = 0,
    max_days: int = 0,
    sort_by: str = "active_installs",
    sort_order: str = "desc",
    limit: int = 100,
    export_path: Optional[str] = None,
    svn_download: int = 0,
    svn_workers: int = 5,
    svn_output: str = "./Plugins_SVN",
    semgrep_scan: bool = False,
    semgrep_rules: Optional[str] = None,
    semgrep_output: str = "./semgrep_results",
) -> None:
    """Query plugins from local database with advanced filters."""

    # Security: Validate and sanitize export_path
    safe_export_path = None
    if export_path:
        import re

        # Prevent path traversal - only allow simple filenames
        export_path_obj = Path(export_path)

        # Reject paths with parent directory references
        if ".." in export_path or "~" in export_path:
            print(
                f"{Colors.RED}[!] Invalid export path: Path traversal detected{Colors.RESET}"
            )
            return

        # Reject absolute paths
        if export_path_obj.is_absolute():
            print(
                f"{Colors.RED}[!] Invalid export path: Absolute paths not allowed{Colors.RESET}"
            )
            return

        # Only allow alphanumeric, hyphens, underscores, dots for filename
        filename = export_path_obj.name
        if not re.match(r"^[a-zA-Z0-9_.-]+$", filename):
            print(
                f"{Colors.RED}[!] Invalid export path: Invalid characters in filename{Colors.RESET}"
            )
            return

        safe_export_path = str(export_path_obj)

    repo = PluginMetadataRepository()

    # Parse tags if provided
    tag_list = tags.split(",") if tags else None

    plugins = repo.query_plugins(
        min_installs=min_installs,
        max_installs=max_installs if max_installs > 0 else 0,
        min_rating=min_rating,
        tags=tag_list,
        search=search,
        author=author,
        requires_php=requires_php,
        tested_wp=tested_wp,
        abandoned=abandoned,
        min_days=min_days,
        max_days=max_days,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit if limit > 0 else 100,
    )

    if not plugins:
        print(
            f"{Colors.YELLOW}[!] No plugins found matching your criteria.{Colors.RESET}"
        )
        print(
            f"{Colors.GRAY}    Try running --sync-db first to populate the database.{Colors.RESET}"
        )
        return

    # Export to file if requested
    if safe_export_path:
        export_file = Path(safe_export_path)
        export_data = [
            {
                "slug": p.get("slug"),
                "name": p.get("name"),
                "version": p.get("version"),
                "active_installs": p.get("active_installs"),
                "rating": p.get("rating"),
                "last_updated": p.get("last_updated"),
                "author": p.get("author"),
                "requires_php": p.get("requires_php"),
                "tested": p.get("tested"),
                "download_link": p.get("download_link"),
            }
            for p in plugins
        ]

        if export_file.suffix.lower() == ".json":
            with open(export_file, "w") as f:
                json.dump(export_data, f, indent=2)
        else:  # Default to CSV
            if not export_file.suffix:
                export_file = export_file.with_suffix(".csv")
            with open(export_file, "w", newline="") as f:
                if export_data:
                    writer = csv.DictWriter(f, fieldnames=export_data[0].keys())
                    writer.writeheader()
                    writer.writerows(export_data)

        print(
            f"{Colors.GREEN}[✓] Exported {len(plugins)} plugins to {export_file}{Colors.RESET}"
        )

    print(f"\n{Colors.CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}📦 Found {len(plugins)} plugins in database{Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 80}{Colors.RESET}\n")

    # Display results in table format
    print(f"{'#':<4} {'Slug':<35} {'Installs':<12} {'Rating':<8} {'Updated':<12}")
    print("-" * 80)

    for i, plugin in enumerate(plugins, 1):
        slug = plugin.get("slug", "")[:34]
        installs = plugin.get("active_installs", 0)
        rating = plugin.get("rating", 0)
        updated = plugin.get("last_updated", "")[:10]

        # Color based on installs
        if installs >= 100000:
            color = Colors.GREEN
        elif installs >= 10000:
            color = Colors.YELLOW
        else:
            color = Colors.WHITE

        print(
            f"{i:<4} {color}{slug:<35}{Colors.RESET} {installs:<12,} {rating:<8} {updated:<12}"
        )

    print(
        f"\n{Colors.GRAY}Use --svn-download N to download top N plugins{Colors.RESET}"
    )

    # SVN download if requested
    downloaded_dirs = []
    if svn_download > 0:
        print(f"\n{Colors.BOLD}Starting SVN download...{Colors.RESET}")
        slugs = [p["slug"] for p in plugins[:svn_download]]

        downloader = SVNDownloader(output_dir=svn_output, workers=svn_workers)
        results = downloader.download_many(slugs, verbose=True)

        # Collect downloaded directories for Semgrep scan
        for result in results:
            if result.success:
                plugin_dir = Path(svn_output) / result.slug
                if plugin_dir.exists():
                    downloaded_dirs.append(str(plugin_dir))

    # Semgrep scan if requested
    if semgrep_scan and downloaded_dirs:
        print(f"\n{Colors.BOLD}Starting Semgrep security scan...{Colors.RESET}")

        try:
            from wp_hunter.scanners.semgrep_scanner import SemgrepScanner

            scanner = SemgrepScanner(
                rules_path=semgrep_rules, output_dir=semgrep_output, workers=3
            )
            scanner.scan_plugins(downloaded_dirs, verbose=True)

        except ImportError:
            print(
                f"{Colors.YELLOW}[!] Semgrep scanner module not loaded.{Colors.RESET}"
            )
        except Exception as e:
            print(f"{Colors.RED}[!] Semgrep scan error: {e}{Colors.RESET}")
