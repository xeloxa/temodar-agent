
<h2 align="center">🚀 AI-powered source code analysis is COMING SOON.</h2>
<div align="center">
  <img src="assets/banner.png" alt="WP-Hunter Banner" width="600"/>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License MIT">
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey" alt="Platform">
</p>

<p align="center">
  <a href="https://www.producthunt.com/products/wp-hunter?embed=true&utm_source=badge-featured&utm_medium=badge&utm_campaign=badge-wp-hunter" target="_blank" rel="noopener noreferrer">
    <img alt="WP-Hunter - WP plugin recon & SAST tool for security researchers. | Product Hunt" width="220" height="48" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1084875&theme=light&t=1771939449742">
  </a>
</p>

<p align="center">
  <b>🌐 Languages / Dil / 语言 / اللغات / Sprachen:</b><br>
  <a href="README.md"><img src="https://img.shields.io/badge/🇬🇧-English-blue" alt="English"></a>
  <a href="README.tr.md"><img src="https://img.shields.io/badge/🇹🇷-Türkçe-red" alt="Türkçe"></a>
  <a href="README.zh.md"><img src="https://img.shields.io/badge/🇨🇳-简体中文-yellow" alt="简体中文"></a>
  <a href="README.ar.md"><img src="https://img.shields.io/badge/🇸🇦-العربية-green" alt="العربية"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪-Deutsch-orange" alt="Deutsch"></a>
</p>

WP-Hunter is a **WordPress plugin/theme reconnaissance and static analysis (SAST) tool**. It is designed for **security researchers** to evaluate the **vulnerability probability** of plugins by analyzing metadata, installation patterns, update histories, and performing deep **Semgrep-powered source code analysis**.

## 🚀 Key Features

*   **Real-time Web Dashboard**: A modern FastAPI-powered interface for visual scanning and analysis.
*   **Deep SAST Integration**: Integrated **Semgrep** scanning with custom rule support.
*   **Offline Recon**: Sync the entire WordPress plugin catalog to a local SQLite database for instant querying.
*   **Risk Scoring (VPS)**: Heuristic-based scoring to identify the "low hanging fruit" in the WordPress ecosystem.
*   **Theme Analysis**: Support for scanning the WordPress theme repository.
*   **Security Hardened**: Built-in SSRF protection and safe execution patterns.

---

## 🖥️ Modern Web Dashboard

WP-Hunter now features a powerful local dashboard for visual researchers.

### Dashboard Gallery

<table>
  <tr>
    <td width="50%">
      <b>Main Interface</b><br>
      Configure scan parameters with intuitive controls
    </td>
    <td width="50%">
      <b>Scan History</b><br>
      Track and manage all your previous scans
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/dashboard-main.png" alt="Main Dashboard" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/scan-history.png" alt="Scan History" width="100%"/>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>Scan Details with Semgrep</b><br>
      Deep SAST analysis with issue tracking
    </td>
    <td width="50%">
      <b>Security Rulesets</b><br>
      Manage OWASP and custom Semgrep rules
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/scan-details.png" alt="Scan Details" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/security-rulesets.png" alt="Security Rulesets" width="100%"/>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <b>CLI Output</b><br>
      Rich terminal interface with vulnerability intelligence
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <img src="assets/screenshots/cli-output.png" alt="CLI Output" width="100%"/>
    </td>
  </tr>
</table>

### Dashboard Capabilities:
*   **Real-time Execution Sequence**: Watch scan results stream in via WebSockets.
*   **Integrated Semgrep**: Run deep static analysis on specific plugins with one click.
*   **Scan History**: Save and compare previous scan sessions.
*   **Favorites System**: Track "interesting" targets for further manual review.
*   **Custom Rules**: Add and manage your own Semgrep security rules directly from the UI.

---

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)
- [Semgrep](https://semgrep.dev/docs/getting-started/) (Optional, for deep analysis)

### Setup
1. Clone the repository:
```bash
git clone https://github.com/xeloxa/WP-Hunter.git
cd WP-Hunter
```
2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```

---

## 🛠️ Usage

### 1. Launching the Web Dashboard (Recommended)
```bash
python3 wp-hunter.py --gui
```
Access the interface at `http://localhost:8080`.

### 2. Database Sync (For Offline Recon)
Populate your local database with plugin metadata for instant filtering:
```bash
# Sync top 100 pages of plugins
python3 wp-hunter.py --sync-db --sync-pages 100

# Sync the entire WordPress catalog (~60k plugins)
python3 wp-hunter.py --sync-all
```

### 3. Local Database Querying
Query your local database without hitting the WordPress API:
```bash
# Find plugins with 10k+ installs not updated for 2 years
python3 wp-hunter.py --query-db --min 10000 --abandoned

# Search for "form" plugins with low ratings
python3 wp-hunter.py --query-db --search "form" --sort-by rating --sort-order asc
```

### 4. CLI Scanning (Classic Mode)
```bash
# Scan 10 pages of updated plugins with Semgrep analysis enabled
python3 wp-hunter.py --pages 10 --semgrep-scan --limit 20
```

---

## 🎯 Hunter Strategies

### 1. The "Zombie" Hunt (High Success Rate)
Target plugins that are widely used but abandoned.
*   **Logic:** Legacy code often lacks modern security standards (missing nonces, weak sanitization).
*   **Command:** `python3 wp-hunter.py --abandoned --min 1000 --sort popular`

### 2. The "Aggressive" Mode
For high-speed, high-concurrency reconnaissance across large scopes.
*   **Command:** `python3 wp-hunter.py --aggressive --pages 200`

### 3. The "Complexity" Trap
Target complex functionality (File Uploads, Payments) in mid-range plugins.
*   **Command:** `python3 wp-hunter.py --smart --min 500 --max 10000`

---

## 📊 VPS Logic (Vulnerability Probability Score)

The score (0-100) reflects the likelihood of **unpatched** or **unknown** vulnerabilities:

| Metric | Condition | Impact | Reasoning |
|--------|-----------|--------|-----------|
| **Code Rot** | > 2 Years Old | **+40 pts** | Abandoned code is a critical risk. |
| **Attack Surface** | Risky Tags | **+30 pts** | Payment, Upload, SQL, Forms are high complexity. |
| **Neglect** | Support < 20% | **+15 pts** | Developers ignoring users likely ignore security reports. |
| **Code Analysis** | Dangerous Funcs | **+5-25 pts** | Presence of `eval()`, `exec()`, or unprotected AJAX. |
| **Tech Debt** | Outdated WP | **+15 pts** | Not tested with the latest WordPress core. |
| **Maintenance** | Update < 14d | **-5 pts** | Active developers are a positive signal. |

---

## ⚖️ Legal Disclaimer

This tool is designed for **security research and authorized reconnaissance** purposes only. It is intended to assist security professionals and developers in assessing attack surfaces and evaluating plugin health. The authors are not responsible for any misuse. Always ensure you have appropriate authorization before performing any security-related activities.

---

<a href="https://www.star-history.com/#xeloxa/wp-hunter&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=xeloxa/wp-hunter&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=xeloxa/wp-hunter&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=xeloxa/wp-hunter&type=date&legend=top-left" />
 </picture>
</a>
