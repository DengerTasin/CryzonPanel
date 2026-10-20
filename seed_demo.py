"""Populate the panel with realistic demo data for previews & screenshots.

Usage:
    CRYZON_DEMO=1 python seed_demo.py
"""
import os
import random
import json
from datetime import datetime, timedelta, timezone

os.environ.setdefault("CRYZON_DEMO", "1")

from ccp import create_app, db
from ccp.security import hash_password, generate_api_key

app = create_app()

random.seed(42)

OS = ["ubuntu-22.04", "ubuntu-24.04", "debian-12", "alpine-3.20"]
RAM = ["1GB", "2GB", "4GB", "8GB"]
CPU = ["1", "2", "4"]
DISK = ["20GB", "40GB", "80GB"]
STATUS = ["running", "running", "running", "stopped", "creating", "error"]


def reset():
    """Wipe demo tables (keeps schema + roles + owner)."""
    for tbl in ["vps", "port_forwards", "backups", "vps_shares", "tickets",
                "ticket_replies", "notifications", "activity_log", "system_logs",
                "vps_schedules"]:
        db.execute(f"DELETE FROM {tbl}")
    # remove non-owner users
    db.execute("DELETE FROM users WHERE id != 1")


def seed():
    with app.app_context():
        reset()

        owner = db.query("SELECT * FROM users WHERE id=1", one=True)
        owner_id = owner["id"]

        roles = {r["slug"]: r["id"] for r in db.list_roles()}
        admin_role = roles.get("admin")
        staff_role = roles.get("staff")
        user_role = roles.get("user")

        # ---- Users ----
        demo_users = [
            ("nova_admin", "nova@cryzoncloud.io", admin_role, 0),
            ("liam_staff", "liam@cryzoncloud.io", staff_role, 0),
            ("sara", "sara@example.com", user_role, 0),
            ("devon", "devon@example.com", user_role, 0),
            ("mika", "mika@example.com", user_role, 0),
            ("raj", "raj@example.com", user_role, 1),  # banned
        ]
        user_ids = [owner_id]
        for uname, email, rid, banned in demo_users:
            uid = db.execute(
                "INSERT INTO users (username, email, password, api_key, role_id, is_banned) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uname, email, hash_password("password123"), generate_api_key(), rid, banned),
            )
            user_ids.append(uid)

        # ---- Nodes ----
        nodes = [
            ("node-eu-1", "10.0.0.11", "", "", "online", 0, 500, 34.2, 51.8, 1),
            ("node-us-1", "10.0.0.21", "https://node-us.cryzoncloud.io:9000", "nodekey_us_1", "online", 0, 500, 62.5, 44.1, 0),
            ("node-asia-1", "10.0.0.31", "https://node-asia.cryzoncloud.io:9000", "nodekey_asia_1", "online", 0, 500, 18.9, 29.4, 0),
        ]
        node_ids = []
        for n in nodes:
            nid = db.execute(
                "INSERT INTO nodes (name, hostname, node_url, api_key, status, vps_count, max_vps, cpu_usage, ram_usage, is_local) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", n,
            )
            node_ids.append(nid)

        # ---- VPS ----
        vps_specs = [
            ("web-frontend-01", user_ids[2], node_ids[0], "running", "ubuntu-24.04", "4GB", "2", "40GB"),
            ("api-backend-02", user_ids[2], node_ids[0], "running", "ubuntu-22.04", "8GB", "4", "80GB"),
            ("db-primary-01", user_ids[3], node_ids[1], "running", "debian-12", "8GB", "4", "80GB"),
            ("cache-redis-01", user_ids[3], node_ids[1], "stopped", "alpine-3.20", "2GB", "1", "20GB"),
            ("staging-app-03", user_ids[4], node_ids[2], "running", "ubuntu-24.04", "4GB", "2", "40GB"),
            ("worker-queue-01", user_ids[4], node_ids[2], "creating", "ubuntu-22.04", "2GB", "2", "20GB"),
            ("legacy-box-09", user_ids[5], node_ids[0], "error", "debian-12", "1GB", "1", "20GB"),
            ("ml-trainer-01", owner_id, node_ids[1], "running", "ubuntu-24.04", "16GB", "8", "160GB"),
        ]
        vps_ids = []
        for name, uid, nid, status, os_type, ram, cpu, disk in vps_specs:
            ip = f"10.132.115.{random.randint(20, 240)}"
            days = random.choice([0, 30, 90, 365])
            expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else None
            vid = db.execute(
                "INSERT INTO vps (user_id, node_id, container_name, container_id, ssh_command, ssh_password, "
                "status, os_type, ram, cpu, disk, expires_at, max_backups) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, nid, name, name, f"ssh root@{ip}",
                 "".join(random.choices("abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789", k=12)),
                 status, os_type, ram, cpu, disk, expires, 5),
            )
            vps_ids.append(vid)

        # ---- Port forwards ----
        pf = [
            (user_ids[2], vps_ids[0], 80, 20080, "http://web-frontend-01.cryzon.cloud:20080", "active"),
            (user_ids[2], vps_ids[0], 443, 20443, "https://web-frontend-01.cryzon.cloud:20443", "active"),
            (user_ids[3], vps_ids[2], 5432, 25432, "tcp://db-primary-01.cryzon.cloud:25432", "active"),
            (user_ids[4], vps_ids[4], 3000, 23000, "http://staging-app-03.cryzon.cloud:23000", "active"),
        ]
        for uid, vid, lp, rp, url, st in pf:
            db.execute(
                "INSERT INTO port_forwards (user_id, vps_id, local_port, remote_port, serveo_url, method, status) "
                "VALUES (?, ?, ?, ?, ?, 'socat', ?)", (uid, vid, lp, rp, url, st),
            )

        # ---- Backups ----
        for vid in vps_ids[:5]:
            for i in range(random.randint(1, 3)):
                db.execute(
                    "INSERT INTO backups (vps_id, user_id, name, image_name, size_mb) VALUES (?, ?, ?, ?, ?)",
                    (vid, owner_id, f"backup-2025010{i}-1200", f"img-{vid}-{i}", round(random.uniform(120, 900), 1)),
                )

        # ---- Tickets + replies ----
        tickets = [
            (user_ids[2], "Cannot SSH into web-frontend-01", "open", [
                (user_ids[2], "I get 'connection refused' when trying to SSH. Can you check the firewall?", 0),
                (owner_id, "Thanks for reaching out — we're checking the node's NAT rules now.", 1),
            ]),
            (user_ids[3], "Request additional RAM for db-primary-01", "open", [
                (user_ids[3], "Our database is hitting memory limits. Can we upgrade to 16GB?", 0),
            ]),
            (user_ids[4], "Billing question about annual plan", "closed", [
                (user_ids[4], "Do you offer a discount for annual billing?", 0),
                (owner_id, "Yes! Annual plans save 20%. I've applied the discount to your account.", 1),
            ]),
            (user_ids[5], "Container stuck in error state", "open", [
                (user_ids[5], "legacy-box-09 has been in an error state for two days.", 0),
            ]),
        ]
        for uid, subj, status, replies in tickets:
            tid = db.execute("INSERT INTO tickets (user_id, subject, status) VALUES (?, ?, ?)", (uid, subj, status))
            for ruid, msg, is_admin in replies:
                db.execute(
                    "INSERT INTO ticket_replies (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, ?)",
                    (tid, ruid, msg, is_admin),
                )

        # ---- Notifications ----
        notifs = [
            (owner_id, "Welcome to CryzonCloud", "Your control panel is ready. Deploy your first container.", "success"),
            (owner_id, "Node node-asia-1 online", "A new compute node joined the fleet.", "info"),
            (user_ids[2], "VPS deployed", "Your VPS web-frontend-01 is ready.", "success"),
            (user_ids[3], "High memory usage", "db-primary-01 is using over 85% of its RAM.", "warning"),
            (user_ids[5], "Account suspended", "Your account has been suspended. Contact support.", "error"),
            (None, "Scheduled maintenance", "We'll perform maintenance on Sunday 02:00 UTC.", "info"),
        ]
        for uid, title, msg, level in notifs:
            db.execute("INSERT INTO notifications (user_id, title, message, level) VALUES (?, ?, ?, ?)", (uid, title, msg, level))

        # ---- System logs ----
        logs = [
            ("info", "Panel started successfully", "core"),
            ("info", "Node node-eu-1 registered", "node"),
            ("warning", "node-us-1 CPU usage above 60%", "monitor"),
            ("error", "Container legacy-box-09 failed to start", "lxd"),
            ("info", "Backup completed for db-primary-01", "backup"),
            ("info", "User nova_admin logged in", "auth"),
            ("warning", "Rate limit triggered for 203.0.113.44", "security"),
            ("info", "Port forward created (80 -> 20080)", "network"),
            ("info", "Role 'Staff' updated", "admin"),
            ("error", "SSH authentication failed for root@10.132.115.88", "auth"),
        ]
        for level, msg, src in logs:
            db.execute("INSERT INTO system_logs (level, message, source) VALUES (?, ?, ?)", (level, msg, src))

        # ---- Activity ----
        actions = [
            (owner_id, "create_role", "role", "Staff"),
            (user_ids[2], "create_vps", "vps", "web-frontend-01"),
            (user_ids[3], "vps_restart", "vps", "db-primary-01"),
            (user_ids[4], "create_ticket", "ticket", "Billing question"),
            (owner_id, "edit_settings", "settings", "site_name"),
            (user_ids[2], "login", "user", None),
            (owner_id, "user_set_role", "user", "liam_staff -> Staff"),
            (user_ids[5], "login", "user", None),
        ]
        for uid, action, res, det in actions:
            db.execute(
                "INSERT INTO activity_log (user_id, action, resource, details, ip_address) VALUES (?, ?, ?, ?, ?)",
                (uid, action, res, det, f"203.0.113.{random.randint(2, 250)}"),
            )

        db.execute("UPDATE nodes SET vps_count = (SELECT COUNT(*) FROM vps WHERE node_id = nodes.id)")

        print("Demo data seeded:")
        print("  users   :", db.query("SELECT COUNT(*) c FROM users", one=True)["c"])
        print("  vps     :", db.query("SELECT COUNT(*) c FROM vps", one=True)["c"])
        print("  nodes   :", db.query("SELECT COUNT(*) c FROM nodes", one=True)["c"])
        print("  tickets :", db.query("SELECT COUNT(*) c FROM tickets", one=True)["c"])
        print("  ports   :", db.query("SELECT COUNT(*) c FROM port_forwards", one=True)["c"])
        print("\nLogin: admin / admin123")


if __name__ == "__main__":
    seed()
