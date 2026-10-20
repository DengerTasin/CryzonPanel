"""Authentication, password hashing and the roles/permissions engine."""
import hashlib
import hmac
import os
import secrets
import functools
from flask import session, redirect, url_for, flash, request, jsonify, g

from . import db

# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------
PERMISSION_GROUPS = [
    {
        "key": "general",
        "label": "General",
        "icon": "grid",
        "permissions": [
            ("dashboard.view", "View dashboard"),
            ("stats.view", "View system statistics"),
        ],
    },
    {
        "key": "vps",
        "label": "VPS / Containers",
        "icon": "server",
        "permissions": [
            ("vps.view", "View VPS instances"),
            ("vps.create", "Create VPS"),
            ("vps.manage", "Manage VPS (start / stop / restart / reinstall)"),
            ("vps.delete", "Delete VPS"),
            ("vps.console", "Access web console / terminal"),
            ("vps.files", "File manager access"),
            ("vps.processes", "Process manager access"),
            ("vps.backups", "Create & restore backups"),
            ("vps.ports", "Manage port forwarding"),
            ("vps.share", "Share VPS with other users"),
            ("vps.transfer", "Transfer VPS ownership"),
            ("vps.expiry", "Set / clear VPS expiry"),
        ],
    },
    {
        "key": "users",
        "label": "Users",
        "icon": "users",
        "permissions": [
            ("users.view", "View users"),
            ("users.manage", "Create / edit users"),
            ("users.ban", "Ban / unban users"),
        ],
    },
    {
        "key": "roles",
        "label": "Roles & Permissions",
        "icon": "shield",
        "permissions": [
            ("roles.view", "View roles"),
            ("roles.manage", "Create / edit / delete roles"),
        ],
    },
    {
        "key": "nodes",
        "label": "Nodes",
        "icon": "cpu",
        "permissions": [
            ("nodes.view", "View nodes"),
            ("nodes.manage", "Add / edit / delete nodes"),
        ],
    },
    {
        "key": "support",
        "label": "Support",
        "icon": "life-buoy",
        "permissions": [
            ("tickets.view", "View tickets"),
            ("tickets.manage", "Reply / close tickets"),
        ],
    },
    {
        "key": "system",
        "label": "System",
        "icon": "settings",
        "permissions": [
            ("logs.view", "View system logs"),
            ("logs.manage", "Clear logs"),
            ("settings.view", "View panel settings"),
            ("settings.manage", "Change panel settings"),
        ],
    },
]

ALL_PERMISSIONS = [p for grp in PERMISSION_GROUPS for p, _ in grp["permissions"]]


def permission_label(perm):
    for grp in PERMISSION_GROUPS:
        for p, label in grp["permissions"]:
            if p == perm:
                return label
    return perm


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-SHA256)
# ---------------------------------------------------------------------------
def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def generate_api_key():
    return "cck_" + secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Current user / permission checks
# ---------------------------------------------------------------------------
def current_user():
    if "user" in g:
        return g.user
    uid = session.get("user_id")
    if not uid:
        g.user = None
        return None
    row = db.query("SELECT * FROM users WHERE id = ?", (uid,), one=True)
    if not row:
        g.user = None
        return None
    user = dict(row)
    user["role"] = db.get_role(user.get("role_id"))
    # Owner (id 1 or is_admin with owner role) always has full access
    g.user = user
    return user


def user_permissions(user):
    if not user:
        return set()
    role = user.get("role")
    if role:
        perms = set(role.get("permissions") or [])
        if role.get("slug") == "owner":
            perms = set(ALL_PERMISSIONS)
        return perms
    if user.get("is_admin"):
        return set(ALL_PERMISSIONS)
    return set()


def has_permission(user, perm):
    if not user:
        return False
    if user.get("is_banned"):
        return False
    return perm in user_permissions(user)


def is_admin(user):
    if not user:
        return False
    role = user.get("role")
    if role and role.get("slug") in ("owner", "admin"):
        return True
    return bool(user.get("is_admin"))


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("main.login", next=request.path))
        if user.get("is_banned"):
            session.clear()
            flash("Your account has been suspended.", "error")
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)

    return wrapper


def permission_required(perm):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "authentication required"}), 401
                return redirect(url_for("main.login", next=request.path))
            if not has_permission(user, perm):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "forbidden", "missing": perm}), 403
                flash("You don't have permission to do that.", "error")
                return redirect(url_for("main.dashboard"))
            return f(*args, **kwargs)

        return wrapper

    return deco


def any_permission_required(perms):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "authentication required"}), 401
                return redirect(url_for("main.login", next=request.path))
            if not any(has_permission(user, p) for p in perms):
                flash("You don't have permission to access that area.", "error")
                return redirect(url_for("main.dashboard"))
            return f(*args, **kwargs)

        return wrapper

    return deco


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("main.login", next=request.path))
        if not is_admin(user):
            flash("Administrator access required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return wrapper


def api_key_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if not key:
            return jsonify({"error": "missing api key"}), 401
        row = db.query("SELECT * FROM users WHERE api_key = ?", (key,), one=True)
        if not row:
            return jsonify({"error": "invalid api key"}), 401
        g.user = dict(row)
        g.user["role"] = db.get_role(g.user.get("role_id"))
        return f(*args, **kwargs)

    return wrapper
