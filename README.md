# Apache Log Monitor

A real-time Apache web server log monitoring dashboard built with Flask and vanilla JavaScript.
Stream, filter, and analyze Apache access and error logs from **local and remote servers** — all in one browser tab.

---

## Features

- **Live log streaming** via Server-Sent Events (SSE) — no polling, no page refresh
- **Multi-server support** — connect remote Linux servers using the lightweight log agent
- **Server selector** — switch between local and remote server log streams from the GUI
- **Log file selector** — monitor access logs, error logs, or any `*.log` file in the log directory
- **Real-time filters** — filter by severity level (info / warn / error), HTTP status group (4xx / 5xx), and keyword search with live highlighting
- **Auto-scroll** — always follow the latest log lines
- **AI analysis** — send the last 20 log lines to Claude for instant analysis (optional, requires Anthropic API key)
- **Log rotation safe** — uses `tail -F` so streams continue seamlessly after log rotation

---

## Architecture

```
Remote Server A          Remote Server B
┌──────────────┐         ┌──────────────┐
│ log_agent.py │         │ log_agent.py │
│ tails logs   │         │ tails logs   │
└──────┬───────┘         └──────┬───────┘
       │  POST /api/agent/push  │
       ▼                        ▼
┌──────────────────────────────────────┐
│       Central Flask Server           │
│  AgentRegistry (per-server queues)   │
│  SSE: /api/stream/<server>/<log>     │
└─────────────────┬────────────────────┘
                  │ SSE
                  ▼
            Browser GUI
          (server selector)
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/rrakeshamd/apache-logmonitoring.git
cd apache-logmonitoring
python3 -m venv venv
source venv/bin/activate

# On WSL2 / systems with SSL cert issues:
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org Flask python-dotenv

# On normal systems:
pip install Flask python-dotenv
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set LOG_DIR, AGENT_SECRET, and optionally ANTHROPIC_API_KEY
```

### 3. Run

```bash
python3 run.py
# App available at http://localhost:5001
```

### 4. Test without a live Apache server

```bash
# Terminal 1 — start app pointed at test logs
LOG_ACCESS=/tmp/test_access.log LOG_ERROR=/tmp/test_error.log python3 run.py

# Terminal 2 — generate synthetic Apache logs
python3 tools/simulate_logs.py --access /tmp/test_access.log --error /tmp/test_error.log
```

---

## Remote Server Agent (v2)

Install the log agent on any Linux server to stream its Apache logs to the central dashboard.

### On the remote server

```bash
# Copy the agent script (no extra dependencies — stdlib only)
scp agent/log_agent.py user@remote-server:/opt/log_agent.py

# Run the agent
python3 /opt/log_agent.py \
  --server web-01 \
  --server-url http://<CENTRAL_SERVER_IP>:5001 \
  --agent-key changeme \
  --logs access:/var/log/apache2/access.log \
  --logs error:/var/log/apache2/error.log
```

### In the GUI

- The **Server** dropdown auto-updates every 10 seconds as agents connect
- Select a remote server to switch the log stream to that server
- Switch back to **Local** at any time

### Running as a systemd service (recommended)

```ini
# /etc/systemd/system/log-agent.service
[Unit]
Description=Apache Log Monitor Agent
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/log_agent.py \
  --server web-01 \
  --server-url http://192.168.1.100:5001 \
  --agent-key changeme \
  --logs access:/var/log/apache2/access.log \
  --logs error:/var/log/apache2/error.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now log-agent
```

---

## Configuration

All settings are controlled via `.env`:

| Variable | Default | Description |
|---|---|---|
| `LOG_DIR` | `/var/log/apache2` | Directory scanned for `*.log` files (local logs) |
| `AGENT_SECRET` | `changeme` | Shared secret — agents must send this in `X-Agent-Key` header |
| `LLM_ENABLED` | `false` | Enable AI log analysis |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required when `LLM_ENABLED=true` |
| `LLM_MODEL` | `claude-3-5-haiku-20241022` | Claude model to use for analysis |
| `LLM_CHUNK_SIZE` | `20` | Number of log lines sent to Claude per analysis request |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret |
| `FLASK_ENV` | `development` | `development` or `production` |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/config` | App config — available log names, LLM status |
| `GET` | `/api/stream/<log_name>` | SSE stream for a local log |
| `GET` | `/api/stream/<server>/<log_name>` | SSE stream for a remote agent's log |
| `GET` | `/api/servers` | List of connected remote servers |
| `GET` | `/api/servers/<server>/logs` | Log names available for a remote server |
| `POST` | `/api/agent/push` | Receive a log line from a remote agent |
| `GET` | `/api/logs` | List local log files with paths and sizes |
| `POST` | `/api/refresh` | Rescan `LOG_DIR` for new log files |
| `POST` | `/api/analyze` | Analyze log lines with Claude AI |

---

## Project Structure

```
apache-logmonitoring/
├── agent/
│   └── log_agent.py          # Remote server agent (install on each server)
├── app/
│   ├── __init__.py            # Flask app factory
│   ├── config.py              # Configuration
│   ├── routes/
│   │   ├── main.py            # UI route
│   │   └── api.py             # REST + SSE API
│   ├── services/
│   │   ├── agent_registry.py  # In-memory queues for remote agents
│   │   ├── log_tailer.py      # Local log file tailing
│   │   ├── log_parser.py      # Apache log line parsing
│   │   └── llm_hook.py        # Claude AI integration
│   ├── static/
│   │   ├── css/app.css        # Dark theme styles
│   │   └── js/app.js          # Frontend SPA logic
│   └── templates/
│       └── index.html         # Single-page UI
├── tools/
│   └── simulate_logs.py       # Test log generator
├── .env.example               # Configuration template
├── requirements.txt           # Python dependencies
└── run.py                     # Entry point
```

---

## Changelog

### v2.0 — Remote Agent Support
- **New:** `agent/log_agent.py` — lightweight agent for remote Linux servers (stdlib only, no pip required)
- **New:** `AgentRegistry` — server-side registry managing per-agent log queues
- **New:** Server selector dropdown in the GUI — switch between local and remote servers
- **New:** `/api/agent/push` endpoint to receive log lines from agents
- **New:** `/api/stream/<server>/<log>` SSE endpoint for remote log streams
- **New:** `/api/servers` and `/api/servers/<server>/logs` endpoints
- Agents auto-appear in the GUI within 10 seconds of connecting

### v1.0 — Initial Release
- Real-time local Apache log streaming via SSE
- Access and error log parsing
- Level, status, and keyword filters
- Optional Claude AI log analysis
- Log rotation support via `tail -F`
- Bootstrap 5 dark-theme UI

---

## Requirements

- Python 3.8+
- Linux (uses `tail` and `stdbuf` commands)
- Apache (or use the log simulator for testing)
- Anthropic API key (optional, for AI analysis)
