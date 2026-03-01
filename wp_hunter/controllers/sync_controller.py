"""
Sync Controller for WP-Hunter
"""

from wp_hunter.config import Colors
from wp_hunter.syncers.plugin_syncer import PluginSyncer, SyncConfig
from wp_hunter.database.plugin_metadata import PluginMetadataRepository


def run_db_sync(
    incremental: bool = False,
    sync_all: bool = False,
    sync_pages: int = 100,
    sync_workers: int = 10,
    sync_type: str = "updated",
) -> None:
    """Sync plugin metadata from WordPress.org API to local database."""
    last_sync = None

    # Check for incremental sync
    if incremental:
        repo = PluginMetadataRepository()
        last_sync = repo.get_last_sync_time()
        if last_sync:
            print(
                f"{Colors.CYAN}[*] Incremental sync mode - last sync: {last_sync}{Colors.RESET}"
            )
        else:
            print(
                f"{Colors.YELLOW}[!] No previous sync found. Running full sync.{Colors.RESET}"
            )

    # Sync-all mode: sync all browse types for full coverage
    if sync_all:
        print(
            f"\n{Colors.BOLD}{Colors.CYAN}=== FULL CATALOG SYNC MODE ==={Colors.RESET}"
        )
        print(f"  This will sync approximately 60,000+ plugins from WordPress.org")
        print(f"  Estimated time: 30-60 minutes depending on connection\n")

        browse_types = ["updated", "popular", "new"]
        total_synced = 0

        for browse_type in browse_types:
            print(
                f"\n{Colors.BOLD}[*] Syncing '{browse_type}' browse type...{Colors.RESET}"
            )

            sync_config = SyncConfig(
                pages=sync_pages or 600,  # 600 pages = ~60k plugins
                browse_type=browse_type,
                workers=sync_workers,
            )

            syncer = PluginSyncer(config=sync_config, last_sync_time=last_sync)
            progress = syncer.sync(verbose=True)
            total_synced += progress.plugins_synced

            if progress.error:
                print(
                    f"{Colors.RED}[!] Error syncing {browse_type}: {progress.error}{Colors.RESET}"
                )

        print(
            f"\n{Colors.GREEN}[✓] Full catalog sync complete! Total synced: {total_synced:,} plugins{Colors.RESET}"
        )
        return

    # Regular sync
    sync_config = SyncConfig(
        pages=sync_pages, browse_type=sync_type, workers=sync_workers
    )

    syncer = PluginSyncer(config=sync_config, last_sync_time=last_sync)
    progress = syncer.sync(verbose=True)

    if progress.error:
        print(f"{Colors.RED}[!] Sync failed: {progress.error}{Colors.RESET}")
