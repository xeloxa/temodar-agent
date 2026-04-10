import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from infrastructure.semgrep_runtime import get_semgrep_command, is_semgrep_available
from scanners.semgrep_scanner import (
    DEFAULT_ENABLED_RULESETS,
    SEMGREP_COMMUNITY_SOURCES,
    SEMGREP_REGISTRY_RULESETS,
)

logger = logging.getLogger("temodar_agent")

CORE_RULESET_KEYS = {"owasp-top-ten", "php-security", "security-audit"}
CORE_RULESET_CONFIGS = {"p/owasp-top-ten", "p/php", "p/security-audit"}
CORE_RULESET_CONFIG_TO_KEY = {
    "p/owasp-top-ten": "owasp-top-ten",
    "p/php": "php-security",
    "p/security-audit": "security-audit",
}
SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
RULESET_PATTERN = re.compile(r"^[a-zA-Z0-9_./-]+$")
RULE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

SEM_RESULTS_DIR = Path("./semgrep_results")
SEM_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
SEMGREP_STATE_DIR = Path.home() / ".temodar-agent" / "semgrep"
SEMGREP_STATE_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_CUSTOM_RULES_PATH = SEM_RESULTS_DIR / "custom_rules.yaml"
LEGACY_DISABLED_CONFIG_PATH = SEM_RESULTS_DIR / "disabled_config.json"
ROOT_CUSTOM_RULES_PATH = Path(__file__).resolve().parents[2] / "custom_rules.yaml"
CUSTOM_RULES_PATH = SEMGREP_STATE_DIR / "custom_rules.yaml"
DISABLED_CONFIG_PATH = SEMGREP_STATE_DIR / "disabled_config.json"
PACKAGE_CUSTOM_RULES_PATH = (
    Path(__file__).resolve().parents[2] / "semgrep_results" / "custom_rules.yaml"
)


def _yaml_file_has_rules(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", []) if isinstance(data, dict) else []
        return isinstance(rules, list) and len(rules) > 0
    except Exception:
        return False


def bootstrap_default_custom_rules() -> None:
    should_bootstrap_custom_rules = not _yaml_file_has_rules(CUSTOM_RULES_PATH)
    if should_bootstrap_custom_rules:
        for candidate in (
            ROOT_CUSTOM_RULES_PATH,
            LEGACY_CUSTOM_RULES_PATH,
            PACKAGE_CUSTOM_RULES_PATH,
        ):
            if not _yaml_file_has_rules(candidate):
                continue
            try:
                shutil.copy2(candidate, CUSTOM_RULES_PATH)
                break
            except Exception:
                logger.warning("Failed to bootstrap default Semgrep custom rules from %s.", candidate)

    if not DISABLED_CONFIG_PATH.exists() and LEGACY_DISABLED_CONFIG_PATH.exists():
        try:
            shutil.copy2(LEGACY_DISABLED_CONFIG_PATH, DISABLED_CONFIG_PATH)
        except Exception:
            logger.warning("Failed to migrate disabled Semgrep config.")


def get_disabled_config() -> Dict[str, List[str]]:
    """Load disabled rules and rulesets configuration."""
    default_config = {"rules": [], "rulesets": [], "extra_rulesets": []}
    legacy_default_rulesets = {"cwe-top-25"}
    if DISABLED_CONFIG_PATH.exists():
        try:
            with open(DISABLED_CONFIG_PATH, "r") as f:
                config = json.load(f)
                before_rulesets = set(config.get("rulesets", []))
                before_extras = set(config.get("extra_rulesets", []))
                normalized = {
                    "rules": config.get("rules", []),
                    "rulesets": config.get("rulesets", []),
                    "extra_rulesets": config.get("extra_rulesets", []),
                }
                normalized["rulesets"] = list(
                    dict.fromkeys(_canonicalize_ruleset_value(r) for r in normalized["rulesets"])
                )
                normalized["extra_rulesets"] = list(
                    dict.fromkeys(
                        _canonicalize_ruleset_value(r)
                        for r in normalized["extra_rulesets"]
                    )
                )
                normalized["rulesets"] = [
                    r for r in normalized["rulesets"] if r not in legacy_default_rulesets
                ]
                normalized["extra_rulesets"] = [
                    r for r in normalized["extra_rulesets"] if r not in legacy_default_rulesets
                ]
                if before_rulesets != set(normalized["rulesets"]) or before_extras != set(
                    normalized["extra_rulesets"]
                ):
                    save_disabled_config(normalized)
                return normalized
        except Exception:
            pass
    return default_config


def save_disabled_config(config: Dict[str, List[str]]):
    """Save disabled configuration."""
    DISABLED_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DISABLED_CONFIG_PATH, "w") as f:
        json.dump(config, f)


def get_active_rulesets() -> List[str]:
    """Return the registry rulesets that are not disabled globally."""
    config = get_disabled_config()
    disabled = set(config.get("rulesets", []))
    extra_rulesets = config.get("extra_rulesets", [])
    combined = DEFAULT_ENABLED_RULESETS + extra_rulesets
    unique = list(dict.fromkeys(combined))
    return [rs for rs in unique if rs not in disabled]


def _normalize_ruleset_value(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    if value.startswith(("p/", "r/")):
        return value
    if value.startswith("https://semgrep.dev/"):
        parsed = value.split("https://semgrep.dev/", 1)[1].strip("/")
        return parsed
    return value


def _canonicalize_ruleset_value(raw: str) -> str:
    normalized = _normalize_ruleset_value(raw)
    return CORE_RULESET_CONFIG_TO_KEY.get(normalized, normalized)


def _validate_slug_or_raise(slug: str) -> str:
    value = (slug or "").strip()
    if not SLUG_PATTERN.fullmatch(value):
        raise ValueError("Invalid slug format")
    return value


def _validate_rule_id_or_raise(rule_id: str) -> str:
    value = (rule_id or "").strip()
    if not RULE_ID_PATTERN.match(value):
        raise ValueError("Invalid rule ID format")
    return value


def validate_ruleset_or_raise(ruleset_id: str) -> str:
    ruleset_id = _canonicalize_ruleset_value(ruleset_id)
    if not RULESET_PATTERN.match(ruleset_id):
        raise ValueError("Invalid ruleset format")
    return ruleset_id


def _build_bulk_download_url(plugin: Dict[str, Any], slug: str) -> str:
    version = plugin.get("version") or "latest"
    return plugin.get("download_link") or (
        f"https://downloads.wordpress.org/plugin/{slug}.{version}.zip"
    )


def _extract_bulk_plugin_meta(plugin: Dict[str, Any]) -> Optional[Dict[str, str]]:
    raw_slug = plugin.get("slug")
    if not raw_slug:
        return None

    slug = _validate_slug_or_raise(str(raw_slug))
    version = str(plugin.get("version") or "latest")
    download_url = _build_bulk_download_url(plugin, slug)
    return {"slug": slug, "version": version, "download_url": download_url}


def _validate_semgrep_rules_config(rules_config: Dict[str, Any]) -> Optional[str]:
    semgrep_command = get_semgrep_command()
    if not semgrep_command:
        return "Semgrep is not available for rule validation."

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.dump(rules_config, tmp, default_flow_style=False, sort_keys=False)
            temp_path = tmp.name

        result = subprocess.run(
            [*semgrep_command, "--validate", "--config", temp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return None

        error_text = (
            result.stderr or result.stdout or "Unknown Semgrep validation error"
        ).strip()
        return error_text[:800]
    except subprocess.TimeoutExpired:
        return "Semgrep validation timed out."
    except Exception as e:
        return f"Semgrep validation failed: {str(e)}"
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


def load_custom_rules() -> List[Dict[str, Any]]:
    custom_rules: List[Dict[str, Any]] = []
    if CUSTOM_RULES_PATH.exists():
        try:
            with open(CUSTOM_RULES_PATH, "r") as f:
                custom_yaml = yaml.safe_load(f)
                if custom_yaml and "rules" in custom_yaml:
                    for rule in custom_yaml["rules"]:
                        rule_id = rule.get("id", "unknown")
                        pattern = rule.get("pattern", "")
                        if not pattern and "patterns" in rule:
                            patterns = rule["patterns"]
                            if patterns:
                                pattern = (
                                    str(patterns[0])
                                    if isinstance(patterns[0], str)
                                    else patterns[0].get("pattern", "Complex")
                                )

                        custom_rules.append(
                            {
                                "id": rule_id,
                                "message": rule.get("message", ""),
                                "severity": rule.get("severity", "WARNING"),
                                "pattern": pattern,
                                "is_custom": True,
                            }
                        )
        except Exception as e:
            logger.warning("Error loading custom rules", exc_info=e)
    return custom_rules


def load_custom_rules_document() -> Dict[str, Any]:
    if CUSTOM_RULES_PATH.exists():
        try:
            with open(CUSTOM_RULES_PATH, "r") as f:
                return yaml.safe_load(f) or {"rules": []}
        except Exception:
            pass
    return {"rules": []}


def save_custom_rules_document(rules_data: Dict[str, Any]) -> None:
    CUSTOM_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CUSTOM_RULES_PATH, "w") as f:
        yaml.dump(rules_data, f, default_flow_style=False, sort_keys=False)


def build_semgrep_rules_response() -> Dict[str, Any]:
    installed = is_semgrep_available()
    disabled_config = get_disabled_config()
    disabled_rules = set(disabled_config["rules"])
    disabled_rulesets = set(disabled_config["rulesets"])

    rulesets = []
    for key, info in SEMGREP_REGISTRY_RULESETS.items():
        if key not in CORE_RULESET_KEYS:
            continue
        rulesets.append(
            {
                "id": key,
                "name": info.get("description", key),
                "url": info.get("url", "#"),
                "enabled": key not in disabled_rulesets,
                "description": info.get("description", ""),
                "deletable": False,
            }
        )

    existing_ids = {r["id"] for r in rulesets}
    for extra in disabled_config.get("extra_rulesets", []):
        normalized = _normalize_ruleset_value(extra)
        if not normalized or normalized in existing_ids:
            continue
        url = (
            f"https://semgrep.dev/{normalized}"
            if normalized.startswith(("p/", "r/"))
            else "https://semgrep.dev/explore"
        )
        rulesets.append(
            {
                "id": normalized,
                "name": normalized,
                "url": url,
                "enabled": normalized not in disabled_rulesets,
                "description": "Custom Semgrep ruleset",
                "deletable": True,
            }
        )

    custom_rules = load_custom_rules()
    for rule in custom_rules:
        rule["enabled"] = rule["id"] not in disabled_rules

    return {
        "installed": installed,
        "rulesets": rulesets,
        "custom_rules": custom_rules,
        "community_sources": SEMGREP_COMMUNITY_SOURCES,
    }


bootstrap_default_custom_rules()
