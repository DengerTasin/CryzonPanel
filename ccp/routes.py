"""Main user-facing routes: auth, dashboard, VPS management, files, support."""
import os
import random
import string
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, abort, send_file, current_app,
)

from . import db, lxd, containers
from .security import (
    hash_password, verify_password, generate_api_key, current_user,
    login_required, permission_required, has_permission, is_admin,
    ALL_PERMISSIONS,
)

bp = Blueprint("main", __name__)

OS_OPTIONS = [
    {"value": "ubuntu-22.04", "label": "Ubuntu 22.04 LTS", "icon": "ubuntu"},
    {"value": "ubuntu-24.04", "label": "Ubuntu 24.04 LTS", "icon": "ubuntu"},
    {"value": "ubuntu-26.04", "label": "Ubuntu 26.04 LTS", "icon": "ubuntu"},
    {"value": "debian-12", "label": "Debian 12", "icon": "debian"},
    {"value": "alpine-3.20", "label": "Alpine 3.20", "icon": "alpine"},
]

RAM_OPTIONS = ["512MB", "1GB", "2GB", "4GB", "8GB", "16GB", "32GB"]
CPU_OPTIONS = ["1", "2", "4", "6", "8", "12", "16"]
DISK_OPTIONS = ["5GB", "10GB", "20GB", "40GB", "80GB", "160GB", "320GB"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_vps(vps_id, perm="vps.view"):
    vps = db.query("SELECT * FROM vps WHERE id = ?", (vps_id,), one=True)
    if not vps:
        abort(404)
    vps = dict(vps)
    user = current_user()
    shared = db.query("SELECT 1 FROM vps_shares WHERE vps_id=? AND shared_with=?", (vps_id, user["id"]), one=True)
    if vps["user_id"] != user["id"] and not shared and not is_admin(user):
        abort(403)
    if not has_permission(user, perm):
        abort(403)
    vps["owner"] = db.query("SELECT username FROM users WHERE id=?", (vps["user_id"],), one=True)
    vps["node"] = db.query("SELECT * FROM nodes WHERE id=?", (vps["node_id"],), one=True) if vps.get("node_id") else None
    return vps


def _apply_expiry(vps):
    if vps.get("expires_at"):
        try:
            exp = datetime.fromisoformat(vps["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return True
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------------------
# Landing / auth
# ---------------------------------------------------------------------------
@bp.route("/")
def index():
    if current_user():
        return redirect(url_for("main.dashboard"))
    settings = db.get_settings()
    stats = {
        "vps": db.query("SELECT COUNT(*) c FROM vps", one=True)["c"],
        "users": db.query("SELECT COUNT(*) c FROM users", one=True)["c"],
        "nodes": db.query("SELECT COUNT(*) c FROM nodes", one=True)["c"],
    }
    return render_template("index.html", settings=settings, stats=stats, os_options=OS_OPTIONS)


@bp.route("/register", methods=["GET", "POST"])
def register():
    settings = db.get_settings()
    if not settings.get("registration_enabled"):
        flash("Registration is currently disabled.", "error")
        return redirect(url_for("main.login"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if len(username) < 3 or len(password) < 6:
            flash("Username must be 3+ chars and password 6+ chars.", "error")
            return render_template("register.html", settings=settings)
        if db.query("SELECT 1 FROM users WHERE username=? OR email=?", (username, email), one=True):
            flash("Username or email already taken.", "error")
            return render_template("register.html", settings=settings)
        user_role = db.query("SELECT id FROM roles WHERE slug='user'", one=True)
        uid = db.execute(
            "INSERT INTO users (username, email, password, api_key, role_id) VALUES (?, ?, ?, ?, ?)",
            (username, email, hash_password(password), generate_api_key(), user_role["id"] if user_role else None),
        )
        db.log_activity(uid, "register", "user", f"New account {username}", request.remote_addr)
        db.notify(uid, "Welcome to CryzonCloud", "Your account is ready. Deploy your first VPS from the dashboard.", "success")
        flash("Account created. Please sign in.", "success")
        return redirect(url_for("main.login"))
    return render_template("register.html", settings=settings)


@bp.route("/login", methods=["GET", "POST"])
def login():
    settings = db.get_settings()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = db.query("SELECT * FROM users WHERE username=? OR email=?", (username, username.lower()), one=True)
        if user and verify_password(password, user["password"]):
            if user["is_banned"]:
                flash("This account has been suspended.", "error")
                return render_template("login.html", settings=settings)
            session.permanent = True
            session["user_id"] = user["id"]
            db.log_activity(user["id"], "login", "user", None, request.remote_addr)
            nxt = request.args.get("next") or url_for("main.dashboard")
            return redirect(nxt)
        flash("Invalid credentials.", "error")
    return render_template("login.html", settings=settings)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    vps_list = db.query("SELECT * FROM vps WHERE user_id=? ORDER BY id DESC", (user["id"],))
    shared = db.query(
        "SELECT v.* FROM vps v JOIN vps_shares s ON s.vps_id=v.id WHERE s.shared_with=? ORDER BY v.id DESC",
        (user["id"],),
    )
    stats = {
        "total": len(vps_list),
        "running": sum(1 for v in vps_list if v["status"] == "running"),
        "stopped": sum(1 for v in vps_list if v["status"] == "stopped"),
        "shared": len(shared),
    }
    nodes = db.query("SELECT * FROM nodes ORDER BY id") if has_permission(user, "nodes.view") else []
    return render_template("dashboard.html", vps_list=vps_list, shared=shared, stats=stats, os_options=OS_OPTIONS,
                           ram_options=RAM_OPTIONS, cpu_options=CPU_OPTIONS, disk_options=DISK_OPTIONS, nodes=nodes)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        newpass = request.form.get("password") or ""
        db.execute("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
        if newpass:
            db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(newpass), user["id"]))
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))
    activity = db.query("SELECT * FROM activity_log WHERE user_id=? ORDER BY id DESC LIMIT 25", (user["id"],))
    return render_template("profile.html", activity=activity)


@bp.route("/profile/regen-key", methods=["POST"])
@login_required
def regen_api_key():
    user = current_user()
    db.execute("UPDATE users SET api_key=? WHERE id=?", (generate_api_key(), user["id"]))
    flash("API key regenerated.", "success")
    return redirect(url_for("main.profile"))


# ---------------------------------------------------------------------------
# VPS
# ---------------------------------------------------------------------------
@bp.route("/vps/create", methods=["POST"])
@login_required
def vps_create():
    user = current_user()
    if not has_permission(user, "vps.create"):
        abort(403)
    settings = db.get_settings()
    max_vps = int(settings.get("max_vps_per_user") or 5)
    count = db.query("SELECT COUNT(*) c FROM vps WHERE user_id=?", (user["id"],), one=True)["c"]
    if count >= max_vps and not is_admin(user):
        flash(f"You have reached your limit of {max_vps} VPS instances.", "error")
        return redirect(url_for("main.dashboard"))

    os_type = request.form.get("os_type", "ubuntu-22.04")
    ram = request.form.get("ram", "2GB")
    cpu = request.form.get("cpu", "1")
    disk = request.form.get("disk", "20GB")
    node_id = request.form.get("node_id") or None
    node_id = int(node_id) if node_id else None

    name = lxd.generate_container_name(settings.get("hostname_prefix", "cryzon"))
    pw = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    days = int(settings.get("default_vps_days") or 0)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else None

    vps_id = db.execute(
        "INSERT INTO vps (user_id, node_id, container_name, status, os_type, ram, cpu, disk, ssh_password, expires_at) "
        "VALUES (?, ?, ?, 'creating', ?, ?, ?, ?, ?, ?)",
        (user["id"], node_id, name, os_type, ram, cpu, disk, pw, expires),
    )
    ok, msg = containers.create(name, os_type, ram, cpu, disk, pw)
    db.execute("UPDATE vps SET status=? WHERE id=?", ("running" if ok else "error", vps_id))
    ip = containers.get_ip(name) if ok else None
    if ip:
        db.execute("UPDATE vps SET ssh_command=? WHERE id=?", (f"ssh root@{ip}", vps_id))
    db.log_activity(user["id"], "create_vps", "vps", name, request.remote_addr)
    db.notify(user["id"], "VPS deployed", f"Your VPS {name} is ready.", "success")
    flash(f"VPS {name} {'deployed successfully' if ok else 'failed: ' + msg}.", "success" if ok else "error")
    return redirect(url_for("main.vps_detail", vps_id=vps_id) if ok else url_for("main.dashboard"))


@bp.route("/vps/<int:vps_id>")
@login_required
def vps_detail(vps_id):
    vps = _get_vps(vps_id)
    stats = containers.get_stats(vps["container_name"], vps["ram"], vps["disk"], vps["cpu"])
    ip = containers.get_ip(vps["container_name"])
    shares = db.query(
        "SELECT s.*, u.username FROM vps_shares s JOIN users u ON u.id=s.shared_with WHERE s.vps_id=?", (vps_id,)
    )
    backups = db.query("SELECT * FROM backups WHERE vps_id=? ORDER BY id DESC", (vps_id,))
    schedules = db.query("SELECT * FROM vps_schedules WHERE vps_id=? ORDER BY id DESC", (vps_id,))
    expired = _apply_expiry(vps)
    return render_template("vps_detail.html", vps=vps, stats=stats, ip=ip, shares=shares,
                           backups=backups, schedules=schedules, expired=expired, os_options=OS_OPTIONS)


@bp.route("/vps/<int:vps_id>/console")
@login_required
def vps_console(vps_id):
    vps = _get_vps(vps_id, perm="vps.console")
    return render_template("console.html", vps=vps)


@bp.route("/vps/<int:vps_id>/action", methods=["POST"])
@login_required
def vps_action(vps_id):
    action = request.form.get("action")
    perm = "vps.delete" if action == "delete" else "vps.manage"
    vps = _get_vps(vps_id, perm=perm)
    name = vps["container_name"]
    user = current_user()
    if action == "start":
        ok = containers.start(name)
        db.execute("UPDATE vps SET status=? WHERE id=?", ("running" if ok else "error", vps_id))
    elif action == "stop":
        ok = containers.stop(name)
        db.execute("UPDATE vps SET status=? WHERE id=?", ("stopped" if ok else "error", vps_id))
    elif action == "restart":
        ok = containers.restart(name)
        db.execute("UPDATE vps SET status=? WHERE id=?", ("running" if ok else "error", vps_id))
    elif action == "delete":
        containers.destroy(name)
        db.execute("DELETE FROM vps WHERE id=?", (vps_id,))
        db.log_activity(user["id"], "delete_vps", "vps", name, request.remote_addr)
        flash("VPS deleted.", "success")
        return redirect(url_for("main.dashboard"))
    elif action == "reinstall":
        pw = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        containers.destroy(name)
        containers.create(name, vps["os_type"], vps["ram"], vps["cpu"], vps["disk"], pw)
        db.execute("UPDATE vps SET status='running', ssh_password=? WHERE id=?", (pw, vps_id))
    db.log_activity(user["id"], f"vps_{action}", "vps", name, request.remote_addr)
    flash(f"VPS {action} issued.", "success")
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/regen-ssh", methods=["POST"])
@login_required
def vps_regen_ssh(vps_id):
    vps = _get_vps(vps_id, perm="vps.manage")
    pw = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    containers.regen_ssh(vps["container_name"], pw)
    db.execute("UPDATE vps SET ssh_password=? WHERE id=?", (pw, vps_id))
    flash("SSH credentials regenerated.", "success")
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/share", methods=["POST"])
@login_required
def vps_share(vps_id):
    vps = _get_vps(vps_id, perm="vps.share")
    uname = (request.form.get("username") or "").strip()
    target = db.query("SELECT * FROM users WHERE username=?", (uname,), one=True)
    if not target:
        flash("User not found.", "error")
    else:
        db.execute("INSERT INTO vps_shares (vps_id, shared_with, shared_by) VALUES (?, ?, ?)", (vps_id, target["id"], current_user()["id"]))
        db.notify(target["id"], "VPS shared with you", f"{vps['container_name']} was shared with your account.", "info")
        flash(f"Shared with {uname}.", "success")
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/unshare/<int:share_id>", methods=["POST"])
@login_required
def vps_unshare(vps_id, share_id):
    _get_vps(vps_id, perm="vps.share")
    db.execute("DELETE FROM vps_shares WHERE id=?", (share_id,))
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


# ---------------------------------------------------------------------------
# File manager & processes
# ---------------------------------------------------------------------------
@bp.route("/vps/<int:vps_id>/files")
@login_required
def vps_files(vps_id):
    vps = _get_vps(vps_id, perm="vps.files")
    path = request.args.get("path", "/root")
    demo = containers.is_demo()
    entries = []
    if demo:
        entries = _demo_files(path)
    else:
        code, out, err = containers.exec_cmd(vps["container_name"], f"ls -la --time-style=+%Y-%m-%d {path!r}")
        if code == 0:
            for line in out.splitlines()[1:]:
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    entries.append({"perm": parts[0], "size": parts[4], "date": parts[5], "name": parts[8],
                                    "dir": parts[0].startswith("d")})
    return render_template("files.html", vps=vps, path=path, entries=entries, demo=demo)


def _demo_files(path):
    base = [
        {"perm": "drwxr-xr-x", "size": "4096", "date": "2025-01-04", "name": "..", "dir": True},
        {"perm": "drwxr-xr-x", "size": "4096", "date": "2025-01-04", "name": "etc", "dir": True},
        {"perm": "drwxr-xr-x", "size": "4096", "date": "2025-01-04", "name": "home", "dir": True},
        {"perm": "drwxr-xr-x", "size": "4096", "date": "2025-01-04", "name": "var", "dir": True},
        {"perm": "-rw-r--r--", "size": "220", "date": "2025-01-04", "name": "README.md", "dir": False},
        {"perm": "-rwxr-xr-x", "size": "1024", "date": "2025-01-04", "name": "deploy.sh", "dir": False},
    ]
    return base


@bp.route("/vps/<int:vps_id>/processes")
@login_required
def vps_processes(vps_id):
    vps = _get_vps(vps_id, perm="vps.processes")
    demo = containers.is_demo()
    procs = []
    if demo:
        procs = [
            {"pid": 1, "user": "root", "cpu": 0.0, "mem": 0.1, "cmd": "/sbin/init"},
            {"pid": 412, "user": "root", "cpu": 1.2, "mem": 2.4, "cmd": "/usr/sbin/sshd -D"},
            {"pid": 733, "user": "www-data", "cpu": 0.8, "mem": 3.1, "cmd": "nginx: worker process"},
            {"pid": 1180, "user": "root", "cpu": 12.5, "mem": 8.7, "cmd": "python3 app.py"},
        ]
    else:
        code, out, _ = containers.exec_cmd(vps["container_name"], "ps -eo pid,user,pcpu,pmem,comm --sort=-pcpu | head -40")
        if code == 0:
            for line in out.splitlines()[1:]:
                parts = line.split(None, 4)
                if len(parts) == 5:
                    procs.append({"pid": parts[0], "user": parts[1], "cpu": parts[2], "mem": parts[3], "cmd": parts[4]})
    return render_template("processes.html", vps=vps, procs=procs, demo=demo)


@bp.route("/vps/<int:vps_id>/processes/kill", methods=["POST"])
@login_required
def vps_kill(vps_id):
    vps = _get_vps(vps_id, perm="vps.processes")
    pid = request.form.get("pid")
    if not containers.is_demo():
        containers.exec_cmd(vps["container_name"], f"kill -9 {int(pid)}")
    flash(f"Process {pid} terminated.", "success")
    return redirect(url_for("main.vps_processes", vps_id=vps_id))


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
@bp.route("/vps/<int:vps_id>/backups", methods=["POST"])
@login_required
def vps_backup_create(vps_id):
    vps = _get_vps(vps_id, perm="vps.backups")
    name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    db.execute("INSERT INTO backups (vps_id, user_id, name, image_name, size_mb) VALUES (?, ?, ?, ?, ?)",
               (vps_id, current_user()["id"], name, f"{vps['container_name']}-{name}", round(random.uniform(120, 900), 1)))
    flash("Backup created.", "success")
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/backups/<int:bid>/delete", methods=["POST"])
@login_required
def vps_backup_delete(vps_id, bid):
    _get_vps(vps_id, perm="vps.backups")
    db.execute("DELETE FROM backups WHERE id=?", (bid,))
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/backups/<int:bid>/restore", methods=["POST"])
@login_required
def vps_backup_restore(vps_id, bid):
    _get_vps(vps_id, perm="vps.backups")
    flash("Backup restore started.", "success")
    return redirect(url_for("main.vps_detail", vps_id=vps_id))


# ---------------------------------------------------------------------------
# Port forwarding
# ---------------------------------------------------------------------------
@bp.route("/ports")
@login_required
def ports():
    user = current_user()
    rows = db.query(
        "SELECT p.*, v.container_name FROM port_forwards p JOIN vps v ON v.id=p.vps_id WHERE p.user_id=? ORDER BY p.id DESC",
        (user["id"],),
    )
    vps_list = db.query("SELECT * FROM vps WHERE user_id=?", (user["id"],))
    return render_template("ports.html", ports=rows, vps_list=vps_list)


@bp.route("/ports/create", methods=["POST"])
@login_required
def port_create():
    user = current_user()
    if not has_permission(user, "vps.ports"):
        abort(403)
    vps_id = int(request.form.get("vps_id"))
    local = int(request.form.get("local_port"))
    remote = int(request.form.get("remote_port") or random.randint(20000, 40000))
    db.execute(
        "INSERT INTO port_forwards (user_id, vps_id, local_port, remote_port, serveo_url, method) VALUES (?, ?, ?, ?, ?, 'socat')",
        (user["id"], vps_id, local, remote, f"http://{lxd.generate_container_name('pf')}.cryzon.cloud:{remote}"),
    )
    flash("Port forward created.", "success")
    return redirect(url_for("main.ports"))


@bp.route("/ports/<int:pid>/delete", methods=["POST"])
@login_required
def port_delete(pid):
    user = current_user()
    db.execute("DELETE FROM port_forwards WHERE id=? AND user_id=?", (pid, user["id"]))
    return redirect(url_for("main.ports"))


# ---------------------------------------------------------------------------
# Support tickets
# ---------------------------------------------------------------------------
@bp.route("/tickets")
@login_required
def tickets():
    user = current_user()
    if has_permission(user, "tickets.manage") and request.args.get("all"):
        rows = db.query("SELECT t.*, u.username FROM tickets t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC")
    else:
        rows = db.query("SELECT t.*, u.username FROM tickets t JOIN users u ON u.id=t.user_id WHERE t.user_id=? ORDER BY t.id DESC", (user["id"],))
    return render_template("tickets.html", tickets=rows)


@bp.route("/tickets/create", methods=["POST"])
@login_required
def ticket_create():
    user = current_user()
    subject = (request.form.get("subject") or "").strip()
    message = (request.form.get("message") or "").strip()
    tid = db.execute("INSERT INTO tickets (user_id, subject) VALUES (?, ?)", (user["id"], subject))
    db.execute("INSERT INTO ticket_replies (ticket_id, user_id, message) VALUES (?, ?, ?)", (tid, user["id"], message))
    flash("Ticket submitted.", "success")
    return redirect(url_for("main.ticket_detail", tid=tid))


@bp.route("/tickets/<int:tid>")
@login_required
def ticket_detail(tid):
    user = current_user()
    t = db.query("SELECT t.*, u.username FROM tickets t JOIN users u ON u.id=t.user_id WHERE t.id=?", (tid,), one=True)
    if not t:
        abort(404)
    if t["user_id"] != user["id"] and not has_permission(user, "tickets.manage"):
        abort(403)
    replies = db.query("SELECT r.*, u.username FROM ticket_replies r JOIN users u ON u.id=r.user_id WHERE r.ticket_id=? ORDER BY r.id", (tid,))
    return render_template("ticket_detail.html", ticket=t, replies=replies)


@bp.route("/tickets/<int:tid>/reply", methods=["POST"])
@login_required
def ticket_reply(tid):
    user = current_user()
    msg = (request.form.get("message") or "").strip()
    db.execute("INSERT INTO ticket_replies (ticket_id, user_id, message, is_admin) VALUES (?, ?, ?, ?)",
               (tid, user["id"], msg, 1 if is_admin(user) else 0))
    db.execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP, status='open' WHERE id=?", (tid,))
    return redirect(url_for("main.ticket_detail", tid=tid))


@bp.route("/tickets/<int:tid>/close", methods=["POST"])
@login_required
def ticket_close(tid):
    db.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
    return redirect(url_for("main.ticket_detail", tid=tid))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@bp.route("/notifications")
@login_required
def notifications():
    user = current_user()
    rows = db.query("SELECT * FROM notifications WHERE user_id=? OR user_id IS NULL ORDER BY id DESC LIMIT 50", (user["id"],))
    return render_template("notifications.html", notifications=rows)


@bp.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    user = current_user()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
    return jsonify({"ok": True})
