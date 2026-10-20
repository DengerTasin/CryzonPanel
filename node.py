"""CryzonCloud node agent.

Runs on every worker node and exposes a small authenticated REST API that the
main panel uses to provision and manage LXD containers remotely. The agent is
stateless: it simply wraps the local ``lxc`` CLI (see :mod:`ccp.lxd`).

Start it with::

    NODE_API_KEY=super-secret CRYZON_NODE_PORT=9000 python node.py

The panel stores the same key on the node record and sends it in the
``X-API-Key`` header.
"""
import functools
import os
import socket

from flask import Flask, request, jsonify

from ccp import lxd

app = Flask(__name__)

NODE_API_KEY = os.environ.get("NODE_API_KEY", "")
NODE_NAME = os.environ.get("CRYZON_NODE_NAME", socket.gethostname())


def require_key(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if NODE_API_KEY:
            key = request.headers.get("X-API-Key") or request.args.get("api_key")
            if key != NODE_API_KEY:
                return jsonify({"error": "invalid api key"}), 401
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Health / capacity
# ---------------------------------------------------------------------------
@app.route("/api/health")
@require_key
def health():
    cpu = ram = 0.0
    vps_count = 0
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
    except Exception:  # noqa: BLE001
        pass
    try:
        vps_count = len(lxd.lxc_list())
    except Exception:  # noqa: BLE001
        pass
    return jsonify({
        "status": "ok",
        "node": NODE_NAME,
        "hostname": socket.gethostname(),
        "cpu": cpu,
        "ram": ram,
        "vps_count": vps_count,
        "lxc_version": lxd.lxc_get_version(),
        "lxc_available": lxd.lxc_is_available(),
    })


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
@app.route("/api/containers")
@require_key
def list_containers():
    return jsonify(lxd.lxc_list())


@app.route("/api/containers", methods=["POST"])
@require_key
def create_container():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name is required"}), 400
    ok, msg = lxd.lxc_create(
        name,
        body.get("os_type", "ubuntu-22.04"),
        body.get("ram", "2GB"),
        body.get("cpu", "1"),
        body.get("disk", "20GB"),
        body.get("password"),
    )
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)


@app.route("/api/containers/<name>/start", methods=["POST"])
@require_key
def start_container(name):
    return jsonify({"ok": lxd.lxc_start(name)})


@app.route("/api/containers/<name>/stop", methods=["POST"])
@require_key
def stop_container(name):
    return jsonify({"ok": lxd.lxc_stop(name)})


@app.route("/api/containers/<name>/restart", methods=["POST"])
@require_key
def restart_container(name):
    return jsonify({"ok": lxd.lxc_restart(name)})


@app.route("/api/containers/<name>", methods=["DELETE"])
@require_key
def delete_container(name):
    return jsonify({"ok": lxd.lxc_destroy(name)})


@app.route("/api/containers/<name>/stats")
@require_key
def container_stats(name):
    return jsonify(lxd.lxc_get_stats(name))


@app.route("/api/containers/<name>/ip")
@require_key
def container_ip(name):
    return jsonify({"ip": lxd.lxc_get_ip(name)})


@app.route("/api/containers/<name>/status")
@require_key
def container_status(name):
    return jsonify({"status": lxd.lxc_status(name)})


@app.route("/api/containers/<name>/exec", methods=["POST"])
@require_key
def container_exec(name):
    body = request.get_json(silent=True) or {}
    code, out, err = lxd.lxc_exec(name, body.get("command", ""), int(body.get("timeout", 60)))
    return jsonify({"code": code, "stdout": out, "stderr": err})


if __name__ == "__main__":
    port = int(os.environ.get("CRYZON_NODE_PORT", "9000"))
    print(f"CryzonCloud node agent '{NODE_NAME}' listening on 0.0.0.0:{port}")
    print(f"  » Auth: {'enabled' if NODE_API_KEY else 'DISABLED (set NODE_API_KEY!)'}")
    print(f"  » LXC:  {lxd.lxc_get_version()}")
    app.run(host="0.0.0.0", port=port, threaded=True)
