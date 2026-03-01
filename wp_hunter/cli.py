"""
WP-Hunter CLI

Command-line interface and main entry point.
"""

import argparse
import logging
import webbrowser
import threading
import time

from wp_hunter.config import Colors
from wp_hunter.infrastructure.http_client import close_session
from wp_hunter.ui.console import print_banner
from wp_hunter.controllers.database_controller import query_database, display_db_stats
from wp_hunter.controllers.sync_controller import run_db_sync as sync_controller_run
from wp_hunter.controllers.scan_controller import run_plugin_scan, run_theme_scan


def get_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="WP Hunter - WordPress Plugin & Theme Security Scanner"
    )

    # Basic scanning options
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="Maximum number of pages to scan (Default: 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of targets to list (0 = Unlimited)",
    )
    parser.add_argument(
        "--min", type=int, default=1000, help="Minimum active installations"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="Maximum active installations (0 = Unlimited)",
    )
    parser.add_argument(
        "--sort", type=str, default="updated", choices=["new", "updated", "popular"]
    )
    parser.add_argument(
        "--smart", action="store_true", help="Show only risky categories"
    )
    parser.add_argument(
        "--abandoned",
        action="store_true",
        help="Show only plugins not updated for > 2 years",
    )

    # Output options
    parser.add_argument(
        "--output", type=str, help="Output file name (e.g., results.json)"
    )
    parser.add_argument(
        "--format",
        type=str,
        default="json",
        choices=["json", "csv", "html"],
        help="Output format",
    )
    parser.add_argument(
        "--download",
        type=int,
        default=0,
        metavar="N",
        help="Download top N plugins (sorted by VPS score) to ./Plugins/",
    )

    # Time filtering
    parser.add_argument(
        "--min-days", type=int, default=0, help="Minimum days since last update"
    )
    parser.add_argument(
        "--max-days", type=int, default=0, help="Maximum days since last update"
    )

    # Analysis features
    parser.add_argument(
        "--themes", action="store_true", help="Scan WordPress themes instead of plugins"
    )
    parser.add_argument(
        "--ajax-scan",
        action="store_true",
        help="Focus on plugins with AJAX functionality",
    )
    parser.add_argument(
        "--dangerous-functions",
        action="store_true",
        help="Look for plugins using dangerous PHP functions",
    )
    parser.add_argument(
        "--user-facing",
        action="store_true",
        help="Focus on plugins that interact directly with end-users (high risk)",
    )
    parser.add_argument(
        "--auto-download-risky",
        type=int,
        default=0,
        metavar="N",
        help="Auto-download top N riskiest plugins for analysis",
    )
    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="AGGRESSIVE MODE: Scan everything, no limits, high concurrency.",
    )

    # GUI mode
    parser.add_argument(
        "--gui", action="store_true", help="Launch web dashboard on localhost:8080"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for web dashboard (default: 8080)"
    )
    parser.add_argument(
        "--check-update",
        action="store_true",
        help="Check for a newer WP-Hunter release and exit",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Download and install the latest WP-Hunter release, then exit",
    )

    # Database sync options
    parser.add_argument(
        "--sync-db",
        action="store_true",
        help="Sync plugin metadata from WordPress.org API to local SQLite database",
    )
    parser.add_argument(
        "--sync-pages",
        type=int,
        default=100,
        help="Number of pages to sync (100 plugins per page, default: 100)",
    )
    parser.add_argument(
        "--sync-workers",
        type=int,
        default=10,
        help="Number of parallel workers for sync (default: 10)",
    )
    parser.add_argument(
        "--sync-type",
        type=str,
        default="updated",
        choices=["updated", "new", "popular"],
        help="Browse type for sync (default: updated)",
    )
    parser.add_argument(
        "--sync-all",
        action="store_true",
        help="Sync entire WordPress plugin catalog (~60k plugins, uses all browse types)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only sync plugins updated since last sync",
    )

    # Database query options
    parser.add_argument(
        "--query-db",
        action="store_true",
        help="Query plugins from local database instead of API",
    )
    parser.add_argument(
        "--db-stats", action="store_true", help="Show database statistics"
    )
    parser.add_argument(
        "--search", type=str, default=None, help="Search term for database query"
    )
    parser.add_argument(
        "--tags",
        type=str,
        default=None,
        help='Comma-separated tags to filter (e.g., "form,payment")',
    )
    parser.add_argument(
        "--min-rating", type=int, default=0, help="Minimum plugin rating (0-100)"
    )
    parser.add_argument(
        "--requires-php",
        type=str,
        default=None,
        help='Filter by PHP version requirement (e.g., "7.4")',
    )
    parser.add_argument(
        "--tested-wp",
        type=str,
        default=None,
        help='Filter by tested WordPress version (e.g., "6.0")',
    )
    parser.add_argument(
        "--author", type=str, default=None, help="Filter by author name"
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="active_installs",
        choices=["active_installs", "rating", "last_updated", "downloaded"],
        help="Sort results by field (default: active_installs)",
    )
    parser.add_argument(
        "--sort-order",
        type=str,
        default="desc",
        choices=["asc", "desc"],
        help="Sort order (default: desc)",
    )

    # Export options
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        metavar="FILE",
        help="Export query results to file (CSV or JSON based on extension)",
    )

    # SVN download options
    parser.add_argument(
        "--svn-download",
        type=int,
        default=0,
        metavar="N",
        help="Download top N plugins from database via SVN",
    )
    parser.add_argument(
        "--svn-workers",
        type=int,
        default=5,
        help="Number of parallel SVN download workers (default: 5)",
    )
    parser.add_argument(
        "--svn-output",
        type=str,
        default="./Plugins_SVN",
        help="Output directory for SVN downloads (default: ./Plugins_SVN)",
    )

    # Semgrep integration
    parser.add_argument(
        "--semgrep-scan",
        action="store_true",
        help="Run Semgrep scan on downloaded plugins",
    )
    parser.add_argument(
        "--semgrep-rules",
        type=str,
        default=None,
        help="Path to custom Semgrep rules (default: built-in PHP security rules)",
    )
    parser.add_argument(
        "--semgrep-output",
        type=str,
        default="./semgrep_results",
        help="Output directory for Semgrep results (default: ./semgrep_results)",
    )

    return parser.parse_args()


def run_db_sync(args: argparse.Namespace) -> None:
    """Sync plugin metadata from WordPress.org API to local database."""
    sync_controller_run(
        incremental=args.incremental,
        sync_all=args.sync_all,
        sync_pages=args.sync_pages,
        sync_workers=args.sync_workers,
        sync_type=args.sync_type,
    )


def run_db_stats() -> None:
    """Show database statistics."""
    display_db_stats()


def run_db_query(args: argparse.Namespace) -> None:
    """Query plugins from local database with advanced filters."""
    query_database(
        min_installs=args.min,
        max_installs=args.max if args.max > 0 else 0,
        min_rating=getattr(args, "min_rating", 0),
        tags=args.tags,
        search=args.search,
        author=getattr(args, "author", None),
        requires_php=getattr(args, "requires_php", None),
        tested_wp=getattr(args, "tested_wp", None),
        abandoned=args.abandoned,
        min_days=args.min_days,
        max_days=args.max_days,
        sort_by=getattr(args, "sort_by", "active_installs"),
        sort_order=getattr(args, "sort_order", "desc"),
        limit=args.limit if args.limit > 0 else 100,
        export_path=getattr(args, "export", None),
        svn_download=getattr(args, "svn_download", 0),
        svn_workers=getattr(args, "svn_workers", 5),
        svn_output=getattr(args, "svn_output", "./Plugins_SVN"),
        semgrep_scan=getattr(args, "semgrep_scan", False),
        semgrep_rules=getattr(args, "semgrep_rules", None),
        semgrep_output=getattr(args, "semgrep_output", "./semgrep_results"),
    )


def run_gui(port: int = 8080) -> None:
    """Start the web dashboard."""
    try:
        from wp_hunter.server.app import create_app
        import uvicorn
    except ImportError as e:
        print(
            f"{Colors.RED}[!] GUI mode requires additional dependencies.{Colors.RESET}"
        )
        print(f"{Colors.YELLOW}Import error: {e}{Colors.RESET}")
        print(
            f"{Colors.YELLOW}Please install: pip install fastapi uvicorn websockets{Colors.RESET}"
        )
        return

    print(f"{Colors.BOLD}{Colors.CYAN}=== WP-Hunter Dashboard ==={Colors.RESET}")
    print(f"Starting web server on http://localhost:{port}")
    print(f"{Colors.GRAY}Press Ctrl+C to stop{Colors.RESET}\n")

    # Open browser after a short delay
    def open_browser():
        import time

        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    # Run server
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _format_release_label(status_payload: dict) -> str:
    latest = status_payload.get("latest_version")
    if latest:
        return str(latest)
    return "unknown"


def run_check_update(update_manager_module) -> None:
    """Check release status once and exit."""
    try:
        status_payload = update_manager_module.manager.get_status(force=True)
    except Exception as exc:
        print(f"{Colors.RED}[!] Update check failed: {exc}{Colors.RESET}")
        return

    latest_label = _format_release_label(status_payload)
    current_label = status_payload.get("current_version") or "unknown"
    if status_payload.get("update_available"):
        print(
            f"{Colors.YELLOW}[!] Update available: {latest_label} (current: {current_label}){Colors.RESET}"
        )
    else:
        print(f"{Colors.GREEN}[✓] You are up to date ({current_label}).{Colors.RESET}")


def run_update(update_manager_module) -> None:
    """Trigger update flow and wait until completion."""
    try:
        status_payload = update_manager_module.manager.get_status(force=True)
    except Exception as exc:
        print(f"{Colors.RED}[!] Update check failed: {exc}{Colors.RESET}")
        return

    if not status_payload.get("update_available"):
        current_label = status_payload.get("current_version") or "unknown"
        print(f"{Colors.GREEN}[✓] Already up to date ({current_label}).{Colors.RESET}")
        return

    latest_label = _format_release_label(status_payload)
    print(f"{Colors.CYAN}[*] Starting update to {latest_label}...{Colors.RESET}")
    try:
        start_message = update_manager_module.manager.start_update()
        print(f"{Colors.GRAY}{start_message}{Colors.RESET}")
    except Exception as exc:
        print(f"{Colors.RED}[!] Could not start update: {exc}{Colors.RESET}")
        return

    last_progress = None
    while True:
        status_payload = update_manager_module.manager.get_status(force=False)
        progress_message = status_payload.get("progress_message")
        if progress_message and progress_message != last_progress:
            print(f"{Colors.GRAY}... {progress_message}{Colors.RESET}")
            last_progress = progress_message

        if not status_payload.get("in_progress"):
            break

        time.sleep(1)

    if status_payload.get("last_error"):
        print(
            f"{Colors.RED}[!] Update failed: {status_payload.get('last_error')}{Colors.RESET}"
        )
        return

    done_message = status_payload.get("last_update_message") or "Update complete."
    print(f"{Colors.GREEN}[✓] {done_message}{Colors.RESET}")


def main() -> None:
    """Main entry point."""
    print_banner()
    args = get_args()

    try:
        update_manager = None
        startup_update_status = None
        try:
            from wp_hunter.server import update_manager as server_update_manager

            update_manager = server_update_manager
            startup_update_status = update_manager.manager.get_status(force=False)
        except Exception:
            logging.getLogger("wp_hunter.update").warning(
                "CLI startup release warmup failed.", exc_info=True
            )

        if args.check_update:
            if not update_manager:
                print(
                    f"{Colors.RED}[!] Update subsystem is not available.{Colors.RESET}"
                )
                return
            run_check_update(update_manager)
            return

        if args.update:
            if not update_manager:
                print(
                    f"{Colors.RED}[!] Update subsystem is not available.{Colors.RESET}"
                )
                return
            run_update(update_manager)
            return

        if startup_update_status and startup_update_status.get("update_available"):
            latest_label = _format_release_label(startup_update_status)
            current_label = startup_update_status.get("current_version") or "unknown"
            print(
                f"{Colors.YELLOW}[!] Update available: {latest_label} (current: {current_label}).{Colors.RESET}"
            )
            print(
                f"{Colors.CYAN}[*] Run this command with --update to install the latest release.{Colors.RESET}"
            )

        # GUI mode
        if args.gui:
            run_gui(args.port)
            return

        # Database sync mode
        if args.sync_db:
            run_db_sync(args)
            return

        # Database stats
        if args.db_stats:
            run_db_stats()
            return

        # Database query mode
        if args.query_db:
            run_db_query(args)
            return

        # Theme scanning mode
        if args.themes:
            run_theme_scan(args)
            return

        # Plugin scanning mode (default)
        run_plugin_scan(args)

    finally:
        close_session()


if __name__ == "__main__":
    main()
