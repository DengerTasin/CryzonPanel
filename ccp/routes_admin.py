"""Administration routes: dashboard, users, roles, nodes, settings, logs."""
import json
import random
import string
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, abort,
)

from . import db, lxd, containers
from .security import (
    current_user, login_required, permission_required, any_permission_required,
    has_permission, is_admin, ALL_PERMISSIONS, PERMISSION_GROUPS, permission_label,
    generate_api_key,
)
from .routes import OS_OPTIONS, RAM_OPTIONS, CPU_OPTIONS, DISK_OPTIONS

bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PERMS = ["vps.view", "vps.create", "users.view", "roles.view", "nodes.view", "settings.view", "logs.view", "stats.view"]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@any_permission_required(ADMIN_PERMS)
def dashboard():
    user = current_user()
    stats = {
        "vps": db.query("SELECT COUNT(*) c FROM vps", one=True)["c"],
        "running": db.query("SELECT COUNT(*) c FROM vps WHERE status='running'", one=True)["c"],
        "users": db.query("SELECT COUNT(*) c FROM users", one=True)["c"],
        "nodes": db.query("SELECT COUNT(*) c FROM nodes", one=True)["c"],
        "tickets": db.query("SELECT COUNT(*) c FROM tickets WHERE status='open'", one=True)["c"],
        "backups": db.query("SELECT COUNT(*) c FROM backups", one=True)["c"],
    }
    recent_vps = db.query(
        "SELECT v.*, u.username FROM vps v JOIN users u ON u.id=v.user_id ORDER BY v.id DESC LIMIT 8"
    )
    recent_logs = db.query("SELECT * FROM system_logs ORDER BY id DESC LIMIT 8")
    nodes = db.query("SELECT * FROM nodes ORDER BY id")
    return render_template("admin/dashboard.html", stats=stats, recent_vps=recent_vps, recent_logs=recent_logs, nodes=nodes)


# ---------------------------------------------------------------------------
# VPS management
# ---------------------------------------------------------------------------
@bp.route("/vps")
@login_required
@permission_required("vps.view")
def vps_list():
    rows = db.query(
        "SELECT v.*, u.username, n.name AS node_name FROM vps v "
        "JOIN users u ON u.id=v.user_id LEFT JOIN nodes n ON n.id=v.node_id ORDER BY v.id DESC"
    )
    users = db.query("SELECT id, username FROM users ORDER BY username")
    nodes = db.query("SELECT * FROM nodes ORDER BY id")
    return render_template("admin/vps.html", vps_list=rows, users=users, nodes=nodes,
                           os_options=OS_OPTIONS, ram_options=RAM_OPTIONS, cpu_options=CPU_OPTIONS, disk_options=DISK_OPTIONS)


@bp.route("/vps/create", methods=["POST"])
@login_required
@permission_required("vps.create")
def vps_create():
    user = current_user()
    owner_id = int(request.form.get("user_id") or user["id"])
    os_type = request.form.get("os_type", "ubuntu-22.04")
    ram = request.form.get("ram", "2GB")
    cpu = request.form.get("cpu", "1")
    disk = request.form.get("disk", "20GB")
    node_id = request.form.get("node_id") or None
    node_id = int(node_id) if node_id else None
    days = int(request.form.get("days") or 0)

    name = lxd.generate_container_name(db.get_settings().get("hostname_prefix", "cryzon"))
    pw = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    expires = None
    if days:
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    vps_id = db.execute(
        "INSERT INTO vps (user_id, node_id, container_name, status, os_type, ram, cpu, disk, ssh_password, expires_at) "
        "VALUES (?, ?, ?, 'creating', ?, ?, ?, ?, ?, ?)",
        (owner_id, node_id, name, os_type, ram, cpu, disk, pw, expires),
    )
    ok, msg = containers.create(name, os_type, ram, cpu, disk, pw)
    db.execute("UPDATE vps SET status=? WHERE id=?", ("running" if ok else "error", vps_id))
    ip = containers.get_ip(name) if ok else None
    if ip:
        db.execute("UPDATE vps SET ssh_command=? WHERE id=?", (f"ssh root@{ip}", vps_id))
    db.log_activity(user["id"], "create_vps", "vps", f"{name} for user {owner_id}", request.remote_addr)
    db.notify(owner_id, "VPS deployed", f"Your VPS {name} is ready.", "success")
    flash(f"VPS {name} {'deployed' if ok else 'failed: ' + msg}.", "success" if ok else "error")
    return redirect(url_for("admin.vps_list"))


@bp.route("/vps/<int:vps_id>")
@login_required
@permission_required("vps.view")
def vps_detail(vps_id):
    vps = db.query("SELECT v.*, u.username FROM vps v JOIN users u ON u.id=v.user_id WHERE v.id=?", (vps_id,), one=True)
    if not vps:
        abort(404)
    vps = dict(vps)
    stats = containers.get_stats(vps["container_name"], vps["ram"], vps["disk"], vps["cpu"])
    ip = containers.get_ip(vps["container_name"])
    users = db.query("SELECT id, username FROM users ORDER BY username")
    nodes = db.query("SELECT * FROM nodes ORDER BY id")
    return render_template("admin/vps_detail.html", vps=vps, stats=stats, ip=ip, users=users, nodes=nodes,
                           os_options=OS_OPTIONS, ram_options=RAM_OPTIONS, cpu_options=CPU_OPTIONS, disk_options=DISK_OPTIONS)


@bp.route("/vps/<int:vps_id>/action", methods=["POST"])
@login_required
@permission_required("vps.manage")
def vps_action(vps_id):
    action = request.form.get("action")
    vps = db.query("SELECT * FROM vps WHERE id=?", (vps_id,), one=True)
    if not vps:
        abort(404)
    name = vps["container_name"]
    if action == "start":
        containers.start(name); db.execute("UPDATE vps SET status='running' WHERE id=?", (vps_id,))
    elif action == "stop":
        containers.stop(name); db.execute("UPDATE vps SET status='stopped' WHERE id=?", (vps_id,))
    elif action == "restart":
        containers.restart(name); db.execute("UPDATE vps SET status='running' WHERE id=?", (vps_id,))
    elif action == "delete":
        containers.destroy(name); db.execute("DELETE FROM vps WHERE id=?", (vps_id,))
        flash("VPS deleted.", "success")
        return redirect(url_for("admin.vps_list"))
    elif action == "reinstall":
        pw = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        containers.destroy(name)
        containers.create(name, vps["os_type"], vps["ram"], vps["cpu"], vps["disk"], pw)
        db.execute("UPDATE vps SET status='running', ssh_password=? WHERE id=?", (pw, vps_id))
    flash(f"VPS {action} issued.", "success")
    return redirect(url_for("admin.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/update", methods=["POST"])
@login_required
@permission_required("vps.manage")
def vps_update(vps_id):
    ram = request.form.get("ram")
    cpu = request.form.get("cpu")
    disk = request.form.get("disk")
    os_type = request.form.get("os_type")
    node_id = request.form.get("node_id") or None
    days = request.form.get("days")
    fields, args = [], []
    for col, val in [("ram", ram), ("cpu", cpu), ("disk", disk), ("os_type", os_type)]:
        if val:
            fields.append(f"{col}=?"); args.append(val)
    if node_id:
        fields.append("node_id=?"); args.append(int(node_id))
    if days not in (None, ""):
        if int(days) > 0:
            fields.append("expires_at=?"); args.append((datetime.now(timezone.utc) + timedelta(days=int(days))).isoformat())
        else:
            fields.append("expires_at=?"); args.append(None)
    if fields:
        args.append(vps_id)
        db.execute(f"UPDATE vps SET {', '.join(fields)} WHERE id=?", args)
    flash("VPS updated.", "success")
    return redirect(url_for("admin.vps_detail", vps_id=vps_id))


@bp.route("/vps/<int:vps_id>/transfer", methods=["POST"])
@login_required
@permission_required("vps.transfer")
def vps_transfer(vps_id):
    target = int(request.form.get("user_id"))
    db.execute("UPDATE vps SET user_id=? WHERE id=?", (target, vps_id))
    db.notify(target, "VPS transferred to you", "A VPS has been transferred to your account.", "info")
    flash("VPS transferred.", "success")
    return redirect(url_for("admin.vps_detail", vps_id=vps_id))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@bp.route("/users")
@login_required
@permission_required("users.view")
def users():
    rows = db.query(
        "SELECT u.*, r.name AS role_name, r.color AS role_color, "
        "(SELECT COUNT(*) FROM vps WHERE user_id=u.id) AS vps_count "
        "FROM users u LEFT JOIN roles r ON r.id=u.role_id ORDER BY u.id"
    )
    roles = db.list_roles()
    return render_template("admin/users.html", users=rows, roles=roles)


@bp.route("/users/<int:uid>/role", methods=["POST"])
@login_required
@permission_required("users.manage")
def user_set_role(uid):
    role_id = request.form.get("role_id") or None
    if uid == 1:
        flash("The primary owner's role cannot be changed.", "error")
        return redirect(url_for("admin.users"))
    db.execute("UPDATE users SET role_id=? WHERE id=?", (int(role_id) if role_id else None, uid))
    flash("Role updated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/ban", methods=["POST"])
@login_required
@permission_required("users.ban")
def user_ban(uid):
    if uid == 1:
        abort(403)
    db.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    flash("User banned.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/unban", methods=["POST"])
@login_required
@permission_required("users.ban")
def user_unban(uid):
    db.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    flash("User unbanned.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
@permission_required("users.manage")
def user_delete(uid):
    if uid == 1:
        abort(403)
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    flash("User deleted.", "success")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# Roles & permissions
# ---------------------------------------------------------------------------
@bp.route("/roles")
@login_required
@permission_required("roles.view")
def roles():
    role_list = db.list_roles()
    counts = {r["id"]: db.query("SELECT COUNT(*) c FROM users WHERE role_id=?", (r["id"],), one=True)["c"] for r in role_list}
    return render_template("admin/roles.html", roles=role_list, counts=counts, permission_groups=PERMISSION_GROUPS)


@bp.route("/roles/create", methods=["POST"])
@login_required
@permission_required("roles.manage")
def role_create():
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    color = request.form.get("color") or "#6366f1"
    perms = request.form.getlist("permissions")
    if not name:
        flash("Role name is required.", "error")
        return redirect(url_for("admin.roles"))
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "role"
    if db.query("SELECT 1 FROM roles WHERE slug=?", (slug,), one=True):
        slug += "-" + str(random.randint(10, 99))
    db.execute(
        "INSERT INTO roles (name, slug, description, permissions, color, priority) VALUES (?, ?, ?, ?, ?, ?)",
        (name, slug, description, json.dumps(perms), color, 20),
    )
    db.log_activity(current_user()["id"], "create_role", "role", name, request.remote_addr)
    flash(f"Role '{name}' created.", "success")
    return redirect(url_for("admin.roles"))


@bp.route("/roles/<int:rid>/edit", methods=["POST"])
@login_required
@permission_required("roles.manage")
def role_edit(rid):
    role = db.get_role(rid)
    if not role:
        abort(404)
    name = (request.form.get("name") or role["name"]).strip()
    description = request.form.get("description", role["description"])
    color = request.form.get("color") or role["color"]
    perms = request.form.getlist("permissions")
    if role["slug"] == "owner":
        perms = ALL_PERMISSIONS  # owner always keeps everything
    db.execute(
        "UPDATE roles SET name=?, description=?, permissions=?, color=? WHERE id=?",
        (name, description, json.dumps(perms), color, rid),
    )
    db.log_activity(current_user()["id"], "edit_role", "role", name, request.remote_addr)
    flash(f"Role '{name}' updated.", "success")
    return redirect(url_for("admin.roles"))


@bp.route("/roles/<int:rid>/delete", methods=["POST"])
@login_required
@permission_required("roles.manage")
def role_delete(rid):
    role = db.get_role(rid)
    if not role:
        abort(404)
    if role["is_system"]:
        flash("System roles cannot be deleted.", "error")
        return redirect(url_for("admin.roles"))
    db.execute("UPDATE users SET role_id=NULL WHERE role_id=?", (rid,))
    db.execute("DELETE FROM roles WHERE id=?", (rid,))
    flash("Role deleted.", "success")
    return redirect(url_for("admin.roles"))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
@bp.route("/nodes")
@login_required
@permission_required("nodes.view")
def nodes():
    rows = db.query("SELECT * FROM nodes ORDER BY id")
    for n in rows:
        lxd.refresh_node_stats(dict(n))
    rows = db.query("SELECT * FROM nodes ORDER BY id")
    return render_template("admin/nodes.html", nodes=rows, lxc_version=lxd.lxc_get_version(), demo=containers.is_demo())


@bp.route("/nodes/add", methods=["POST"])
@login_required
@permission_required("nodes.manage")
def node_add():
    name = request.form.get("name")
    hostname = request.form.get("hostname")
    url = request.form.get("node_url", "")
    key = request.form.get("api_key", "")
    is_local = 1 if request.form.get("is_local") else 0
    db.execute(
        "INSERT INTO nodes (name, hostname, node_url, api_key, is_local, status) VALUES (?, ?, ?, ?, ?, 'online')",
        (name, hostname, url, key, is_local),
    )
    flash("Node added.", "success")
    return redirect(url_for("admin.nodes"))


@bp.route("/nodes/<int:nid>/edit", methods=["POST"])
@login_required
@permission_required("nodes.manage")
def node_edit(nid):
    db.execute(
        "UPDATE nodes SET name=?, hostname=?, node_url=?, api_key=?, max_vps=? WHERE id=?",
        (request.form.get("name"), request.form.get("hostname"), request.form.get("node_url", ""),
         request.form.get("api_key", ""), int(request.form.get("max_vps") or 500), nid),
    )
    flash("Node updated.", "success")
    return redirect(url_for("admin.nodes"))


@bp.route("/nodes/<int:nid>/delete", methods=["POST"])
@login_required
@permission_required("nodes.manage")
def node_delete(nid):
    node = db.query("SELECT * FROM nodes WHERE id=?", (nid,), one=True)
    if node and node["is_local"]:
        flash("The local node cannot be removed.", "error")
    else:
        db.execute("DELETE FROM nodes WHERE id=?", (nid,))
        flash("Node removed.", "success")
    return redirect(url_for("admin.nodes"))


# ---------------------------------------------------------------------------
# Settings & logs
# ---------------------------------------------------------------------------
@bp.route("/settings", methods=["GET", "POST"])
@login_required
@permission_required("settings.view")
def settings():
    if request.method == "POST":
        if not has_permission(current_user(), "settings.manage"):
            abort(403)
        keys = ["site_name", "site_description", "footer_text", "timezone", "logo_url", "favicon_url",
                "hostname_prefix", "port_forwarding_method", "public_ipv4"]
        for k in keys:
            if k in request.form:
                db.set_setting(k, request.form.get(k))
        for k in ["cpu_threshold", "ram_threshold", "max_vps_per_user", "max_ports_per_user", "default_vps_days"]:
            if k in request.form:
                db.set_setting(k, int(request.form.get(k) or 0))
        db.set_setting("registration_enabled", 1 if request.form.get("registration_enabled") else 0)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", settings=db.get_settings())


@bp.route("/logs")
@login_required
@permission_required("logs.view")
def logs():
    rows = db.query("SELECT * FROM system_logs ORDER BY id DESC LIMIT 300")
    activity = db.query(
        "SELECT a.*, u.username FROM activity_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100"
    )
    return render_template("admin/logs.html", logs=rows, activity=activity)


@bp.route("/logs/clear", methods=["POST"])
@login_required
@permission_required("logs.manage")
def logs_clear():
    db.execute("DELETE FROM system_logs")
    flash("Logs cleared.", "success")
    return redirect(url_for("admin.logs"))
