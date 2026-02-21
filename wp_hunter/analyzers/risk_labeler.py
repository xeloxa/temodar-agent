"""
Relative risk labeling utilities.
"""

from typing import Callable, List, TypeVar
import math

T = TypeVar("T")


def apply_relative_risk_labels(
    items: List[T],
    get_score: Callable[[T], int],
    set_label: Callable[[T, str], None],
) -> None:
    """
    Apply percentile-based relative risk labels with an absolute CRITICAL guardrail.

    Labels:
    - CRITICAL: score >= 65
    - HIGH/MEDIUM/LOW: distributed across non-critical set
      (small sample fallback uses absolute buckets)
    """
    if not items:
        return

    # Absolute CRITICAL guardrail.
    for item in items:
        score = int(get_score(item) or 0)
        if score >= 65:
            set_label(item, "CRITICAL")
        else:
            set_label(item, "")

    non_critical = [item for item in items if int(get_score(item) or 0) < 65]
    n = len(non_critical)
    if n == 0:
        return

    # Small sample fallback for stability.
    if n < 8:
        for item in non_critical:
            score = int(get_score(item) or 0)
            if score >= 40:
                set_label(item, "HIGH")
            elif score >= 20:
                set_label(item, "MEDIUM")
            else:
                set_label(item, "LOW")
        return

    sorted_items = sorted(
        non_critical, key=lambda item: int(get_score(item) or 0), reverse=True
    )
    high_n = max(1, math.ceil(n * 0.15))
    medium_n = max(1, math.ceil(n * 0.25))
    if high_n + medium_n > n:
        medium_n = max(0, n - high_n)

    for idx, item in enumerate(sorted_items):
        if idx < high_n:
            set_label(item, "HIGH")
        elif idx < high_n + medium_n:
            set_label(item, "MEDIUM")
        else:
            set_label(item, "LOW")
