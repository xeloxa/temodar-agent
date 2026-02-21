"""
Scan Controller for WP-Hunter
"""

import argparse
from typing import List, Dict, Any

from wp_hunter.config import Colors
from wp_hunter.models import ScanConfig, PluginResult
from wp_hunter.scanners.plugin_scanner import PluginScanner
from wp_hunter.scanners.theme_scanner import ThemeScanner
from wp_hunter.downloaders.plugin_downloader import PluginDownloader
from wp_hunter.reports.html_report import save_results
from wp_hunter.ui.console import (
    display_plugin_console,
    display_theme_console,
    print_summary,
)

REPO_URL = "https://github.com/xeloxa/wp-hunter"


def print_repo_star_line() -> None:
    print(
        f"{Colors.CYAN}[i] Enjoying WP-Hunter? Open the repository and leave a star: {REPO_URL}{Colors.RESET}"
    )


def args_to_config(args: argparse.Namespace) -> ScanConfig:
    """Convert argparse namespace to ScanConfig."""
    return ScanConfig(
        pages=args.pages,
        limit=args.limit,
        min_installs=args.min,
        max_installs=args.max,
        sort=args.sort,
        smart=args.smart,
        abandoned=args.abandoned,
        user_facing=args.user_facing,
        themes=args.themes,
        min_days=args.min_days,
        max_days=args.max_days,
        ajax_scan=args.ajax_scan,
        dangerous_functions=args.dangerous_functions,
        output=args.output,
        format=args.format,
        download=args.download,
        auto_download_risky=args.auto_download_risky,
        aggressive=args.aggressive,
    )


def run_theme_scan(args: argparse.Namespace) -> None:
    """Run theme scanning mode."""
    print_repo_star_line()
    print(
        f"\n{Colors.BOLD}{Colors.MAGENTA}=== WordPress Theme Scanner ==={Colors.RESET}"
    )
    print(f"Scanning {args.pages} pages of themes...\n")

    found_count = [0]

    def on_result(result: Dict[str, Any]):
        found_count[0] += 1
        display_theme_console(found_count[0], result)

    scanner = ThemeScanner(
        pages=args.pages, limit=args.limit, sort=args.sort, on_result=on_result
    )

    scanner.scan()

    print(
        f"{Colors.GREEN}[✓] Theme scan complete: {found_count[0]} themes analyzed{Colors.RESET}"
    )
    print_repo_star_line()

    summary = scanner.get_summary()
    print_summary(summary)


def run_plugin_scan(args: argparse.Namespace) -> None:
    """Run plugin scanning mode."""
    print_repo_star_line()
    config = args_to_config(args)

    # Override defaults for Abandoned Mode to be effective
    if args.abandoned:
        if config.sort == "updated":
            config.sort = "popular"
            print(
                f"{Colors.YELLOW}[!] Mode switched to POPULAR to find abandoned plugins effectively.{Colors.RESET}"
            )

        if args.pages == 5:  # If user didn't change default
            config.pages = 100
            print(
                f"{Colors.YELLOW}[!] Increased page scan limit to 100 to dig deeper for abandoned plugins.{Colors.RESET}"
            )

    # Aggressive Mode Overrides
    if config.aggressive:
        print(
            f"{Colors.BOLD}{Colors.RED}[!!!] AGGRESSIVE MODE ENABLED [!!!]{Colors.RESET}"
        )

        # Override limits if they are at defaults
        if args.pages == 5:
            config.pages = 200
            print(f"{Colors.RED}[!] Pages increased to 200{Colors.RESET}")

        # In Aggressive Mode, we focus on High Value Targets (High Score OR High Popularity)
        config.min_score = 40  # Only show HIGH risk items
        print(f"{Colors.RED}[!] Filtering for High Risk (Score > 40){Colors.RESET}")

        config.limit = 0
        print(f"{Colors.RED}[!] Result limit removed{Colors.RESET}")

        # We keep min_installs default (1000) or user value to avoid junk
        if args.min == 1000:
            print(
                f"{Colors.RED}[!] Min installs kept at 1000 to filter low-quality plugins{Colors.RESET}"
            )

        if config.smart:
            config.smart = False
            print(
                f"{Colors.RED}[!] Smart filter DISABLED (scanning all categories){Colors.RESET}"
            )

    print(f"\n{Colors.BOLD}{Colors.WHITE}=== WP Hunter ==={Colors.RESET}")
    range_str = (
        f"{config.min_installs}-{config.max_installs}"
        if config.max_installs > 0
        else f"{config.min_installs}+"
    )
    print(f"Mode: {config.sort.upper()} | Range: {range_str} installs")

    limit_msg = f"{config.limit} items" if config.limit > 0 else "Unlimited"
    print(f"Target Limit: {Colors.YELLOW}{limit_msg}{Colors.RESET}")

    # Mode indicators
    if config.smart:
        print(f"{Colors.RED}[!] Smart Filter: ON{Colors.RESET}")
    if config.abandoned:
        print(f"{Colors.RED}[!] Abandoned Filter: ON (>730 days){Colors.RESET}")
    if config.ajax_scan:
        print(f"{Colors.YELLOW}[!] AJAX Focus: ON{Colors.RESET}")
    if config.user_facing:
        print(f"{Colors.MAGENTA}[!] User-Facing Plugin Filter: ON{Colors.RESET}")
    if config.dangerous_functions:
        print(f"{Colors.RED}[!] Dangerous Functions Detection: ON{Colors.RESET}")

    if config.min_days > 0 or config.max_days > 0:
        d_min = config.min_days
        d_max = config.max_days if config.max_days > 0 else "∞"
        print(
            f"{Colors.RED}[!] Update Age Filter: {d_min} to {d_max} days{Colors.RESET}"
        )

    print("=" * 70)

    # Set up scanner with callbacks
    found_count = [0]
    collected_results: List[PluginResult] = []

    def on_result(result: PluginResult):
        found_count[0] += 1
        display_plugin_console(found_count[0], result)
        collected_results.append(result)

    # Create scanner
    scanner = PluginScanner(config, on_result=on_result)

    # Run scan
    scanner.scan()

    # Save results
    if config.output and collected_results:
        results_dicts = [r.to_dict() for r in collected_results]
        save_results(results_dicts, config.output, config.format)

    # Download top plugins if requested
    if config.download > 0 and collected_results:
        downloader = PluginDownloader()
        results_dicts = [r.to_dict() for r in collected_results]
        downloader.download_top_plugins(results_dicts, config.download)

    # Auto-download riskiest plugins
    if config.auto_download_risky > 0 and collected_results:
        print(
            f"\n{Colors.BOLD}{Colors.RED}=== Auto-Downloading Riskiest Plugins ==={Colors.RESET}"
        )
        sorted_results = sorted(collected_results, key=lambda x: x.score, reverse=True)
        downloader = PluginDownloader()
        results_dicts = [
            r.to_dict() for r in sorted_results[: config.auto_download_risky]
        ]
        downloader.download_top_plugins(results_dicts, config.auto_download_risky)

    print(
        f"\n{Colors.GREEN}[✓] Scan completed. Total {found_count[0]} targets analyzed.{Colors.RESET}"
    )
    print_repo_star_line()

    # Print summary
    if collected_results:
        summary = scanner.get_summary()
        print_summary(summary)
