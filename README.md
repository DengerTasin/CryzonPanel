# ☁️ CryzonCloud Cpanel

A modern, self-hosted **VPS / container control panel** built on **LXC / LXD**.
Provision containers with **dedicated RAM, disk (ROM) and CPU cores**, manage them
from a glassmorphic dark UI with smooth animations, open a **direct web console**
straight into the container's terminal, and run a full **role-based admin panel**
with a granular permission system.

```
   ______                 ______                 __
  / ____/_____ __  __ ____/ ____/___  __  ______/ /
 / /   / ___/ / / /_/_  / /   / __ \/ / / / __  /
/ /___/ /  / /_/ /  / /_/ /___/ /_/ / /_/ / /_/ /
\____/_/   \__, /\___/\____/\____/\__,_/\__,_/
          /____/        Cpanel  v3
```

---

## ✨ Features

| Area | Highlights |
|------|------------|
| **Containers** | LXC/LXD backed, dedicated **RAM / disk / CPU cores**, multi-node routing, demo mode |
| **Console** | Direct **web terminal** (xterm.js + server-side PTY) into any container |
| **Admin panel** | Dedicated admin area — overview, VPS, users, nodes, settings, logs |
| **Roles** | Create **Owner / Admin / Staff / custom** roles with a fine-grained permission matrix |
| **Permissions** | 30+ granular permissions grouped by area (create-only, manage-only, full, …) |
| **Users** | Registration, sessions, ban/unban, per-user roles, API keys |
| **Ops** | Backups, port forwarding, file manager, process manager, schedules, expiry |
| **Support** | Ticket system with threaded replies |
| **UI/UX** | Glassmorphism, animated orbs, counters, reveal-on-scroll, ripples, toasts, live stats |
| **Security** | PBKDF2-SHA256 (240k iters), rate limiting, CSRF-safe sessions, API-key auth for nodes |

---

## 🚀 Quick start (demo mode — no LXD required)

Demo mode simulates containers so you can explore the full UI anywhere.

```bash
cd cryzoncloud
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# (optional) load realistic sample data
CRYZON_DEMO=1 ./venv/bin/python seed_demo.py

# run
CRYZON_DEMO=1 ./venv/bin/python app.py
```

Open **http://localhost:8080** and log in with:

```
username: admin
password: admin123
```

> ⚠️ Change the default password immediately after first login (Profile → Update).

---

## 🛠️ Production install (with LXD)

One-shot installer for a fresh Debian/Ubuntu host. It installs LXD (snap), creates a
service user, sets up a virtualenv, and registers a **systemd** service.

```bash
sudo ./setup.sh                 # full install: LXD + panel + systemd
sudo ./setup.sh --demo          # panel only, demo mode (no LXD)
sudo ./setup.sh --no-systemd    # skip the systemd unit
```

Then visit `http://<server-ip>:8080` and log in with `admin / admin123`.

Manage the service:

```bash
systemctl status cryzoncloud
journalctl -u cryzoncloud -f
```

---

## 🌐 Adding a node

Turn any host into a CryzonCloud node so the panel can spread containers across
machines.

1. In the panel go to **Admin → Nodes** and note / generate the **API key**.
2. On the target host run:

```bash
sudo ./setup_node.sh --key <API_KEY> --port 7000
```

3. Register the node in **Admin → Nodes** with its address
   `http://<node-ip>:7000` and the same API key.

The node agent (`node.py`) authenticates every request with the `X-API-Key`
header and exposes container lifecycle endpoints.

---

## 🗂️ Project layout

```
cryzoncloud/
├── app.py                 # entry point (dev server / gunicorn target)
├── node.py                # node agent (runs on remote nodes)
├── setup.sh               # control-panel installer
├── setup_node.sh          # node-agent installer
├── seed_demo.py           # sample data generator
├── requirements.txt       # panel dependencies
├── node_requirements.txt  # node dependencies
├── ccp/                   # the application package
│   ├── __init__.py        # app factory, context processors, filters
│   ├── db.py              # SQLite schema, migrations, helpers, role seeding
│   ├── security.py        # password hashing, permission catalog, decorators
│   ├── lxd.py             # LXD client + node routing + parsers
│   ├── containers.py      # demo-mode container simulation
│   ├── terminal.py        # PTY web-terminal sessions
│   ├── routes.py          # user blueprint (main)
│   ├── routes_admin.py    # admin blueprint (/admin)
│   └── routes_api.py      # JSON API blueprint (/api)
├── static/
│   ├── css/style.css      # design system
│   └── js/app.js          # UI interactions & animations
└── templates/             # Jinja2 templates (user + admin/)
```

---

## 🔐 Roles & permissions

The heart of the admin panel. Every role is a set of permissions drawn from a
catalog grouped into **General, VPS / Containers, Users, Roles, Nodes, Support,
System**.

Seeded roles:

| Role | Priority | Description |
|------|----------|-------------|
| **Owner** | 100 | Full access — always every permission |
| **Admin** | 80 | Everything except managing roles & panel settings |
| **Staff** | 50 | Day-to-day operations (view/manage VPS, support) |
| **User** | 10 | Self-service: own containers, console, tickets |

### Creating a custom role

Go to **Admin → Roles & Permissions → Create role**, then tick exactly the
capabilities you want. Examples:

- **Create-only** → `vps.create` (can deploy, cannot start/stop/delete)
- **Manage-only** → `vps.manage` + `vps.console` (operates existing VPS)
- **Create + Manage (full)** → tick everything in the VPS group
- **Support agent** → `tickets.view` + `tickets.manage` + `users.view`

The permission matrix shows a live counter per group and a grand total, and the
Owner role is protected (cannot be stripped or deleted).

---

## 🖥️ Direct console

Each container has a **Console** tab that opens an interactive terminal in the
browser. It is powered by:

- a server-side **PTY** session (`ccp/terminal.py`) that attaches to the
  container shell,
- a **512 KB ring buffer** per session so output survives reconnects,
- **xterm.js** on the frontend, wired to `/api/vps/<id>/terminal/{open,input,read,resize,close}`.

This works under WSGI/gunicorn (no websockets required).

---

## 🔌 JSON API

All endpoints live under `/api` and can be authenticated with a session or an
API key (`X-API-Key`):

```
GET  /api/health                 panel + node health
GET  /api/stats                  aggregate statistics
GET  /api/vps                    list your containers
GET  /api/vps/<id>/stats         live cpu / ram / disk / processes
GET  /api/notifications          notifications feed
POST /api/notifications/read     mark all read
GET  /api/nodes                  node list
GET  /api/me                     current user + permissions
```

---

## ⚙️ Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CRYZON_HOST` | `0.0.0.0` | Bind address |
| `CRYZON_PORT` | `8080` | Bind port |
| `CRYZON_DEMO` | `0` | `1` = simulate containers (no LXD) |
| `CRYZON_DEBUG` | `0` | `1` = Flask debug mode |
| `CRYZON_USER` | `cryzon` | Service user (installers) |
| `CRYZON_NODE_PORT` | `7000` | Node agent port |
| `CRYZON_NODE_KEY` | — | Node agent API key |

---

## 🧰 Tech stack

- **Backend:** Python 3.11, Flask 3, Flask-Limiter, SQLite (WAL), psutil, requests
- **Containers:** LXC / LXD (snap)
- **Frontend:** Jinja2, hand-written CSS design system, vanilla JS, xterm.js
- **Serving:** gunicorn (threaded)

---

## 📄 License

Provided as-is for self-hosted use. Review and harden before exposing to the
public internet (TLS via a reverse proxy, strong passwords, firewall, backups).
