"""
WP-Hunter VPS Scorer

Vulnerability Probability Score calculation.
"""

from typing import Dict, Any, List, Optional

from wp_hunter.config import Colors, CURRENT_WP_VERSION
from wp_hunter.models import CodeAnalysisResult


def calculate_vps_score(
    plugin: Dict[str, Any],
    days_ago: int,
    matched_tags: List[str],
    support_rate: int,
    tested_ver: str,
    sec_flags: List[str],
    code_analysis: Optional[CodeAnalysisResult] = None,
) -> int:
    """
    Enhanced VPS calculation with code analysis integration.
    High Score = High Probability of Unknown Vulnerabilities (0-day) or Unpatched Code.

    Scoring breakdown:
    - CODE ROT (Maintenance Latency): Max 40 pts
    - ATTACK SURFACE (Intrinsic Risk): Max 30 pts
    - DEVELOPER NEGLECT (Support Health): Max 15 pts
    - TECHNICAL DEBT (Compatibility): Max 15 pts
    - REPUTATION (Quality Signal): Max 10 pts
    - CODE ANALYSIS BONUS: Max 25 pts
    """
    score = 0
    evidence_count = 0

    # 1. CODE ROT (Maintenance Latency)
    if days_ago > 1095:  # >3 years
        score += 24
        evidence_count += 1
    elif days_ago > 730:  # >2 years
        score += 18
        evidence_count += 1
    elif days_ago > 365:
        score += 10
    elif days_ago > 180:
        score += 4

    # 2. ATTACK SURFACE (Intrinsic Risk)
    unique_tags = set(matched_tags or [])
    if unique_tags:
        score += min(18, len(unique_tags) * 2)
        if len(unique_tags) >= 2:
            evidence_count += 1

    # 3. DEVELOPER NEGLECT (Support Health)
    if support_rate < 20:
        score += 10
        evidence_count += 1
    elif support_rate < 50:
        score += 6

    # 4. TECHNICAL DEBT (Compatibility)
    try:
        ver_str = str(tested_ver).split("-")[0]
        parts = ver_str.split(".")
        if len(parts) >= 2:
            ver_float = float(f"{parts[0]}.{parts[1]}")
        else:
            ver_float = float(ver_str)

        compat_gap = CURRENT_WP_VERSION - ver_float
        if compat_gap >= 1.0:
            score += 8
            evidence_count += 1
        elif compat_gap >= 0.5:
            score += 5
    except (ValueError, TypeError, IndexError):
        score += 2

    # 5. REPUTATION (Quality Signal)
    raw_rating = plugin.get("rating", 0)
    if not isinstance(raw_rating, (int, float)) or raw_rating < 0:
        raw_rating = 0
    elif raw_rating > 100:
        raw_rating = 100
    rating = raw_rating / 20
    if rating < 2.5:
        score += 8
        evidence_count += 1
    elif rating < 3.5:
        score += 4
    elif rating < 4.2:
        score += 2

    # 6. KNOWN SECURITY SIGNALS (high-confidence)
    if sec_flags:
        score += min(20, 10 + len(sec_flags) * 4)
        evidence_count += 2

    # 7. CODE ANALYSIS SIGNALS (if available)
    if code_analysis:
        if code_analysis.sanitization_issues:
            score += min(20, 6 + len(code_analysis.sanitization_issues) * 2)
            evidence_count += 2

        if code_analysis.dangerous_functions:
            dangerous_score = min(10, len(code_analysis.dangerous_functions) * 2)
            if code_analysis.sanitization_issues:
                dangerous_score += 4
            score += min(14, dangerous_score)
            evidence_count += 1

        if code_analysis.ajax_endpoints and not code_analysis.nonce_usage:
            score += 10
            evidence_count += 1

        if code_analysis.file_operations and code_analysis.sanitization_issues:
            score += 4
            evidence_count += 1

    # 8. User-facing bonus (small, to avoid over-scoring)
    user_input_tags = {
        "form",
        "contact",
        "input",
        "chat",
        "comment",
        "review",
        "upload",
        "profile",
    }
    if any(tag in unique_tags for tag in user_input_tags):
        score += 3

    # 9. Trust/maintenance reductions
    author_text = str(plugin.get("author", "")).lower()
    if "automattic" in author_text or "wordpress.org" in author_text:
        score = max(0, score - 6)

    if days_ago < 30:
        score = max(0, score - 4)

    if (
        code_analysis
        and code_analysis.nonce_usage
        and not code_analysis.sanitization_issues
    ):
        score = max(0, score - 4)

    # 10. False-positive guardrails: high scores require corroboration
    if score >= 65 and evidence_count < 3:
        score = min(score, 54)
    elif score >= 40 and evidence_count < 2:
        score = min(score, 34)

    return max(0, min(score, 100))


def get_score_display(score: int) -> str:
    """Generates a colored ASCII bar for the score."""
    bar_len = 10
    filled = int((score / 100) * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    if score >= 65:
        return f"{Colors.RED}[{bar}] {score} (CRITICAL){Colors.RESET}"
    elif score >= 40:
        return f"{Colors.ORANGE}[{bar}] {score} (HIGH){Colors.RESET}"
    elif score >= 20:
        return f"{Colors.YELLOW}[{bar}] {score} (MEDIUM){Colors.RESET}"
    else:
        return f"{Colors.GREEN}[{bar}] {score} (LOW){Colors.RESET}"


def get_score_level(score: int) -> str:
    """Get text level for score."""
    if score >= 65:
        return "CRITICAL"
    elif score >= 40:
        return "HIGH"
    elif score >= 20:
        return "MEDIUM"
    else:
        return "LOW"
