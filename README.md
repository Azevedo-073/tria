# 🎯 Tria

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Gemini](https://img.shields.io/badge/LLM-Gemini_2.0-4285F4?logo=google)](https://ai.google.dev/)
[![Obsidian](https://img.shields.io/badge/output-Obsidian-7C3AED?logo=obsidian)](https://obsidian.md/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#license)
[![Status](https://img.shields.io/badge/status-alpha-orange)]()

**Autonomous email triage agent.** Reads your inbox, classifies each email with AI, and writes a daily digest straight into your Obsidian vault.

> 💡 Instead of looking at your inbox 20 times a day, let an agent triage it and deliver a 5-line briefing to your second brain. Important stuff flagged, newsletters batched, spam ignored.

---

## ✨ Features

- 📬 **Gmail OAuth2** integration (read-only scope by default)
- 🧠 **LLM-powered classification** — Gemini 2.5 Flash by default, pluggable for Kimi K2, Claude, or local Ollama
- 📝 **Obsidian output** via Local REST API, writes markdown digests to your vault
- 💾 **SQLite state** — dedup processed emails, full run history for dashboard/analytics
- ⏰ **Scheduled runs** — Windows Task Scheduler (Windows) or systemd timer (Linux)
- 🏢 **Multi-tenant ready** — one `config.yaml` per client, isolated state
- 🔒 **Privacy-first** — sends only sender + subject + snippet to LLM (never full body), with regex redaction for CPF/CNPJ/cards

---

## 🏗️ Architecture

Three pluggable layers, interface-based:

```
Source (Gmail) → Classifier (Gemini) → Output (Obsidian)
                        ↓
                   SQLite state
```

Swap any layer by adding one file:
- New source → `tria/sources/outlook.py`
- New classifier → `tria/classifiers/kimi.py`
- New output → `tria/outputs/notion.py`

---

## 🚀 Quick Start

```bash
# 1. Clone and install
git clone https://github.com/Azevedo-073/tria.git
cd tria
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 2. Configure secrets
cp .env.example .env
# Edit .env with your Gemini API key, Obsidian API key, vault path

# 3. Download Gmail credentials.json from Google Cloud Console
# Place it in the project root

# 4. First run — triggers OAuth flow (opens browser)
python main.py run

# 5. (Optional) Schedule every 3 hours
python main.py schedule
```

---

## ⚙️ Configuration

Edit `config.yaml` to customize categories, frequency, privacy:

```yaml
tenant: marco

source:
  type: gmail
  lookback_hours: 3
  max_emails_per_run: 50

classifier:
  type: gemini
  model: model: gemini-2.5-flash

output:
  type: obsidian
  folder: 04-Daily notes/Emails

categories:
  - id: important
    emoji: "🔴"
    label: Importante
    description: "Banco, trabalho, pessoa real..."
```

---

## 🗺️ Roadmap

- [x] MVP CLI — Gmail → Gemini → Obsidian
- [x] SQLite state + dedup
- [x] Privacy redaction (CPF/CNPJ/cards)
- [ ] Web dashboard (FastAPI + HTMX) with run history + stats
- [ ] Ollama local classifier (LGPD-safe for B2B)
- [ ] Notion / Slack / webhook outputs
- [ ] Outlook source
- [ ] Docker image + systemd service
- [ ] Semantic search over classification history

---

## 👤 Author

**Marco Azevedo** · Logistics automation and AI agents · [LinkedIn](https://www.linkedin.com/in/marco-otávio-azevedo) · [GitHub](https://github.com/Azevedo-073)

---

## 📄 License

MIT
