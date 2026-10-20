"""JSON API blueprint for the CryzonCloud panel.

Provides lightweight endpoints consumed by the front-end for live statistics,
notification polling and the dashboard auto-refresh. All endpoints require an
authenticated session (or an API key where noted).
"""
from flask import Blueprint, jsonify, request

from . import db, containers
from .security import (
    current_user, login_required, has_permission, is_admin, api_key_required,
)

bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Health (also used by remote node probes)
# ---------------------------------------------------------------------------
@bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "cryzoncloud-cpanel"})


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------
@bp.route("/stats")
@login_required
def stats():
    user = current_user()
    if is_admin(user):
        data = {
            "scope": "admin",
            "vps": db.query("SELECT COUNT(*) c FROM vps", one=True)["c"],
            "running": db.query("SELECT COUNT(*) c FROM vps WHERE status='running'", one=True)["c"],
            "stopped": db.query("SELECT COUNT(*) c FROM vps WHERE status='stopped'", one=True)["c"],
            "users": db.query("SELECT COUNT(*) c FROM users", one=True)["c"],
            "nodes": db.query("SELECT COUNT(*) c FROM nodes", one=True)["c"],
            "tickets": db.query("SELECT COUNT(*) c FROM tickets WHERE status='open'", one=True)["c"],
            "backups": db.query("SELECT COUNT(*) c FROM backups", one=True)["c"],
        }
    else:
        data = {
            "scope": "user",
            "vps": db.query("SELECT COUNT(*) c FROM vps WHERE user_id=?", (user["id"],), one=True)["c"],
            "running": db.query("SELECT COUNT(*) c FROM vps WHERE user_id=? AND status='running'", (user["id"],), one=True)["c"],
            "stopped": db.query("SELECT COUNT(*) c FROM vps WHERE user_id=? AND status='stopped'", (user["id"],), one=True)["c"],
            "shared": db.query("SELECT COUNT(*) c FROM vps_shares WHERE shared_with=?", (user["id"],), one=True)["c"],
        }
    return jsonify(data)


# ---------------------------------------------------------------------------
# VPS list & live per-container stats
# ---------------------------------------------------------------------------
@bp.route("/vps")
@login_required
def vps_list():
    user = current_user()
    if is_admin(user) and request.args.get("all"):
        rows = db.query(
            "SELECT v.*, u.username FROM vps v JOIN users u ON u.id=v.user_id ORDER BY v.id DESC"
        )
    else:
        rows = db.query("SELECT * FROM vps WHERE user_id=? ORDER BY id DESC", (user["id"],))
    return jsonify([dict(r) for r in rows])


@bp.route("/vps/<int:vps_id>/stats")
@login_required
def vps_stats(vps_id):
    vps = db.query("SELECT * FROM vps WHERE id=?", (vps_id,), one=True)
    if not vps:
        return jsonify({"error": "not found"}), 404
    vps = dict(vps)
    user = current_user()
    shared = db.query(
        "SELECT 1 FROM vps_shares WHERE vps_id=? AND shared_with=?", (vps_id, user["id"]), one=True
    )
    if vps["user_id"] != user["id"] and not shared and not is_admin(user):
        return jsonify({"error": "forbidden"}), 403
    st = containers.get_stats(vps["container_name"], vps["ram"], vps["disk"], vps["cpu"])
    st["ip"] = containers.get_ip(vps["container_name"])
    st["status"] = containers.status(vps["container_name"])
    return jsonify(st)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@bp.route("/notifications")
@login_required
def notifications():
    user = current_user()
    rows = db.query(
        "SELECT * FROM notifications WHERE user_id=? OR user_id IS NULL ORDER BY id DESC LIMIT 20",
        (user["id"],),
    )
    unread = db.query(
        "SELECT COUNT(*) c FROM notifications WHERE (user_id=? OR user_id IS NULL) AND is_read=0",
        (user["id"],),
        one=True,
    )["c"]
    return jsonify({"items": [dict(r) for r in rows], "unread": unread})


@bp.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    user = current_user()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
@bp.route("/nodes")
@login_required
def nodes():
    user = current_user()
    if not has_permission(user, "nodes.view"):
        return jsonify({"error": "forbidden"}), 403
    rows = db.query("SELECT * FROM nodes ORDER BY id")
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# API-key protected endpoint (for scripts / automation)
# ---------------------------------------------------------------------------
@bp.route("/me")
@api_key_required
def me():
    from flask import g
    u = dict(g.user)
    u.pop("password", None)
    return jsonify(u)
