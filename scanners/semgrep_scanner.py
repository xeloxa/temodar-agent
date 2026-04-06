# Semgrep security scanner for WordPress plugins

import json
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from infrastructure.semgrep_runtime import get_semgrep_command, semgrep_install_hint


# Official Semgrep Registry Rulesets + Temodar Agent Core
SEMGREP_REGISTRY_RULESETS = {
    "owasp-top-ten": {
        "config": "p/owasp-top-ten",
        "description": "OWASP Top 10 vulnerabilities (2021)",
        "url": "https://semgrep.dev/p/owasp-top-ten",
    },
    "php-security": {
        "config": "p/php",
        "description": "PHP security best practices",
        "url": "https://semgrep.dev/p/php",
    },
    "security-audit": {
        "config": "p/security-audit",
        "description": "Comprehensive security audit rules",
        "url": "https://semgrep.dev/p/security-audit",
    },
}

# Default enabled rulesets
DEFAULT_ENABLED_RULESETS = ["owasp-top-ten", "php-security", "security-audit"]

# Community rule sources for user reference
SEMGREP_COMMUNITY_SOURCES = [
    {
        "name": "Semgrep Registry",
        "url": "https://semgrep.dev/r",
        "description": "Official Semgrep rule registry with 3000+ rules",
    },
    {
        "name": "OWASP Top 10 Rules",
        "url": "https://semgrep.dev/p/owasp-top-ten",
        "description": "Rules for OWASP Top 10 2021 vulnerabilities",
    },
    {
        "name": "PHP Security Rules",
        "url": "https://semgrep.dev/p/php",
        "description": "PHP-specific security patterns",
    },
    {
        "name": "Security Audit Pack",
        "url": "https://semgrep.dev/p/security-audit",
        "description": "Comprehensive security audit rules",
    },
]

SEMGREP_TIMEOUT_SECONDS = 60
SAFE_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
DANGEROUS_PATH_CHARS = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r"]


@dataclass
class SemgrepResult:
    slug: str
    findings: List[Dict[str, Any]]
    errors: List[str]
    success: bool


@dataclass
class SemgrepTarget:
    slug: str
    plugin_target_path: str
    output_file: Path


@dataclass
class SemgrepExecutionResult:
    findings: List[Dict[str, Any]]
    errors: List[str]
    success: bool


class SemgrepScanner:
    def __init__(
        self,
        rules_path: Optional[str] = None,
        output_dir: str = "./semgrep_results",
        workers: int = 3,
        use_registry_rules: bool = True,
        registry_rulesets: Optional[List[str]] = None,
    ):
        self.rules_path = rules_path
        self.output_dir = Path(output_dir)
        self.workers = workers
        self.stop_event = threading.Event()
        self.use_registry_rules = use_registry_rules
        self.registry_rulesets = registry_rulesets or DEFAULT_ENABLED_RULESETS
        self.semgrep_command = get_semgrep_command()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _result(self, slug: str, *, findings: Optional[List[Dict[str, Any]]] = None, errors: Optional[List[str]] = None, success: bool = False) -> SemgrepResult:
        """Create a normalized Semgrep result payload."""
        return SemgrepResult(
            slug=slug,
            findings=findings or [],
            errors=errors or [],
            success=success,
        )

    def _load_disabled_rule_ids(self) -> set[str]:
        """Load disabled custom rule IDs from legacy and current config locations."""
        disabled_ids: set[str] = set()

        legacy_disabled_file = self.output_dir / "disabled_rules.json"
        if legacy_disabled_file.exists():
            try:
                with open(legacy_disabled_file, "r") as file_handle:
                    loaded = json.load(file_handle)
                if isinstance(loaded, list):
                    disabled_ids.update(str(item) for item in loaded)
            except Exception:
                pass

        shared_disabled_file = Path("./semgrep_results/disabled_config.json")
        if shared_disabled_file.exists():
            try:
                with open(shared_disabled_file, "r") as file_handle:
                    loaded = json.load(file_handle)
                if isinstance(loaded, dict):
                    disabled_ids.update(str(item) for item in loaded.get("rules", []))
            except Exception:
                pass

        return disabled_ids

    def _resolve_custom_rules_file(self) -> Optional[Path]:
        """Find the best available custom rules file candidate."""
        custom_candidates = [
            self.output_dir / "custom_rules.yaml",
            Path("./semgrep_results/custom_rules.yaml"),
            Path(__file__).resolve().parents[1] / "semgrep_results" / "custom_rules.yaml",
        ]
        return next((path for path in custom_candidates if path.exists()), None)

    def _validate_custom_rule(self, rule: Dict[str, Any]) -> bool:
        """Return whether an individual custom rule passes Semgrep validation."""
        if not self.semgrep_command:
            return True

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as tmp:
                yaml.dump({"rules": [rule]}, tmp, default_flow_style=False, sort_keys=False)
                temp_path = tmp.name

            result = subprocess.run(
                [*self.semgrep_command, "--validate", "--config", temp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except Exception:
            return False
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def _write_filtered_custom_rules(self, rules_data: Dict[str, Any], disabled_ids: set[str]) -> Optional[str]:
        """Persist a filtered custom rules file with disabled or invalid rules removed."""
        rules = rules_data.get("rules", [])
        if not isinstance(rules, list):
            return None

        active_rules: List[Dict[str, Any]] = []
        invalid_rule_ids: List[str] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or "")
            if not rule_id or rule_id in disabled_ids:
                continue
            if self._validate_custom_rule(rule):
                active_rules.append(rule)
            else:
                invalid_rule_ids.append(rule_id)

        if invalid_rule_ids:
            invalid_path = self.output_dir / "invalid_custom_rules.json"
            with open(invalid_path, "w") as file_handle:
                json.dump({"invalid_rule_ids": invalid_rule_ids}, file_handle)

        if not active_rules:
            return None

        filtered_file = self.output_dir / "active_custom_rules.yaml"
        with open(filtered_file, "w") as file_handle:
            yaml.dump(
                {"rules": active_rules},
                file_handle,
                default_flow_style=False,
                sort_keys=False,
            )
        return str(filtered_file)

    def _filter_custom_rules(self) -> Optional[str]:
        """Create a temporary custom rules file with disabled rules removed."""
        custom_file = self._resolve_custom_rules_file()
        if not custom_file:
            return None

        disabled_ids = self._load_disabled_rule_ids()
        try:
            with open(custom_file, "r") as file_handle:
                rules_data = yaml.safe_load(file_handle)
            if rules_data and "rules" in rules_data:
                return self._write_filtered_custom_rules(rules_data, disabled_ids)
        except Exception:
            return str(custom_file)

        return str(custom_file)

    def _get_config_args(self) -> List[str]:
        """Build config arguments for semgrep command."""
        config_values: List[str] = []

        filtered_custom = self._filter_custom_rules()
        if filtered_custom:
            config_values.append(filtered_custom)

        if self.use_registry_rules:
            for ruleset_key in self.registry_rulesets:
                config_value = str(
                    SEMGREP_REGISTRY_RULESETS.get(ruleset_key, {}).get(
                        "config",
                        ruleset_key,
                    )
                    or ""
                ).strip()
                if config_value:
                    config_values.append(config_value)

        deduped_configs = list(dict.fromkeys(config_values))
        configs: List[str] = []
        for config_value in deduped_configs:
            configs.extend(["--config", config_value])
        return configs

    def _validate_scan_target(self, plugin_path: str, slug: str) -> SemgrepTarget | SemgrepResult:
        """Validate user input and build a normalized scan target."""
        if not slug or not isinstance(slug, str):
            return self._result(slug or "unknown", errors=["Invalid slug"])

        if not SAFE_SLUG_PATTERN.match(slug):
            return self._result(slug, errors=["Invalid slug format"])

        path_obj = Path(plugin_path)
        if not path_obj.exists():
            return self._result(slug, errors=["Plugin path does not exist"])
        if not path_obj.is_dir():
            return self._result(slug, errors=["Plugin path is not a directory"])

        try:
            resolved_path = path_obj.resolve()
            plugin_target_path = str(resolved_path)
            if any(char in plugin_target_path for char in DANGEROUS_PATH_CHARS):
                return self._result(slug, errors=["Invalid characters in path"])
        except Exception as exc:
            return self._result(slug, errors=[f"Path validation error: {str(exc)}"])

        return SemgrepTarget(
            slug=slug,
            plugin_target_path=plugin_target_path,
            output_file=self.output_dir / f"{slug}_results.json",
        )

    def _build_scan_command(self, target: SemgrepTarget) -> List[str]:
        """Build the full semgrep subprocess command."""
        command = list(self.semgrep_command)
        command.extend(self._get_config_args())
        command.extend(
            [
                "--json",
                "--output",
                str(target.output_file),
                "--no-git-ignore",
                target.plugin_target_path,
            ]
        )
        return command

    def _is_non_fatal_semgrep_error(self, message: str) -> bool:
        """Return whether a Semgrep error message is non-fatal for the overall scan."""
        normalized = str(message or "").lower()
        non_fatal_markers = [
            "syntax error",
            "parse error",
            "partial parsing",
            "could not parse",
            "was unexpected",
        ]
        return any(marker in normalized for marker in non_fatal_markers)

    def _parse_output_file(self, output_file: Path, stderr: str) -> SemgrepExecutionResult:
        """Parse semgrep JSON output file."""
        try:
            with open(output_file, "r") as file_handle:
                data = json.load(file_handle)
        except json.JSONDecodeError:
            return SemgrepExecutionResult(
                findings=[],
                errors=[f"Invalid JSON output from Semgrep. Stderr: {stderr}"],
                success=False,
            )

        findings = data.get("results", [])
        raw_errors = data.get("errors", [])
        errors = [
            str(error.get("message") or "").strip()
            for error in raw_errors
            if isinstance(error, dict) and str(error.get("message") or "").strip()
        ]
        stderr_text = str(stderr or "").strip()

        if errors:
            non_fatal_errors = [error for error in errors if self._is_non_fatal_semgrep_error(error)]
            fatal_errors = [error for error in errors if error not in non_fatal_errors]

            if fatal_errors or not findings:
                if stderr_text:
                    errors.append(f"stderr: {stderr_text}")
                return SemgrepExecutionResult(
                    findings=findings if findings else [],
                    errors=errors,
                    success=False,
                )

            # Semgrep can report parser/syntax issues for some files while still producing
            # valid findings for the rest of the target. Treat that as a successful scan
            # so the UI can display the findings instead of showing a hard failure.
            return SemgrepExecutionResult(
                findings=findings,
                errors=non_fatal_errors,
                success=True,
            )

        return SemgrepExecutionResult(
            findings=findings,
            errors=[],
            success=True,
        )

    def _parse_subprocess_result(
        self,
        *,
        output_file: Path,
        returncode: int,
        stderr: str,
    ) -> SemgrepExecutionResult:
        """Convert subprocess output into normalized findings/errors."""
        if output_file.exists() and output_file.stat().st_size > 0:
            return self._parse_output_file(output_file, stderr)

        if returncode != 0:
            return SemgrepExecutionResult(
                findings=[],
                errors=[f"Semgrep failed (code {returncode}): {stderr}"],
                success=False,
            )

        return SemgrepExecutionResult(
            findings=[],
            errors=[f"No output file generated. Stderr: {stderr}"],
            success=False,
        )

    def _execute_scan(self, target: SemgrepTarget) -> SemgrepExecutionResult:
        """Run the semgrep subprocess and parse its output."""
        if not self.semgrep_command:
            return SemgrepExecutionResult(
                findings=[],
                errors=[f"Semgrep not available. {semgrep_install_hint()}"],
                success=False,
            )

        target.output_file.parent.mkdir(parents=True, exist_ok=True)

        # Use Popen for cooperative cancellation support and resource limits.
        process = subprocess.Popen(
            self._build_scan_command(target),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=SEMGREP_TIMEOUT_SECONDS)
            # Enforce output size cap to prevent memory exhaustion.
            MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10 MB
            if len(stdout) > MAX_OUTPUT_SIZE:
                stdout = stdout[:MAX_OUTPUT_SIZE]
            if len(stderr) > MAX_OUTPUT_SIZE:
                stderr = stderr[:MAX_OUTPUT_SIZE]
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return SemgrepExecutionResult(
                findings=[], errors=["Scan timeout"], success=False,
            )

        return self._parse_subprocess_result(
            output_file=target.output_file,
            returncode=process.returncode,
            stderr=stderr,
        )

    def scan_plugin(self, plugin_path: str, slug: str) -> SemgrepResult:
        target = self._validate_scan_target(plugin_path, slug)
        if isinstance(target, SemgrepResult):
            return target

        if self.stop_event.is_set():
            return self._result(target.slug, errors=["Stopped"])

        try:
            execution_result = self._execute_scan(target)
            return self._result(
                target.slug,
                findings=execution_result.findings,
                errors=execution_result.errors,
                success=execution_result.success,
            )
        except subprocess.TimeoutExpired:
            return self._result(target.slug, errors=["Scan timeout"])
        except Exception as exc:
            return self._result(target.slug, errors=[str(exc)])

    def stop(self):
        self.stop_event.set()
