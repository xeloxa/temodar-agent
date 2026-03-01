# Third-Party Licenses

This project is licensed under the MIT License (`LICENSE`).

WP-Hunter integrates third-party tools and dependencies. Their licenses remain in effect for their respective components.

## Semgrep

- Project: `semgrep/semgrep`
- Repository: https://github.com/semgrep/semgrep
- License: GNU Lesser General Public License v2.1 (`LGPL-2.1`)
- Upstream license file: https://github.com/semgrep/semgrep/blob/develop/LICENSE

### Usage in WP-Hunter

WP-Hunter invokes Semgrep as an external scanner process for static analysis.
WP-Hunter does not relicense Semgrep, and Semgrep remains covered by its own LGPL-2.1 license.

If you redistribute Semgrep binaries or modified Semgrep code as part of another package, you must satisfy LGPL-2.1 obligations for that component.
