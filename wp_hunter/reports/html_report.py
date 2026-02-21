"""
WP-Hunter HTML Report Generator

Generate HTML, JSON, and CSV reports from scan results.
"""

import json
import csv
from typing import List, Dict, Any
from datetime import datetime

from wp_hunter.config import Colors


def generate_html_report(results: List[Dict[str, Any]]) -> str:
    """Generates a complete HTML report string from results."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    high_risk_count = sum(
        1
        for r in results
        if (
            r.get("relative_risk") in {"CRITICAL", "HIGH"}
            or (not r.get("relative_risk") and int(r.get("score", 0) or 0) >= 40)
        )
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>WP-Hunter Scan Results</title>
    <style>
        :root {{
            --bg-dark: #050505;
            --bg-panel: #0f0f11;
            --border-color: #222;
            --accent-primary: #00ff9d;
            --accent-secondary: #ff0055;
            --accent-blue: #00f3ff;
            --text-main: #e0e0e0;
            --text-muted: #666;
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            margin: 0; 
            padding: 20px;
            background-color: var(--bg-dark); 
            color: var(--text-main);
        }}
        
        h1 {{ 
            color: var(--accent-primary); 
            margin-bottom: 10px;
            font-size: 28px;
        }}
        
        .subtitle {{
            color: var(--text-muted);
            margin-bottom: 30px;
            font-size: 14px;
        }}
        
        .stats {{
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            min-width: 150px;
        }}
        
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: var(--accent-blue);
        }}
        
        .stat-value.high {{ color: var(--accent-secondary); }}
        
        .stat-label {{
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
        }}
        
        table {{ 
            width: 100%; 
            border-collapse: collapse; 
            background: var(--bg-panel);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        th, td {{ 
            padding: 12px; 
            text-align: left; 
            border-bottom: 1px solid var(--border-color); 
            font-size: 14px; 
        }}
        
        th {{ 
            background-color: #1a1a1a; 
            color: var(--accent-blue);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
        }}
        
        tr:hover {{ background-color: #151515; }}
        
        .score-high {{ color: var(--accent-secondary); font-weight: bold; }}
        .score-med {{ color: #f0ad4e; font-weight: bold; }}
        .score-low {{ color: var(--accent-primary); font-weight: bold; }}
        
        a {{ color: var(--accent-blue); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        
        .tag {{ 
            display: inline-block; 
            padding: 2px 8px; 
            font-size: 10px; 
            font-weight: bold; 
            color: white; 
            background-color: #333; 
            border-radius: 4px; 
            margin-right: 4px; 
        }}
        
        .tag-risk {{ background-color: var(--accent-secondary); }}
        .tag-safe {{ background-color: var(--accent-primary); color: #000; }}
        
        .plugin-name {{
            font-weight: 600;
            color: var(--text-main);
        }}
        
        .plugin-slug {{
            font-size: 11px;
            color: var(--text-muted);
            font-family: monospace;
        }}
        
        .links a {{
            margin-right: 10px;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <h1>🎯 WP-Hunter Reconnaissance Report</h1>
    <p class="subtitle">Generated: {timestamp} | Total Results: {len(results)}</p>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{len(results)}</div>
            <div class="stat-label">Total Plugins</div>
        </div>
        <div class="stat-card">
            <div class="stat-value high">{high_risk_count}</div>
            <div class="stat-label">High Risk</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{sum(1 for r in results if r.get("days_since_update", 0) > 730)}</div>
            <div class="stat-label">Abandoned</div>
        </div>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Name (Slug)</th>
                <th>Version</th>
                <th>Score</th>
                <th>Installs</th>
                <th>Updated</th>
                <th>Trusted Author</th>
                <th>Links</th>
            </tr>
        </thead>
        <tbody>
"""

    for res in results:
        score = int(res.get("score", 0) or 0)
        relative = str(res.get("relative_risk") or "").upper()
        if not relative:
            if score >= 65:
                relative = "CRITICAL"
            elif score >= 40:
                relative = "HIGH"
            elif score >= 20:
                relative = "MEDIUM"
            else:
                relative = "LOW"
        score_class = (
            "score-high"
            if relative in {"CRITICAL", "HIGH"}
            else ("score-med" if relative == "MEDIUM" else "score-low")
        )
        trusted = (
            '<span class="tag tag-safe">YES</span>'
            if res.get("author_trusted")
            else '<span class="tag">NO</span>'
        )

        html += f"""
            <tr>
                <td>
                    <div class="plugin-name">{res.get("name")}</div>
                    <div class="plugin-slug">{res.get("slug")}</div>
                </td>
                <td>{res.get("version")}</td>
                <td class="{score_class}">{score} <span style="font-size:11px; color:#777; margin-left:6px;">{relative}</span></td>
                <td>{res.get("installations"):,}+</td>
                <td>{res.get("days_since_update")} days ago</td>
                <td>{trusted}</td>
                <td class="links">
                    <a href="{res.get("wpscan_link")}" target="_blank">WPScan</a>
                    <a href="{res.get("cve_search_link")}" target="_blank">CVE</a>
                    <a href="{res.get("patchstack_link")}" target="_blank">Patchstack</a>
                    <a href="{res.get("wp_org_link", res.get("download_link"))}" target="_blank">WP.org</a>
                </td>
            </tr>"""

    html += """
        </tbody>
    </table>
</body>
</html>"""
    return html


def save_results(
    results: List[Dict[str, Any]], filename: str, format_type: str, verbose: bool = True
) -> bool:
    """Saves the collected results to a file."""
    if not results:
        if verbose:
            print(f"{Colors.YELLOW}[!] No results to save.{Colors.RESET}")
        return False

    try:
        with open(filename, "w", encoding="utf-8", newline="") as f:
            if format_type == "json":
                json.dump(results, f, indent=4)

            elif format_type == "csv":
                writer = csv.writer(f)
                headers = list(results[0].keys())
                writer.writerow(headers)
                for res in results:
                    writer.writerow([res.get(h, "") for h in headers])

            elif format_type == "html":
                f.write(generate_html_report(results))

        if verbose:
            print(f"{Colors.GREEN}[+] Results saved to {filename}{Colors.RESET}")
        return True

    except Exception as e:
        if verbose:
            print(f"{Colors.RED}[!] Error saving results: {e}{Colors.RESET}")
        return False
