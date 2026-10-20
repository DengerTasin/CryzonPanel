"""Database layer: schema, migrations, seeding and query helpers."""
import os
import sqlite3
import json
from datetime import datetime, timezone
from flask import g

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.path.join(BASE, "data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    permissions TEXT DEFAULT '[]',
    is_system INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    color TEXT DEFAULT '#6366f1',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    api_key TEXT,
    is_admin INTEGER DEFAULT 0,
    role_id INTEGER DEFAULT NULL,
    is_banned INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

CREATE TABLE IF NOT EXISTS vps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    node_id INTEGER DEFAULT NULL,
    container_id TEXT,
    container_name TEXT,
    ssh_command TEXT,
    ssh_password TEXT DEFAULT NULL,
    status TEXT DEFAULT 'creating',
    os_type TEXT DEFAULT 'ubuntu-22.04',
    ram TEXT DEFAULT '2GB',
    cpu TEXT DEFAULT '1 vCPU',
    disk TEXT DEFAULT '20GB',
    expires_at TIMESTAMP DEFAULT NULL,
    max_backups INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (node_id) REFERENCES nodes(id)
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    hostname TEXT NOT NULL,
    node_url TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    status TEXT DEFAULT 'online',
    vps_count INTEGER DEFAULT 0,
    max_vps INTEGER DEFAULT 500,
    cpu_usage REAL DEFAULT 0,
    ram_usage REAL DEFAULT 0,
    is_local INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS port_forwards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    vps_id INTEGER NOT NULL,
    local_port INTEGER NOT NULL,
    remote_port INTEGER NOT NULL,
    serveo_url TEXT,
    method TEXT DEFAULT 'socat',
    socat_pid INTEGER DEFAULT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    resource TEXT,
    details TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT DEFAULT 'info',
    message TEXT NOT NULL,
    source TEXT DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vps_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    image_name TEXT NOT NULL,
    size_mb REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vps_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vps_id INTEGER NOT NULL,
    shared_with INTEGER NOT NULL,
    shared_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vps_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vps_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    time TEXT NOT NULL,
    days TEXT DEFAULT 'everyday',
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT NULL,
    title TEXT NOT NULL,
    message TEXT DEFAULT '',
    level TEXT DEFAULT 'info',
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT DEFAULT 'CryzonCloud Cpanel',
    site_description TEXT DEFAULT 'High-Performance Cloud VPS Management Panel',
    footer_text TEXT DEFAULT 'Powered by CryzonCloud',
    timezone TEXT DEFAULT 'UTC',
    registration_enabled INTEGER DEFAULT 1,
    logo_url TEXT DEFAULT '',
    favicon_url TEXT DEFAULT '',
    cpu_threshold INTEGER DEFAULT 90,
    ram_threshold INTEGER DEFAULT 90,
    max_vps_per_user INTEGER DEFAULT 5,
    max_ports_per_user INTEGER DEFAULT 20,
    hostname_prefix TEXT DEFAULT 'cryzon',
    port_forwarding_method TEXT DEFAULT 'socat',
    public_ipv4 TEXT DEFAULT '',
    icon_path TEXT DEFAULT '',
    rate_limit_auth INTEGER DEFAULT 20,
    rate_limit_api INTEGER DEFAULT 120,
    rate_limit_heavy INTEGER DEFAULT 10,
    default_vps_days INTEGER DEFAULT 0
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=10000")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    last = cur.lastrowid
    cur.close()
    return last


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings():
    row = query("SELECT * FROM settings ORDER BY id LIMIT 1", one=True)
    if not row:
        execute("INSERT INTO settings (id) VALUES (1)")
        row = query("SELECT * FROM settings ORDER BY id LIMIT 1", one=True)
    return dict(row) if row else {}


def set_setting(key, value):
    execute(f"UPDATE settings SET {key} = ? WHERE id = (SELECT id FROM settings ORDER BY id LIMIT 1)", (value,))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def add_log(level, message, source="system"):
    execute("INSERT INTO system_logs (level, message, source) VALUES (?, ?, ?)", (level, message, source))


def log_activity(user_id, action, resource=None, details=None, ip=None):
    execute(
        "INSERT INTO activity_log (user_id, action, resource, details, ip_address) VALUES (?, ?, ?, ?, ?)",
        (user_id, action, resource, details, ip),
    )


def notify(user_id, title, message="", level="info"):
    execute(
        "INSERT INTO notifications (user_id, title, message, level) VALUES (?, ?, ?, ?)",
        (user_id, title, message, level),
    )


# ---------------------------------------------------------------------------
# Roles & permissions
# ---------------------------------------------------------------------------
def get_role(role_id):
    if role_id is None:
        return None
    row = query("SELECT * FROM roles WHERE id = ?", (role_id,), one=True)
    if not row:
        return None
    d = dict(row)
    try:
        d["permissions"] = json.loads(d.get("permissions") or "[]")
    except (ValueError, TypeError):
        d["permissions"] = []
    return d


def list_roles():
    rows = query("SELECT * FROM roles ORDER BY priority DESC, id ASC")
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["permissions"] = json.loads(d.get("permissions") or "[]")
        except (ValueError, TypeError):
            d["permissions"] = []
        out.append(d)
    return out


def seed_roles():
    from .security import ALL_PERMISSIONS
    if query("SELECT COUNT(*) c FROM roles", one=True)["c"] > 0:
        return
    defaults = [
        ("Owner", "owner", "Full unrestricted access to everything.", ALL_PERMISSIONS, 1, 100, "#f59e0b"),
        ("Admin", "admin", "Manage VPS, users, nodes and most settings.", [p for p in ALL_PERMISSIONS if p not in ("roles.manage", "settings.manage")], 1, 80, "#6366f1"),
        ("Staff", "staff", "Create and manage VPS, handle tickets.", [
            "dashboard.view", "vps.view", "vps.create", "vps.manage", "vps.console",
            "vps.files", "vps.processes", "users.view", "tickets.view", "tickets.manage",
            "logs.view", "stats.view",
        ], 1, 50, "#06b6d4"),
        ("User", "user", "Standard customer role.", [
            "dashboard.view", "vps.view", "vps.console", "vps.files", "vps.processes",
            "vps.backups", "vps.ports", "tickets.view",
        ], 1, 10, "#64748b"),
    ]
    for name, slug, desc, perms, sys, prio, color in defaults:
        execute(
            "INSERT INTO roles (name, slug, description, permissions, is_system, priority, color) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, slug, desc, json.dumps(perms), sys, prio, color),
        )


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
def init_db():
    os.makedirs(BASE, exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.executescript(SCHEMA)
    conn.commit()
    # Lightweight migrations for older databases
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in [
        ("is_banned", "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0"),
        ("role_id", "ALTER TABLE users ADD COLUMN role_id INTEGER DEFAULT NULL"),
    ]:
        if col not in cols:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
    conn.commit()
    conn.close()

    # Seed roles + default owner using an app context
    from flask import Flask
    tmp = Flask(__name__)
    with tmp.app_context():
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        seed_roles()
        from .security import hash_password
        owner = query("SELECT * FROM users WHERE id = 1", one=True)
        owner_role = query("SELECT id FROM roles WHERE slug='owner'", one=True)
        if not owner:
            execute(
                "INSERT INTO users (username, email, password, is_admin, role_id) VALUES (?, ?, ?, 1, ?)",
                ("admin", "admin@cryzoncloud.local", hash_password("admin123"), owner_role["id"] if owner_role else None),
            )
        else:
            if owner["role_id"] is None and owner_role:
                execute("UPDATE users SET role_id = ? WHERE id = 1", (owner_role["id"],))
        if not query("SELECT * FROM settings", one=True):
            execute("INSERT INTO settings (id) VALUES (1)")
        g.db.commit()
        g.db.close()
