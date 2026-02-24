<div align="center">
  <img src="assets/banner.png" alt="WP-Hunter Banner" width="600"/>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License MIT">
  <img src="https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey" alt="Platform">
</p>

<p align="center">
  <a href="https://www.producthunt.com/products/wp-hunter?embed=true&utm_source=badge-featured&utm_medium=badge&utm_campaign=badge-wp-hunter" target="_blank" rel="noopener noreferrer"><img alt="WP-Hunter - WP plugin recon & SAST tool for security researchers. | Product Hunt" width="220" height="48" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1084875&theme=light&t=1771939449742"></a>
</p>

<p align="center">
  <b>🌐 选择语言:</b><br>
  <a href="README.md"><img src="https://img.shields.io/badge/🇬🇧-English-blue" alt="English"></a>
  <a href="README.tr.md"><img src="https://img.shields.io/badge/🇹🇷-Türkçe-red" alt="Türkçe"></a>
  <a href="README.zh.md"><img src="https://img.shields.io/badge/🇨🇳-简体中文-yellow" alt="简体中文"></a>
  <a href="README.ar.md"><img src="https://img.shields.io/badge/🇸🇦-العربية-green" alt="العربية"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪-Deutsch-orange" alt="Deutsch"></a>
</p>

WP-Hunter 是一个 **WordPress 插件/主题侦察和静态分析 (SAST) 工具**。它专为**安全研究人员**设计，通过分析元数据、安装模式、更新历史记录以及执行深度 **Semgrep 驱动的源代码分析** 来评估插件的**漏洞概率**。

## 🚀 主要功能

*   **实时 Web 仪表板**: 用于可视扫描和分析的现代 FastAPI 驱动界面。
*   **深度 SAST 集成**: 集成 **Semgrep** 扫描，支持自定义规则。
*   **离线侦察**: 将整个 WordPress 插件目录同步到本地 SQLite 数据库以进行即时查询。
*   **风险评分 (VPS)**: 基于启发式的评分，用于识别 WordPress 生态系统中的"唾手可得的果实"。
*   **主题分析**: 支持扫描 WordPress 主题存储库。
*   **安全加固**: 内置 SSRF 保护和安全执行模式。

---

## 🖥️ 现代 Web 仪表板

WP-Hunter 现在为视觉研究人员提供了一个强大的本地仪表板。

### 仪表板画廊

<table>
  <tr>
    <td width="50%">
      <b>主界面</b><br>
      使用直观的控件配置扫描参数
    </td>
    <td width="50%">
      <b>扫描历史</b><br>
      跟踪和管理所有以前的扫描
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/dashboard-main.png" alt="主仪表板" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/scan-history.png" alt="扫描历史" width="100%"/>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>Semgrep 扫描详情</b><br>
      带有问题跟踪的深度 SAST 分析
    </td>
    <td width="50%">
      <b>安全规则集</b><br>
      管理 OWASP 和自定义 Semgrep 规则
    </td>
  </tr>
  <tr>
    <td>
      <img src="assets/screenshots/scan-details.png" alt="扫描详情" width="100%"/>
    </td>
    <td>
      <img src="assets/screenshots/security-rulesets.png" alt="安全规则集" width="100%"/>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <b>CLI 输出</b><br>
      具有丰富的漏洞情报的终端界面
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <img src="assets/screenshots/cli-output.png" alt="CLI 输出" width="100%"/>
    </td>
  </tr>
</table>

### 仪表板功能：
*   **实时执行序列**: 通过 WebSocket 观看扫描结果流式传输。
*   **集成 Semgrep**: 一键运行深度静态分析。
*   **扫描历史**: 保存并比较以前的扫描会话。
*   **收藏系统**: 跟踪"有趣"的目标以供进一步手动审查。
*   **自定义规则**: 直接从 UI 添加和管理您自己的 Semgrep 安全规则。

---

## 📦 安装

### 先决条件
- Python 3.8 或更高版本
- pip (Python 包安装程序)
- [Semgrep](https://semgrep.dev/docs/getting-started/) (可选，用于深度分析)

### 设置
1. 克隆仓库：
```bash
git clone https://github.com/xeloxa/WP-Hunter.git
cd WP-Hunter
```
2. 创建并激活虚拟环境：
```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```
3. 安装依赖项：
```bash
pip install -r requirements.txt
```

---

## 🛠️ 用法

### 1. 启动 Web 仪表板 (推荐)
```bash
python3 wp-hunter.py --gui
```
在 `http://localhost:8080` 访问界面。

### 2. 数据库同步 (用于离线侦察)
使用插件元数据填充您的本地数据库：
```bash
# 同步前 100 页插件
python3 wp-hunter.py --sync-db --sync-pages 100

# 同步整个 WordPress 目录 (~60k 插件)
python3 wp-hunter.py --sync-all
```

### 3. 本地数据库查询
在不访问 WordPress API 的情况下查询您的本地数据库：
```bash
# 查找 10k+ 安装且 2 年未更新的插件
python3 wp-hunter.py --query-db --min 10000 --abandoned

# 搜索包含"form"且评分较低的插件
python3 wp-hunter.py --query-db --search "form" --sort-by rating --sort-order asc
```

### 4. CLI 扫描 (经典模式)
```bash
# 扫描 10 页更新的插件并启用 Semgrep 分析
python3 wp-hunter.py --pages 10 --semgrep-scan --limit 20
```

---

## 🎯 Hunter 策略

### 1. "僵尸"狩猎 (高成功率)
针对广泛使用但被放弃的插件。
*   **逻辑：** 旧代码通常缺乏现代安全标准 (缺少 nonces，弱清理)。
*   **命令：** `python3 wp-hunter.py --abandoned --min 1000 --sort popular`

### 2. "激进"模式
用于大范围、高并发的高速侦察。
*   **命令：** `python3 wp-hunter.py --aggressive --pages 200`

### 3. "复杂性"陷阱
针对中等规模插件中的复杂功能 (文件上传、支付)。
*   **命令：** `python3 wp-hunter.py --smart --min 500 --max 10000`

---

## 📊 VPS 逻辑 (漏洞概率评分)
评分 (0-100) 反映 **未修补** 或 **未知** 漏洞的可能性：

| 指标 | 条件 | 影响 | 推理 |
|------|------|------|------|
| **代码腐烂** | > 2 年旧 | **+40 分** | 被放弃的代码是关键风险。 |
| **攻击面** | 风险标签 | **+30 分** | 支付、上传、SQL、表单具有高复杂性。 |
| **忽视** | 支持 < 20% | **+15 分** | 忽视用户的开发人员可能忽视安全报告。 |
| **代码分析** | 危险函数 | **+5-25 分** | 存在 `eval()`、`exec()` 或未受保护的 AJAX。 |
| **技术债务** | 过时的 WP | **+15 分** | 未使用最新的 WordPress 核心进行测试。 |
| **维护** | 更新 < 14 天 | **-5 分** | 积极的开发人员是一个积极信号。 |

---

## ⚖️ 法律免责声明

此工具专为 **安全研究和授权侦察** 目的而设计。它旨在协助安全专业人员和开发人员评估攻击面并评估插件健康状况。作者对任何滥用行为不承担责任。在执行任何与安全相关的活动之前，请务必确保您拥有适当的授权。
