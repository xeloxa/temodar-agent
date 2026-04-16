<p align="center">
  <img src="assets/banner.png" alt="Temodar Agent Banner" width="900" />
</p>

<h1 align="center">Temodar Agent</h1>

<blockquote>
  <p>
    <strong>Temodar Agent is now listed in <a href="https://github.com/vavkamil/awesome-bugbounty-tools">awesome-bugbounty-tools</a></strong> — a curated bug bounty resources list with <strong>5.9k+ GitHub stars</strong>.
  </p>
</blockquote>

<p align="center">
  <img src="https://img.shields.io/badge/Docker-Required-2496ED?logo=docker&logoColor=white" alt="Docker Required">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Analysis-AI--Agent%20%2B%20Semgrep-FF6B35" alt="AI-Agent + Semgrep">
  <img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License Apache 2.0">
  <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/Listed-awesome--bugbounty--tools-f59e0b?logo=github&logoColor=white" alt="Listed on awesome-bugbounty-tools">
</p>

<p align="center">
  <b>AI agent-powered WordPress security scanner</b> for plugin and theme triage, Semgrep analysis, and source-aware investigation workflows.
</p>

Temodar Agent is an <b>AI-powered WordPress plugin and theme security analysis platform</b> built for security researchers, product security teams, auditors, and defenders. It combines <b>AI agent workflows</b>, <b>multi-provider LLM orchestration</b>, <b>Semgrep-powered static analysis</b>, and <b>risk-based WordPress reconnaissance</b> in one local-first Docker application.

If you are looking for an <b>AI security scanner for WordPress plugins</b>, an <b>AI agent workflow for code review</b>, or a <b>Semgrep-based vulnerability triage platform</b>, Temodar Agent is designed to make that process faster, more structured, and easier to scale.

## Screenshots

<table>
  <tr>
    <td width="50%">
      <b>AI-assisted security dashboard</b><br>
      Launch scans, prioritize targets, and review results from one interface
    </td>
    <td width="50%">
      <b>Semgrep + AI investigation workflow</b><br>
      Move from static analysis to source-aware AI review without losing context
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/scr/1.jpeg" alt="Temodar Agent AI security dashboard" width="100%" />
    </td>
    <td>
      <img src="assets/scr/2.jpeg" alt="Temodar Agent Semgrep and AI analysis workflow" width="100%" />
    </td>
  </tr>
</table>

## What Temodar Agent Does

Temodar Agent helps teams identify which WordPress plugins and themes deserve attention first, run repeatable code analysis, and continue investigation with AI agent systems that stay attached to the target under review.

Core platform capabilities include:
- WordPress plugin and theme scanning
- risk-based target prioritization
- Semgrep-powered static application security testing
- AI agent-assisted investigation threads
- multi-provider AI configuration and execution
- custom Semgrep rule management
- local result persistence and historical review

## AI Agent Capabilities

Temodar Agent is built around an <b>AI agent workflow</b> rather than a simple chat box.

### Source-aware AI investigation
- Open dedicated <b>AI threads per plugin or per theme</b>
- Prepare a trusted source workspace for the selected target before deeper review
- Keep thread-level context attached to the investigation, including:
  - conversation summary
  - analysis summary
  - findings summary
  - architecture notes
  - important files
  - last prepared source path

### Multi-agent and execution strategy support
The current runtime supports multiple AI execution strategies that are already exposed in the application:
- <b>agent</b>
- <b>team</b>
- <b>tasks</b>
- <b>fanout</b>
- <b>auto</b>

This makes Temodar Agent suitable for teams that want to move from a single-agent workflow to more advanced <b>multi-agent analysis patterns</b> inside the same product.

### AI run control and orchestration
The platform also supports:
- custom `agents` payloads
- custom `tasks` payloads
- fanout configuration
- loop detection settings
- trace and runtime event streaming
- before-run and after-run hook payloads
- manual approval mode
- auto-approve mode
- structured AI output when an output schema is provided

## Multi-Provider AI System

Temodar Agent includes a <b>multi-provider AI configuration system</b> with stored profiles, active profile switching, and connection testing.

Supported providers currently present in the application:
- <b>Anthropic</b>
- <b>OpenAI</b>
- <b>Copilot</b>
- <b>Gemini</b>
- <b>Grok</b>

Provider system features already implemented:
- multiple saved provider profiles
- active provider switching
- model selection per profile
- model list storage per profile
- provider connection testing
- optional custom base URL support
- masked API key handling in the UI layer

## Semgrep Security Analysis

Temodar Agent includes a production-oriented <b>Semgrep analysis workflow</b> for WordPress source code review.

### Built-in Semgrep coverage
The current application ships with support for these default Semgrep rulesets:
- <b>OWASP Top 10</b>
- <b>PHP security</b>
- <b>security audit</b>

### Custom rule and ruleset management
The current Semgrep system also supports:
- custom Semgrep rule creation
- custom rule deletion
- rule enable / disable toggling
- bulk enable / disable operations
- ruleset add / remove / toggle actions
- validation of custom rule documents
- bulk Semgrep scanning across a scan session
- persistent local storage for Semgrep outputs

This makes Temodar Agent useful not only as an <b>AI security research tool</b>, but also as a <b>Semgrep operations layer</b> for teams that maintain their own detection logic.

## WordPress Security Triage and Prioritization

Temodar Agent helps security teams reduce noise before manual review starts.

The scanning system can:
- scan WordPress plugins or themes from public sources
- filter by install counts and update windows
- identify abandoned or user-facing targets
- prioritize packages using metadata, tags, and security-related signals
- assign relative risk labels for faster triage
- stream progress to the dashboard in real time
- store scan sessions for later comparison and follow-up

## Why Teams Use Temodar Agent

Temodar Agent is designed for organizations that want:
- a faster way to review large WordPress plugin ecosystems
- an <b>AI agent layer</b> on top of source code analysis
- a bridge between Semgrep findings and human investigation
- reusable investigation memory per target
- a local-first workflow for security research and internal review

## Requirements

Temodar Agent is designed to run with <b>Docker</b>.

You need:
- <b>Docker</b> installed and running
- permission to run Docker commands on your machine

Useful links:
- [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Docker Engine installation guide](https://docs.docker.com/engine/install/)
- [Docker documentation](https://docs.docker.com/)

## Installation

### 1. Pull the latest image

```bash
docker pull xeloxa/temodar-agent:latest
```

### 2. Start Temodar Agent

```bash
docker run -d --name temodar-agent -p 8080:8080 \
  -v temodar-agent-data:/home/appuser/.temodar-agent \
  xeloxa/temodar-agent:latest
```

`latest` is recommended if you want the newest published image, but starting an existing container with `docker start temodar-agent` does not pull new images. To move to a newer `latest`, pull the image again and recreate the container.

### Run a specific version

If you want a pinned release instead of `latest`, use a version tag:

```bash
docker pull xeloxa/temodar-agent:v0.1.3
docker run -d --name temodar-agent -p 8080:8080 \
  -v temodar-agent-data:/home/appuser/.temodar-agent \
  xeloxa/temodar-agent:v0.1.3
```

Open the dashboard at:
- [http://127.0.0.1:8080](http://127.0.0.1:8080)

## Data Persistence

Temodar Agent stores persistent application data in one named Docker volume: `temodar-agent-data`, mounted at `/home/appuser/.temodar-agent`.

This is a hard cutover to the canonical runtime root. Existing three-volume installs are no longer the supported Docker contract. Recreate the container with the official one-volume command instead of keeping `temodar-agent-plugins` or `temodar-agent-semgrep` mounted.

## Typical Workflow

1. Start Temodar Agent with the official `docker run` command
2. Open the local dashboard
3. Launch a WordPress plugin or theme scan
4. Review risk labels and prioritized targets
5. Run Semgrep on a selected target or across a session
6. Open an AI thread for source-aware follow-up analysis
7. Continue investigation with stored context, thread memory, and runtime events

## Updating

Temodar Agent no longer runs host-side update scripts or local rebuild flows.

To update manually:

```bash
docker pull xeloxa/temodar-agent:latest
docker rm -f temodar-agent >/dev/null 2>&1 || true
docker run -d --name temodar-agent -p 8080:8080 \
  -v temodar-agent-data:/home/appuser/.temodar-agent \
  xeloxa/temodar-agent:latest
```

The in-app update UI only notifies you about new releases and can copy this manual Docker update command. If you installed a pinned tag such as `v0.1.3`, update by pulling and rerunning the newer pinned tag you want rather than assuming `docker start` will move you forward.

If you are upgrading from an older three-volume install, stop using the old plugin and Semgrep volumes and recreate the container with only `temodar-agent-data` mounted at `/home/appuser/.temodar-agent`.

## Star History

<p align="center">
  <a href="https://www.star-history.com/#xeloxa/temodar-agent&type=Date&legend=top-left">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=xeloxa/temodar-agent&type=Date&theme=dark&legend=top-left" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=xeloxa/temodar-agent&type=Date&legend=top-left" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=xeloxa/temodar-agent&type=Date&theme=dark&legend=top-left" />
    </picture>
  </a>
</p>

## Legal Disclaimer

This project is intended for <b>authorized security research, defensive analysis, and educational use only</b>. It is designed to help researchers and developers assess WordPress plugin and theme attack surfaces, prioritize risky targets, and review code more efficiently.

Do <b>not</b> use this software against systems, plugins, themes, or environments you do not own or do not have explicit permission to test. The author and contributors are <b>not responsible</b> for misuse, damage, service disruption, data loss, or any legal consequences resulting from improper use.

Always ensure your testing is authorized and compliant with applicable laws, regulations, and disclosure policies.
