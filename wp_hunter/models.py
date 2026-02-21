"""
WP-Hunter Data Models

All dataclasses and type definitions for the application.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


class ScanStatus(Enum):
    """Scan session status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CodeAnalysisResult:
    """Code analysis result for plugins/themes."""

    dangerous_functions: List[str] = field(default_factory=list)
    ajax_endpoints: List[str] = field(default_factory=list)
    theme_functions: List[str] = field(default_factory=list)
    file_operations: List[str] = field(default_factory=list)
    sql_queries: List[str] = field(default_factory=list)
    nonce_usage: List[str] = field(default_factory=list)
    sanitization_issues: List[str] = field(default_factory=list)


@dataclass
class ScanConfig:
    """Scan configuration parameters."""

    # Basic scanning options
    pages: int = 5
    limit: int = 0
    min_installs: int = 1000
    max_installs: int = 0
    sort: str = "updated"  # new, updated, popular

    # Filter flags
    smart: bool = False
    abandoned: bool = False
    user_facing: bool = False
    themes: bool = False

    # Time filtering
    min_days: int = 0
    max_days: int = 0

    # Analysis flags
    ajax_scan: bool = False
    dangerous_functions: bool = False

    # Aggressive mode
    aggressive: bool = False

    # Filter by Score
    min_score: int = 0

    # Output options
    output: Optional[str] = None
    format: str = "json"  # json, csv, html
    download: int = 0
    auto_download_risky: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "pages": self.pages,
            "limit": self.limit,
            "min_installs": self.min_installs,
            "max_installs": self.max_installs,
            "sort": self.sort,
            "smart": self.smart,
            "abandoned": self.abandoned,
            "user_facing": self.user_facing,
            "themes": self.themes,
            "min_days": self.min_days,
            "max_days": self.max_days,
            "ajax_scan": self.ajax_scan,
            "dangerous_functions": self.dangerous_functions,
            "aggressive": self.aggressive,
            "min_score": self.min_score,
            "output": self.output,
            "format": self.format,
            "download": self.download,
            "auto_download_risky": self.auto_download_risky,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScanConfig":
        """Create from dictionary."""
        return cls(
            pages=data.get("pages", 5),
            limit=data.get("limit", 0),
            min_installs=data.get("min_installs", data.get("min", 1000)),
            max_installs=data.get("max_installs", data.get("max", 0)),
            sort=data.get("sort", "updated"),
            smart=data.get("smart", False),
            abandoned=data.get("abandoned", False),
            user_facing=data.get("user_facing", data.get("user-facing", False)),
            themes=data.get("themes", False),
            min_days=data.get("min_days", data.get("min-days", 0)),
            max_days=data.get("max_days", data.get("max-days", 0)),
            ajax_scan=data.get("ajax_scan", data.get("ajax-scan", False)),
            dangerous_functions=data.get(
                "dangerous_functions", data.get("dangerous-functions", False)
            ),
            aggressive=data.get("aggressive", False),
            min_score=data.get("min_score", 0),
            output=data.get("output"),
            format=data.get("format", "json"),
            download=data.get("download", 0),
            auto_download_risky=data.get(
                "auto_download_risky", data.get("auto-download-risky", 0)
            ),
        )


@dataclass
class ScanSession:
    """A scan session for persistence."""

    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    status: ScanStatus = ScanStatus.PENDING
    config: Optional[ScanConfig] = None
    total_found: int = 0
    high_risk_count: int = 0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status.value,
            "config": self.config.to_dict() if self.config else None,
            "total_found": self.total_found,
            "high_risk_count": self.high_risk_count,
            "error_message": self.error_message,
        }


@dataclass
class PluginResult:
    """Structured result for a scanned plugin."""

    # Basic info
    name: str
    slug: str
    version: str

    # Scores & metrics
    score: int = 0
    relative_risk: str = ""
    installations: int = 0
    days_since_update: int = 0
    tested_wp_version: str = "?"

    # Flags
    author_trusted: bool = False
    is_risky_category: bool = False
    is_user_facing: bool = False
    is_duplicate: bool = False
    is_theme: bool = False

    # Analysis data
    risk_tags: List[str] = field(default_factory=list)
    security_flags: List[str] = field(default_factory=list)
    feature_flags: List[str] = field(default_factory=list)
    code_analysis: Optional[CodeAnalysisResult] = None

    # Links
    download_link: str = ""
    wp_org_link: str = ""
    cve_search_link: str = ""
    wpscan_link: str = ""
    patchstack_link: str = ""
    wordfence_link: str = ""
    google_dork_link: str = ""
    trac_link: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses and reports."""
        result = {
            "name": self.name,
            "slug": self.slug,
            "version": self.version,
            "score": self.score,
            "relative_risk": self.relative_risk,
            "installations": self.installations,
            "days_since_update": self.days_since_update,
            "tested_wp_version": self.tested_wp_version,
            "author_trusted": self.author_trusted,
            "is_risky_category": self.is_risky_category,
            "is_user_facing": self.is_user_facing,
            "is_duplicate": self.is_duplicate,
            "is_theme": self.is_theme,
            "risk_tags": self.risk_tags,
            "security_flags": self.security_flags,
            "feature_flags": self.feature_flags,
            "download_link": self.download_link,
            "wp_org_link": self.wp_org_link,
            "cve_search_link": self.cve_search_link,
            "wpscan_link": self.wpscan_link,
            "patchstack_link": self.patchstack_link,
            "wordfence_link": self.wordfence_link,
            "google_dork_link": self.google_dork_link,
            "trac_link": self.trac_link,
        }

        if self.code_analysis:
            result["code_analysis"] = {
                "dangerous_functions": self.code_analysis.dangerous_functions,
                "ajax_endpoints": self.code_analysis.ajax_endpoints,
                "file_operations": self.code_analysis.file_operations,
                "sql_queries": self.code_analysis.sql_queries,
                "nonce_usage": self.code_analysis.nonce_usage,
                "sanitization_issues": self.code_analysis.sanitization_issues,
            }

        return result
