"""
Pydantic Models for API
"""

from typing import Optional, List
from typing_extensions import Literal
from pydantic import BaseModel, Field, HttpUrl


class ScanRequest(BaseModel):
    pages: int = 5
    limit: int = 0
    min_installs: int = 1000
    max_installs: int = 0
    sort: str = "updated"
    smart: bool = False
    abandoned: bool = False
    user_facing: bool = False
    themes: bool = False
    min_days: int = 0
    max_days: int = 0
    download: int = 0
    auto_download_risky: int = 0
    output: Optional[str] = None
    format: str = "json"
    ajax_scan: bool = False
    dangerous_functions: bool = False
    aggressive: bool = False


class DownloadRequest(BaseModel):
    slug: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="WordPress slug (letters, numbers, underscore, hyphen)",
    )
    download_url: HttpUrl


class SemgrepRuleRequest(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    pattern: str = Field(..., min_length=1, max_length=10000)
    message: str = Field(..., min_length=1, max_length=500)
    severity: Literal["ERROR", "WARNING", "INFO"] = "WARNING"
    languages: List[str] = Field(default_factory=lambda: ["php"], min_length=1)


class SemgrepRulesetRequest(BaseModel):
    ruleset: str = Field(..., min_length=1, max_length=200)
