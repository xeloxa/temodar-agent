"""
WP-Hunter Theme Scanner

Theme fetching and analysis from WordPress.org API.
"""

import time
from typing import List, Dict, Any, Optional, Callable
from urllib.parse import quote_plus

from wp_hunter.config import Colors, RISKY_TAGS
from wp_hunter.infrastructure.http_client import get_session
from wp_hunter.utils.date_utils import calculate_days_ago


class ThemeScanner:
    """WordPress Theme Scanner."""

    def __init__(
        self,
        pages: int = 5,
        limit: int = 0,
        sort: str = "popular",
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        self.pages = pages
        self.limit = limit
        self.sort = sort
        self.on_result = on_result
        self.on_progress = on_progress
        self.results: List[Dict[str, Any]] = []

    def fetch_themes(self, page: int = 1, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Fetch themes from WordPress.org API."""
        session = get_session()
        url = "https://api.wordpress.org/themes/info/1.2/"
        params = {
            "action": "query_themes",
            "request[browse]": self.sort,
            "request[page]": page,
            "request[per_page]": 100,
            "request[fields][description]": True,
            "request[fields][downloaded]": True,
            "request[fields][last_updated]": True,
            "request[fields][download_link]": True,
            "request[fields][version]": True,
            "request[fields][author]": True,
            "request[fields][tags]": True,
            "request[fields][screenshot_url]": True,
        }

        for attempt in range(max_retries):
            try:
                response = session.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("themes", []) if data else []
                elif response.status_code == 429:
                    wait_time = 5 * (attempt + 1)
                    print(
                        f"{Colors.YELLOW}[!] Rate limited, waiting {wait_time}s...{Colors.RESET}"
                    )
                    time.sleep(wait_time)
                    continue
            except Exception as e:
                print(f"{Colors.RED}[!] Theme API Error: {e}{Colors.RESET}")
                time.sleep(2)
                continue
        return []

    def process_theme(self, theme: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single theme and return analysis."""
        name = theme.get("name", "Unknown")
        slug = theme.get("slug", "")
        version = theme.get("version", "?")
        downloads = theme.get("downloaded", 0)
        last_updated = theme.get("last_updated", "")
        author = theme.get("author", "Unknown")

        days_ago = calculate_days_ago(last_updated)

        # Check for risky patterns in theme
        theme_tags = list(theme.get("tags", {}).keys())
        desc = theme.get("description", "").lower()
        matched_tags = [tag for tag in RISKY_TAGS if tag in theme_tags or tag in desc]

        # Simple risk assessment for themes
        risk_score = 0
        if days_ago > 730:
            risk_score += 40  # Abandoned
        elif days_ago > 365:
            risk_score += 25
        if matched_tags:
            risk_score += 20
        if downloads < 1000:
            risk_score += 10

        # Align thresholds with plugin-facing UI semantics.
        risk_level = (
            "HIGH" if risk_score >= 40 else ("MEDIUM" if risk_score >= 20 else "LOW")
        )

        google_dork_query = (
            f"\"{slug}\" "
            f"intext:\"{slug}\" "
            f"(\"wordpress theme\" OR \"wp theme\" OR \"wordpress.org/themes/{slug}\") "
            f"(vulnerability OR exploit OR cve) "
            f"-\"wordpress plugin\" -\"plugins/\""
        )

        return {
            "name": name,
            "slug": slug,
            "version": version,
            "downloads": downloads,
            "days_since_update": days_ago,
            "author": author,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "matched_tags": matched_tags,
            "download_link": theme.get("download_link", ""),
            "wp_org_link": f"https://wordpress.org/themes/{slug}/",
            "trac_link": f"https://themes.trac.wordpress.org/log/{slug}/",
            "wpscan_link": f"https://wpscan.com/theme/{slug}",
            "patchstack_link": f"https://patchstack.com/database?search={slug}",
            "wordfence_link": f"https://www.wordfence.com/threat-intel/vulnerabilities/search?search={slug}",
            "cve_search_link": f"https://cve.mitre.org/cgi-bin/cvekey.cgi?keyword={slug}",
            "google_dork_link": f"https://www.google.com/search?q={quote_plus(google_dork_query)}",
            "screenshot_url": theme.get("screenshot_url", ""),
        }

    def scan(self) -> List[Dict[str, Any]]:
        """Run the theme scan."""
        found_count = 0

        for page in range(1, self.pages + 1):
            if self.limit > 0 and found_count >= self.limit:
                break

            themes = self.fetch_themes(page)

            if not themes:
                break

            for theme in themes:
                if self.limit > 0 and found_count >= self.limit:
                    break

                result = self.process_theme(theme)
                found_count += 1
                self.results.append(result)

                if self.on_result:
                    self.on_result(result)

            if self.on_progress:
                self.on_progress(page, self.pages)

            time.sleep(0.5)  # Rate limiting

        return self.results

    def get_summary(self) -> Dict[str, Any]:
        """Get scan summary statistics."""
        return {
            "total_found": len(self.results),
            "high_risk": sum(1 for r in self.results if r.get("risk_level") == "HIGH"),
            "medium_risk": sum(
                1 for r in self.results if r.get("risk_level") == "MEDIUM"
            ),
            "low_risk": sum(1 for r in self.results if r.get("risk_level") == "LOW"),
        }
