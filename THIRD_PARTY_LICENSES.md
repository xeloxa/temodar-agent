# Third-Party Licenses

This project is licensed under the Apache License, Version 2.0 (`LICENSE`).

Temodar Agent integrates third-party tools and dependencies. Their licenses remain in effect for their respective components.

## Temodar Agent (Main Project)

- License: Apache License 2.0
- License file: `LICENSE`

## Semgrep

- Project: `semgrep/semgrep`
- Repository: https://github.com/semgrep/semgrep
- License: GNU Lesser General Public License v2.1 (`LGPL-2.1`)
- Upstream license file: https://github.com/semgrep/semgrep/blob/develop/LICENSE
- Canonical LGPL text in this repo: `licenses/LGPL-2.1.txt`
- Source notice in this repo: `licenses/SEMGREP_SOURCE_NOTICE.txt`

### Usage in Temodar Agent

Temodar Agent invokes Semgrep as an external scanner process for static analysis.
Temodar Agent does not relicense Semgrep, and Semgrep remains covered by its own LGPL-2.1 license.

If you redistribute Semgrep binaries or modified Semgrep code as part of another package, you must satisfy LGPL-2.1 obligations for that component.

### Docker redistribution note

Temodar Agent Docker image copies license artifacts into `/licenses`:

- `/licenses/Temodar-Agent-Apache-2.0.txt`
- `/licenses/THIRD_PARTY_LICENSES.md`
- `/licenses/LGPL-2.1.txt`
- `/licenses/SEMGREP_SOURCE_NOTICE.txt`

