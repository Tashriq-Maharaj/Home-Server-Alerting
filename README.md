# Ubuntu Server Monitoring & Alerting

A reliable, lightweight, real-time host monitoring and stress detection system built specifically for home server environments (Ubuntu Server 22.04.5 LTS / 4 logical CPUs).

Rather than simply dumping raw metrics or alerting on brief, transient spikes, this system correlates multiple hardware, kernel, and container signals to determine:
> **"Is my server actually under stress, why is it under stress, how serious is it, and when has it recovered?"**

---

## 📌 Key Capabilities

- **4-Core Aware Load & CPU Tracking:** Calibrated specifically for a 4 logical CPU host (Lenovo ThinkPad T440p). Differentiates between normal load, increasing contention (approaching 4.0), and serious bottlenecks (> 4.0).
- **Linux Pressure Stall Information (PSI):** Inspects `/proc/pressure/{cpu,memory,io}`. Distinguishes harmless high utilization from actual resource starvation where processes are actively stalling.
- **Cache-Aware Memory & Swap Monitoring:** Accounts for Linux page cache behavior. Evaluates genuinely available RAM (`MemAvailable`), memory pressure, and swap thrashing rates.
- **Disk Capacity & I/O Wait Contention:** Monitors filesystem capacity (`/` filesystem warning at 80%, critical at 90%) and detects heavy disk I/O bottlenecks and wait stalls.
- **Thermal Sensor Monitoring:** Checks CPU package and core thermal sensors (Intel `coretemp` / `thinkpad` ACPI) with graceful fallbacks if hardware sensors are absent.
- **Docker Container Health:** Directly monitors critical containers without requiring external daemons:
  - `Prometheus`, `Grafana`, `Node Exporter`, `SQL Server 2022`, `Plex`, `Plex Exporter`, `Portainer`, `SQL Exporter`
  - Detects stopped containers (non-zero exits) and crash-restarting loops.
- **Kernel Errors & OOM Kills:** Reads `/proc/vmstat` for kernel OOM-killer invocations, filesystem read-only remounts, and failed systemd units.
- **Intelligent Stress & Recovery State Machine:**
  - **No Alert Spam:** Rejects transient spikes; requires sustained stress (`stress_duration_seconds: 60s`).
  - **Hysteresis:** Recovery thresholds are lower than trigger thresholds to prevent flapping.
  - **Top Suspected Resource:** Identifies the primary bottleneck causing stress.
  - **Recovery Notifications:** Sends a concise recovery alert only when all stressed metrics return to normal for a sustained duration (`recovery_duration_seconds: 60s`).
- **Decoupled Notifiers:** Real-time **Telegram** Bot notifications (HTML-formatted) and optional **Email** (SMTP/TLS).

---

## 📁 Project Architecture

```text
Server_Alerting/
├── config/
│   └── config.default.json     # Calibrated thresholds & monitored containers
├── src/
│   ├── collectors/             # Individual metric collectors
│   │   ├── base.py             # Data models & collector base class
│   │   ├── cpu.py              # CPU %, user/sys, 4-core load averages
│   │   ├── memory.py           # RAM, MemAvailable, swap rates
│   │   ├── disk.py             # Mount point capacity (/), I/O rates, I/O wait
│   │   ├── psi.py              # Linux Pressure Stall Information (CPU, Mem, IO)
│   │   ├── thermal.py          # CPU package & core temperature
│   │   ├── docker_service.py   # Monitored Docker container health & restart loops
│   │   └── system_errors.py    # OOM kills, read-only fs, failed systemd units
│   ├── engine/                 # State machine & stress evaluation
│   │   ├── models.py           # HealthState, StressFactor, AlertPayload
│   │   ├── evaluator.py        # Multi-metric correlation & bottleneck analysis
│   │   └── state_machine.py    # Hysteresis, sustained duration, recovery tracking
│   ├── notifiers/              # Decoupled notification dispatch
│   │   ├── base.py             # Notifier interface & message formatting
│   │   ├── telegram.py         # Telegram Bot API (HTML formatted)
│   │   ├── email_notifier.py   # SMTP Email notifier
│   │   └── dispatcher.py       # Multi-notifier orchestrator
│   ├── config.py               # Strongly typed configuration & .env loader
│   └── monitor.py              # Main monitoring loop & signal handlers
├── systemd/
│   └── server-monitor.service  # Systemd service unit for Ubuntu Server
├── tests/                      # Full unit test suite (20 tests)
├── .env.example                # Template for credentials
├── requirements.txt            # Python dependencies (psutil, python-dotenv)
└── main.py                     # CLI entrypoint
```

---

## 🚀 Quick Start on Ubuntu Server

### 1. Prerequisites

On your Ubuntu host (`homeserver`):
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### 2. Clone and Setup Environment

```bash
cd /home/rick/Coding/Server_Alerting
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Telegram Bot Credentials

Copy the template:
```bash
cp .env.example .env
nano .env
```

Set your Telegram credentials:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=987654321
```

*(To get these: message [@BotFather](https://t.me/BotFather) on Telegram to create a bot, and [@userinfobot](https://t.me/userinfobot) to get your Chat ID.)*

### 4. Test Metric Collection & Notifications

**Run a single snapshot diagnostics check:**
```bash
python main.py --once
```

**Send a test alert to your Telegram chat:**
```bash
python main.py --test-notify
```

---

## 🛠️ Deploying as a Systemd Service

To ensure the monitor runs continuously, restarts automatically on reboots or failures, and logs to `journald`:

1. Copy the systemd service unit:
   ```bash
   sudo cp systemd/server-monitor.service /etc/systemd/system/
   ```

2. Reload systemd and enable the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now server-monitor.service
   ```

3. Check service status:
   ```bash
   sudo systemctl status server-monitor.service
   ```

4. Stream live logs via `journalctl`:
   ```bash
   journalctl -u server-monitor.service -f
   ```

---

## 📊 Alert Format Examples

### 🔴 Stress Detected Alert

Sent once when system stress is sustained for >= 60 seconds:

```text
🔴 Home Server Stress Detected

Duration: 2m 15s
Severity: CRITICAL
Host: homeserver

Load:
1m: 6.21 | 5m: 5.14 | 15m: 2.91
(Logical CPUs: 4)

CPU: 94.0% (Idle: 6.0%)
CPU Pressure: 38.2%
Temperature: 74.5°C

RAM: 86.9% used
Available RAM: 2.1 GB (13.1%)
Swap: 4.0% | Memory Pressure: 12.0%

Disk (/): 62.0% (190.0 GB free)
I/O Wait: 4.2% | I/O Pressure: 31.0%

Top suspected resource:
CPU / system load

Contributing factors:
• Load 1m critically high: 6.21 (capacity: 4 CPUs)
• Severe CPU stall pressure: 38.2% PSI avg10

Monitoring continues...
```

### 🟢 Recovery Alert

Sent when all metrics that caused the stress have returned below the recovery thresholds for >= 60 seconds:

```text
🟢 Home Server Recovered

Stress duration: 7m 42s
Host: homeserver

Current state:
CPU: 18.2%
Load (1m): 0.74 (Capacity: 4 CPUs)
RAM Available: 7.4 GB (62.1%)
Swap: 4.0%
I/O Pressure: Normal

System resources have returned to normal operating thresholds.
```

---

## ⚙️ Configuration & Threshold Reference

All non-secret thresholds are configured in `config/config.default.json`:

| Category | Metric | Warning | Critical | Recovery Threshold |
| :--- | :--- | :--- | :--- | :--- |
| **Load** | 1m Load Average | `3.8` | `5.5` | `<= 2.8` |
| **Load** | 5m Load Average | `3.4` | `4.5` | `<= 2.5` |
| **CPU** | Overall Utilization | `85.0%` | `95.0%` | `<= 70.0%` |
| **Linux PSI** | CPU Pressure (avg10) | `15.0%` | `35.0%` | `<= 5.0%` |
| **Memory** | Available RAM | `< 1500 MB` (`15%`) | `< 700 MB` (`8%`) | `>= 20.0%` |
| **Memory** | Memory PSI (avg10) | `10.0%` | `25.0%` | `<= 3.0%` |
| **Swap** | Swap Utilization | `50.0%` | `80.0%` | `<= 40.0%` |
| **Disk** | `/` Mount Usage | `80.0%` | `90.0%` | `<= 78.0%` |
| **Disk I/O** | CPU I/O Wait | `15.0%` | `30.0%` | `<= 8.0%` |
| **Disk I/O** | I/O Pressure (avg10) | `15.0%` | `35.0%` | `<= 5.0%` |
| **Thermal** | CPU Package Temp | `80.0°C` | `90.0°C` | `<= 72.0°C` |

---

## 🧪 Testing & Simulation

### 1. Automated Unit Tests
Run the complete automated unit test suite:
```bash
python -m unittest discover tests
```
All 21 tests validate metric collectors, PSI parsing, multi-signal correlation, deduplication, cooldowns, and recovery state transitions.

---

### 2. Scenario Simulation Runner (`simulate.py`)
To test real stress and recovery cycles **safely without overloading your physical server**:

```bash
# Test sustained CPU & load stress and recovery:
python simulate.py --scenario cpu

# Test Docker container failure & recovery:
python simulate.py --scenario docker

# Test RAM exhaustion & swap pressure:
python simulate.py --scenario memory

# Verify transient spike filtering (anti-false-alarm check):
python simulate.py --scenario transient
```

#### Send Real Alerts to Telegram during Simulation:
Add the `--notify` flag to dispatch the simulated alert and recovery messages directly to your Telegram chat:
```bash
python simulate.py --scenario cpu --notify
python simulate.py --scenario docker --notify
```

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).
