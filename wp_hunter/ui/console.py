"""
WP-Hunter Console UI

Terminal output and display functions.
"""

from typing import Dict, Any

from wp_hunter.config import Colors, CURRENT_WP_VERSION
from wp_hunter.models import PluginResult
from wp_hunter.analyzers.vps_scorer import get_score_display, get_score_level


def print_banner() -> None:
    """Print the WP-Hunter ASCII banner."""
    banner = f"""{Colors.BOLD}{Colors.CYAN}
██╗    ██╗██████╗       ██╗  ██╗██╗   ██╗███╗   ██╗████████╗███████╗██████╗ 
██║    ██║██╔══██╗      ██║  ██║██║   ██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗
██║ █╗ ██║██████╔╝█████╗███████║██║   ██║██╔██╗ ██║   ██║   █████╗  ██████╔╝
██║███╗██║██╔═══╝ ╚════╝██╔══██║██║   ██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗
╚███╔███╔╝██║           ██║  ██║╚██████╔╝██║ ╚████║   ██║   ███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝           ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝

                       WordPress Plugin Reconnaissance Tool                 

{Colors.RESET}{Colors.YELLOW}Author: Ali Sünbül (xeloxa)
Email:  alisunbul@proton.me
Repo:   https://github.com/xeloxa/wp-hunter{Colors.RESET}
"""
    print(banner)


def display_plugin_console(idx: int, result: PluginResult) -> None:
    """Display a single plugin result in formatted console output."""
    r = result

    # Get compatibility display
    try:
        tested_ver = float(r.tested_wp_version)
        if tested_ver < CURRENT_WP_VERSION - 0.5:
            compat_display = (
                f"{Colors.RED}Outdated (WP {r.tested_wp_version}){Colors.RESET}"
            )
        else:
            compat_display = f"{Colors.GREEN}Up-to-date{Colors.RESET}"
    except (ValueError, TypeError):
        compat_display = f"{Colors.YELLOW}Unknown{Colors.RESET}"

    score_display = get_score_display(r.score)
    relative_label = r.relative_risk or get_score_level(r.score)

    print(
        f"{Colors.BOLD}{Colors.CYAN}┌── [{idx}] {r.name} {Colors.RESET}(v{r.version})"
    )

    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.BOLD}SCORE:{Colors.RESET} {score_display}  |  {Colors.BOLD}Relative Risk:{Colors.RESET} {relative_label}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.BOLD}Compatibility:{Colors.RESET} {compat_display}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.BOLD}Data:{Colors.RESET} {r.installations}+ Installations | {r.days_since_update} days ago"
    )

    dev_type = (
        f"{Colors.YELLOW}Individual/Indie{Colors.RESET}"
        if not r.author_trusted
        else f"{Colors.BLUE}Corporate{Colors.RESET}"
    )
    if r.author_trusted:
        dev_type += f" {Colors.GREEN}(Trusted Author){Colors.RESET}"
    print(f"{Colors.CYAN}│{Colors.RESET}   {Colors.BOLD}Type:{Colors.RESET} {dev_type}")

    if r.is_user_facing:
        print(
            f"{Colors.CYAN}│{Colors.RESET}   {Colors.MAGENTA}{Colors.BOLD}🎯 USER FACING:{Colors.RESET} Detected"
        )

    if r.security_flags:
        print(
            f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}{Colors.BOLD}⚠ SECURITY PATCH: {', '.join(r.security_flags).upper()}{Colors.RESET}"
        )
    elif r.feature_flags:
        print(
            f"{Colors.CYAN}│{Colors.RESET}   {Colors.YELLOW}{Colors.BOLD}★ NEW FEATURE: {', '.join(r.feature_flags).upper()}{Colors.RESET}"
        )

    if r.risk_tags:
        print(
            f"{Colors.CYAN}│{Colors.RESET}   {Colors.BOLD}Risk Areas:{Colors.RESET} {Colors.ORANGE}{', '.join(list(set(r.risk_tags))[:5]).upper()}{Colors.RESET}"
        )

    # Code Analysis Results
    if r.code_analysis:
        ca = r.code_analysis
        print(
            f"{Colors.CYAN}│{Colors.RESET}   {Colors.GRAY}--- Code Analysis ---{Colors.RESET}"
        )

        if ca.dangerous_functions:
            print(
                f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}🚨 Dangerous Functions: {', '.join(ca.dangerous_functions[:3])}{Colors.RESET}"
            )

        if ca.ajax_endpoints:
            nonce_status = "✓ Protected" if ca.nonce_usage else "⚠ Unprotected"
            print(
                f"{Colors.CYAN}│{Colors.RESET}   {Colors.YELLOW}🔗 AJAX Endpoints: {len(ca.ajax_endpoints)} ({nonce_status}){Colors.RESET}"
            )

        if ca.sanitization_issues:
            print(
                f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}🔓 Sanitization Issues: {len(ca.sanitization_issues)}{Colors.RESET}"
            )

        if ca.file_operations:
            print(
                f"{Colors.CYAN}│{Colors.RESET}   {Colors.ORANGE}📁 File Operations: {len(ca.file_operations)}{Colors.RESET}"
            )

    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.MAGENTA}[Trac Diff]:{Colors.RESET} {r.trac_link}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.BLUE}[Download]:{Colors.RESET}  {r.download_link}"
    )

    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.GRAY}--- Vulnerability Intel ---{Colors.RESET}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}[Smart Dork]:{Colors.RESET} {r.google_dork_link}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}[WPScan]:{Colors.RESET}     {r.wpscan_link}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}[Patchstack]:{Colors.RESET} {r.patchstack_link}"
    )
    print(
        f"{Colors.CYAN}│{Colors.RESET}   {Colors.RED}[Wordfence]:{Colors.RESET}  {r.wordfence_link}"
    )

    print(f"{Colors.CYAN}└──{Colors.RESET}\n")


def display_theme_console(idx: int, result: Dict[str, Any]) -> None:
    """Display a single theme result in formatted console output."""
    risk_score = result.get("risk_score", 0)
    risk_level = result.get("risk_level", "LOW")

    risk_color = (
        Colors.RED
        if risk_score >= 40
        else (Colors.ORANGE if risk_score >= 20 else Colors.GREEN)
    )

    print(
        f"{Colors.BOLD}{Colors.MAGENTA}┌── [{idx}] {result.get('name')} {Colors.RESET}(v{result.get('version')})"
    )
    print(
        f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.BOLD}Risk:{Colors.RESET} {risk_color}{risk_level} ({risk_score}){Colors.RESET}"
    )
    print(
        f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.BOLD}Downloads:{Colors.RESET} {result.get('downloads', 0):,} | {Colors.BOLD}Updated:{Colors.RESET} {result.get('days_since_update', '?')} days ago"
    )
    print(
        f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.BOLD}Author:{Colors.RESET} {result.get('author', 'Unknown')}"
    )

    matched_tags = result.get("matched_tags", [])
    if matched_tags:
        print(
            f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.BOLD}Risk Areas:{Colors.RESET} {Colors.ORANGE}{', '.join(matched_tags[:3]).upper()}{Colors.RESET}"
        )

    download_link = result.get("download_link", "")
    if download_link:
        print(
            f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.BLUE}[Download]:{Colors.RESET} {download_link}"
        )

    trac_link = result.get("trac_link", "")
    if trac_link:
        print(
            f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.MAGENTA}[Trac Diff]:{Colors.RESET} {trac_link}"
        )

    wpscan_link = result.get("wpscan_link", "")
    if wpscan_link:
        print(
            f"{Colors.MAGENTA}│{Colors.RESET}   {Colors.RED}[WPScan]:{Colors.RESET}     {wpscan_link}"
        )

    print(f"{Colors.MAGENTA}└──{Colors.RESET}\n")


def print_summary(summary: Dict[str, Any]) -> None:
    """Print scan summary statistics."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}=== Scan Summary ==={Colors.RESET}")

    if "high_risk" in summary and summary.get("high_risk", 0) > 0:
        print(
            f"High Risk Targets: {Colors.RED}{summary.get('high_risk', 0)}{Colors.RESET}"
        )

    if "abandoned" in summary:
        print(
            f"Abandoned Targets: {Colors.YELLOW}{summary.get('abandoned', 0)}{Colors.RESET}"
        )

    if "user_facing" in summary:
        print(
            f"User Facing Targets: {Colors.MAGENTA}{summary.get('user_facing', 0)}{Colors.RESET}"
        )

    if "risky_categories" in summary:
        print(
            f"Risky Categories: {Colors.ORANGE}{summary.get('risky_categories', 0)}{Colors.RESET}"
        )

    if "medium_risk" in summary:
        print(
            f"Medium Risk Targets: {Colors.ORANGE}{summary.get('medium_risk', 0)}{Colors.RESET}"
        )

    print(
        f"Total Analyzed: {Colors.GREEN}{summary.get('total_found', 0)}{Colors.RESET}"
    )
