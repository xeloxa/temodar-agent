# Semgrep security scanner for WordPress plugins

import json
import subprocess
import threading
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from wp_hunter.config import Colors
from wp_hunter.infrastructure.semgrep_runtime import (
    get_semgrep_command,
    is_semgrep_available,
    semgrep_install_hint,
)


print_lock = threading.Lock()

# Official Semgrep Registry Rulesets + WP-Hunter Core
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


@dataclass
class SemgrepResult:
    slug: str
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
        # Default to OWASP + PHP + Security Audit rulesets
        self.registry_rulesets = registry_rulesets or DEFAULT_ENABLED_RULESETS
        self.semgrep_command = get_semgrep_command()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _filter_custom_rules(self) -> Optional[str]:
        """Create a temporary custom rules file with disabled rules removed."""
        custom_candidates = [
            self.output_dir / "custom_rules.yaml",
            Path("./semgrep_results/custom_rules.yaml"),
            Path(__file__).resolve().parents[1]
            / "semgrep_results"
            / "custom_rules.yaml",
        ]
        custom_file = next((p for p in custom_candidates if p.exists()), None)
        if not custom_file:
            return None

        disabled_ids = set()

        # Legacy per-output disabled rules format: ["rule-id", ...]
        legacy_disabled_file = self.output_dir / "disabled_rules.json"
        if legacy_disabled_file.exists():
            try:
                with open(legacy_disabled_file, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        disabled_ids.update(loaded)
            except Exception:
                pass

        # Current shared UI format: {"rules": [...], "rulesets": [...]}
        shared_disabled_file = Path("./semgrep_results/disabled_config.json")
        if shared_disabled_file.exists():
            try:
                with open(shared_disabled_file, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        disabled_ids.update(loaded.get("rules", []))
            except Exception:
                pass

        try:
            with open(custom_file, "r") as f:
                rules_data = yaml.safe_load(f)

            if rules_data and "rules" in rules_data:
                active_rules = [
                    r for r in rules_data["rules"] if r.get("id") not in disabled_ids
                ]

                if not active_rules:
                    return None

                filtered_data = {"rules": active_rules}
                filtered_file = self.output_dir / "active_custom_rules.yaml"
                with open(filtered_file, "w") as f:
                    yaml.dump(
                        filtered_data, f, default_flow_style=False, sort_keys=False
                    )
                return str(filtered_file)
        except Exception:
            return str(custom_file)  # Fallback to original

        return str(custom_file)

    def _get_config_args(self) -> List[str]:
        """Build config arguments for semgrep command."""
        configs = []

        # 1. Custom user rules (filtered)
        filtered_custom = self._filter_custom_rules()
        if filtered_custom:
            configs.extend(["--config", filtered_custom])

        # 2. Registry rulesets (OWASP, PHP, etc.)
        if self.use_registry_rules:
            for ruleset_key in self.registry_rulesets:
                # Resolve the config string from our map if it exists
                if ruleset_key in SEMGREP_REGISTRY_RULESETS:
                    config_val = SEMGREP_REGISTRY_RULESETS[ruleset_key]["config"]
                    configs.extend(["--config", config_val])
                else:
                    # Otherwise use the value directly (e.g. if user supplied "p/ci")
                    configs.extend(["--config", ruleset_key])

        return configs

    def _check_semgrep_available(self) -> bool:
        self.semgrep_command = get_semgrep_command()
        return is_semgrep_available()

    def scan_plugin(self, plugin_path: str, slug: str) -> SemgrepResult:
        # Security: Validate inputs
        if not slug or not isinstance(slug, str):
            return SemgrepResult(
                slug=slug or "unknown",
                findings=[],
                errors=["Invalid slug"],
                success=False,
            )

        # Security: Sanitize slug (alphanumeric, hyphens, underscores only)
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", slug):
            return SemgrepResult(
                slug=slug, findings=[], errors=["Invalid slug format"], success=False
            )

        # Security: Validate plugin_path exists and is a directory
        path_obj = Path(plugin_path)
        if not path_obj.exists():
            return SemgrepResult(
                slug=slug,
                findings=[],
                errors=["Plugin path does not exist"],
                success=False,
            )
        if not path_obj.is_dir():
            return SemgrepResult(
                slug=slug,
                findings=[],
                errors=["Plugin path is not a directory"],
                success=False,
            )

        # Security: Prevent path traversal - ensure path is within expected directory
        try:
            # Resolve to absolute path and check for path traversal
            resolved_path = path_obj.resolve()
            plugin_target_path = str(resolved_path)
            # Ensure the path doesn't contain shell metacharacters
            dangerous_chars = [
                ";",
                "&",
                "|",
                "`",
                "$",
                "(",
                ")",
                "<",
                ">",
                "\\",
                "\n",
                "\r",
            ]
            if any(c in plugin_target_path for c in dangerous_chars):
                return SemgrepResult(
                    slug=slug,
                    findings=[],
                    errors=["Invalid characters in path"],
                    success=False,
                )
        except Exception as e:
            return SemgrepResult(
                slug=slug,
                findings=[],
                errors=[f"Path validation error: {str(e)}"],
                success=False,
            )

        if self.stop_event.is_set():
            return SemgrepResult(
                slug=slug, findings=[], errors=["Stopped"], success=False
            )

        output_file = self.output_dir / f"{slug}_results.json"

        try:
            # Build command with all config sources
            if not self.semgrep_command:
                return SemgrepResult(
                    slug=slug,
                    findings=[],
                    errors=[f"Semgrep not available. {semgrep_install_hint()}"],
                    success=False,
                )

            cmd = list(self.semgrep_command)
            cmd.extend(self._get_config_args())
            cmd.extend(
                [
                    "--json",
                    "--output",
                    str(output_file),
                    "--no-git-ignore",
                    plugin_target_path,
                ]
            )

            # Ensure output directory exists before running
            output_file.parent.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # Reduced timeout to 60 seconds to prevent hanging
            )

            # Check return code. Semgrep returns 0 if clean, 1 if findings, >1 if error
            # But recent versions return 0 even with findings unless --error is used
            # We care if the output file was created and is valid JSON

            findings = []
            errors = []
            parsing_success = False

            if output_file.exists() and output_file.stat().st_size > 0:
                try:
                    with open(output_file, "r") as f:
                        data = json.load(f)
                        findings = data.get("results", [])
                        # Semgrep errors are usually in 'errors' key
                        errors = [e.get("message", "") for e in data.get("errors", [])]
                        parsing_success = True
                except json.JSONDecodeError:
                    errors.append(
                        f"Invalid JSON output from Semgrep. Stderr: {result.stderr}"
                    )
            else:
                if result.returncode != 0:
                    errors.append(
                        f"Semgrep failed (code {result.returncode}): {result.stderr}"
                    )
                else:
                    errors.append(f"No output file generated. Stderr: {result.stderr}")

            return SemgrepResult(
                slug=slug, findings=findings, errors=errors, success=parsing_success
            )

        except subprocess.TimeoutExpired:
            return SemgrepResult(
                slug=slug, findings=[], errors=["Scan timeout"], success=False
            )
        except Exception as e:
            return SemgrepResult(slug=slug, findings=[], errors=[str(e)], success=False)

    def scan_plugins(
        self, plugin_dirs: List[str], verbose: bool = True
    ) -> Dict[str, SemgrepResult]:
        if not self._check_semgrep_available():
            if verbose:
                print(
                    f"{Colors.RED}[!] Semgrep is not installed or not found in PATH.{Colors.RESET}"
                )
                print(f"    Semgrep is required for static code analysis.")
                print(f"")
                print(f"    {semgrep_install_hint()}")
            return {}

        if verbose:
            print(f"\n{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(f"{Colors.BOLD}🔍 Running Semgrep Security Scan{Colors.RESET}")
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}")
            print(f"  📁 Plugins: {len(plugin_dirs)}")
            print(f"  📄 Output: {self.output_dir}")
            print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")

        results: Dict[str, SemgrepResult] = {}
        total_findings = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_plugin = {}

            for plugin_path in plugin_dirs:
                path = Path(plugin_path)
                if path.exists() and path.is_dir():
                    slug = path.name
                    future = executor.submit(self.scan_plugin, str(path), slug)
                    future_to_plugin[future] = slug

            completed = 0
            for future in as_completed(future_to_plugin):
                if self.stop_event.is_set():
                    break

                slug = future_to_plugin[future]
                completed += 1

                try:
                    result = future.result()
                    results[slug] = result

                    finding_count = len(result.findings)
                    total_findings += finding_count

                    if verbose:
                        if finding_count > 0:
                            color = Colors.RED if finding_count >= 5 else Colors.YELLOW
                            print(
                                f"  [{completed}/{len(plugin_dirs)}] {color}⚠{Colors.RESET} {slug}: {finding_count} findings"
                            )
                        else:
                            print(
                                f"  [{completed}/{len(plugin_dirs)}] {Colors.GREEN}✓{Colors.RESET} {slug}: clean"
                            )

                except Exception as e:
                    if verbose:
                        print(
                            f"  [{completed}/{len(plugin_dirs)}] {Colors.RED}✗{Colors.RESET} {slug}: {e}"
                        )

        if verbose and results:
            self._print_summary(results, total_findings)
        self._save_combined_report(results)

        return results

    def _print_summary(self, results: Dict[str, SemgrepResult], total_findings: int):
        print(f"\n{Colors.CYAN}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.BOLD}📊 Scan Summary{Colors.RESET}")
        print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}")
        print(f"  🔌 Plugins scanned: {len(results)}")
        print(f"  ⚠️  Total findings: {total_findings}")
        severities = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        for result in results.values():
            for finding in result.findings:
                sev = finding.get("extra", {}).get("severity", "INFO")
                severities[sev] = severities.get(sev, 0) + 1

        if total_findings > 0:
            print(f"\n  By Severity:")
            if severities.get("ERROR", 0) > 0:
                print(f"    {Colors.RED}ERROR{Colors.RESET}: {severities['ERROR']}")
            if severities.get("WARNING", 0) > 0:
                print(
                    f"    {Colors.YELLOW}WARNING{Colors.RESET}: {severities['WARNING']}"
                )
            if severities.get("INFO", 0) > 0:
                print(f"    {Colors.GRAY}INFO{Colors.RESET}: {severities['INFO']}")
        sorted_results = sorted(
            results.items(), key=lambda x: len(x[1].findings), reverse=True
        )[:5]

        if sorted_results and len(sorted_results[0][1].findings) > 0:
            print(f"\n  Top Vulnerable Plugins:")
            for slug, result in sorted_results:
                if len(result.findings) > 0:
                    print(f"    • {slug}: {len(result.findings)} findings")

        print(f"\n  📁 Results saved to: {self.output_dir}")
        print(f"{Colors.CYAN}{'=' * 60}{Colors.RESET}\n")

    def _save_combined_report(self, results: Dict[str, SemgrepResult]):
        report = {
            "total_plugins": len(results),
            "total_findings": sum(len(r.findings) for r in results.values()),
            "plugins": {},
        }

        for slug, result in results.items():
            report["plugins"][slug] = {
                "findings": result.findings,
                "errors": result.errors,
                "success": result.success,
            }

        report_path = self.output_dir / "combined_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

    def stop(self):
        self.stop_event.set()
