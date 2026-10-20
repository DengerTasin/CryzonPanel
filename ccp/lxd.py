"""LXC / LXD integration and multi-node routing."""
import json
import os
import re
import shutil
import socket
import subprocess
import time
import http.client

from . import db

LXC = "lxc"
SNAP_LXC = "/snap/bin/lxc"

LXC_IMAGE_MAP = {
    "ubuntu-22.04": "22.04",
    "ubuntu-24.04": "24.04",
    "ubuntu-26.04": "26.04",
    "debian-12": "images:debian/12",
    "alpine-3.20": "images:alpine/3.20",
}

OS_LABELS = {
    "ubuntu-22.04": "Ubuntu 22.04 LTS",
    "ubuntu-24.04": "Ubuntu 24.04 LTS",
    "ubuntu-26.04": "Ubuntu 26.04 LTS",
    "debian-12": "Debian 12",
    "alpine-3.20": "Alpine 3.20",
}


def _lxc_bin():
    if shutil.which(LXC):
        return shutil.which(LXC)
    if os.path.exists(SNAP_LXC):
        return SNAP_LXC
    return LXC


def _run(args, timeout=60, input=None):
    env = dict(os.environ)
    env["PATH"] = "/snap/bin:" + env.get("PATH", "")
    try:
        p = subprocess.run(
            [_lxc_bin()] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
            env=env,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "lxc binary not found"
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"


def lxc_is_available():
    if os.environ.get("CRYZON_DEMO") == "1":
        return False
    sock = "/var/snap/lxd/common/lxd/unix.socket"
    if not os.path.exists(sock) and not shutil.which("lxc") and not os.path.exists(SNAP_LXC):
        return False
    code, out, err = _run(["version"], timeout=10)
    return code == 0


def lxc_get_version():
    code, out, _ = _run(["version"], timeout=10)
    if code == 0:
        return out.strip().splitlines()[0] if out.strip() else "unknown"
    return "unavailable"


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------
def lxc_create(name, os_type="ubuntu-22.04", ram="2GB", cpu="1", disk="20GB", password=None):
    image = LXC_IMAGE_MAP.get(os_type, "22.04")
    args = [
        "launch", image, name,
        "-c", f"limits.memory={ram}",
        "-c", f"limits.cpu={cpu}",
        "-c", "limits.memory.swap=false",
        "-d", f"root,size={disk},pool=default",
    ]
    code, out, err = _run(args, timeout=600)
    if code != 0:
        # Retry without the disk quota (dir pools may not support it)
        args = [
            "launch", image, name,
            "-c", f"limits.memory={ram}",
            "-c", f"limits.cpu={cpu}",
        ]
        code, out, err = _run(args, timeout=600)
        if code != 0:
            return False, (err or out).strip()
    # Set a root password so SSH works too
    if password:
        _run(["exec", name, "--", "bash", "-c", f"echo 'root:{password}' | chpasswd"], timeout=60)
    _run(["config", "set", name, "boot.autostart", "true"], timeout=30)
    return True, out.strip()


def lxc_start(name):
    return _run(["start", name], timeout=120)[0] == 0


def lxc_stop(name):
    return _run(["stop", name, "--force"], timeout=120)[0] == 0


def lxc_restart(name):
    return _run(["restart", name], timeout=180)[0] == 0


def lxc_destroy(name):
    _run(["stop", name, "--force"], timeout=120)
    return _run(["delete", name, "--force"], timeout=120)[0] == 0


def lxc_status(name):
    code, out, _ = _run(["info", name, "--format", "json"], timeout=30)
    if code != 0:
        return "unknown"
    try:
        data = json.loads(out)
        return data.get("status", "unknown").lower()
    except (ValueError, KeyError):
        return "unknown"


def lxc_get_ip(name):
    code, out, _ = _run(["list", name, "--format", "json"], timeout=30)
    if code != 0:
        return None
    try:
        data = json.loads(out)
        for c in data:
            for net, info in (c.get("state", {}).get("network") or {}).items():
                for addr in info.get("addresses", []):
                    if addr.get("family") == "inet" and addr.get("scope") == "global":
                        return addr.get("address")
    except (ValueError, KeyError):
        pass
    return None


def lxc_get_stats(name):
    code, out, _ = _run(["info", name, "--format", "json"], timeout=30)
    stats = {"cpu": 0, "ram_used": 0, "ram_total": 0, "ram_pct": 0, "disk_used": 0, "disk_total": 0, "processes": 0, "status": "unknown"}
    if code != 0:
        return stats
    try:
        data = json.loads(out)
        st = data.get("state", {})
        stats["status"] = data.get("status", "unknown").lower()
        stats["processes"] = st.get("processes", 0)
        mem = st.get("memory", {})
        stats["ram_used"] = mem.get("usage", 0)
        stats["ram_total"] = mem.get("usage_peak", 0) or mem.get("usage", 0)
        if mem.get("usage") and data.get("expanded_config", {}).get("limits.memory"):
            limit = _parse_mem_limit(data["expanded_config"]["limits.memory"])
            if limit:
                stats["ram_total"] = limit
                stats["ram_pct"] = round(mem["usage"] / limit * 100, 1)
        disk = st.get("disk", {})
        for dev, d in disk.items():
            stats["disk_used"] += d.get("usage", 0)
            stats["disk_total"] += d.get("total", 0)
        cpu = st.get("cpu", {})
        stats["cpu"] = cpu.get("usage", 0)
    except (ValueError, KeyError):
        pass
    return stats


def _parse_mem_limit(val):
    if not val:
        return 0
    m = re.match(r"(\d+)([A-Za-z]+)?", str(val))
    if not m:
        return 0
    n = int(m.group(1))
    unit = (m.group(2) or "B").upper()
    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3}
    return n * mult.get(unit, 1)


def lxc_list():
    code, out, _ = _run(["list", "--format", "json"], timeout=30)
    if code != 0:
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def lxc_exec(name, command, timeout=60):
    if isinstance(command, str):
        command = ["bash", "-lc", command]
    code, out, err = _run(["exec", name, "--"] + command, timeout=timeout)
    return code, out, err


def lxc_shell_command(name):
    """Return the argv used to attach an interactive shell to a container."""
    return [_lxc_bin(), "exec", name, "--env", "TERM=xterm-256color", "--", "/bin/bash", "-l"]


def lxc_regen_ssh(name, password):
    _run(["exec", name, "--", "bash", "-c", "apt-get update -y >/dev/null 2>&1; apt-get install -y openssh-server >/dev/null 2>&1; mkdir -p /var/run/sshd"], timeout=300)
    _run(["exec", name, "--", "bash", "-c", f"echo 'root:{password}' | chpasswd"], timeout=60)
    _run(["exec", name, "--", "bash", "-c", "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config; service ssh restart || /usr/sbin/sshd"], timeout=60)


# ---------------------------------------------------------------------------
# Node routing
# ---------------------------------------------------------------------------
def get_local_node():
    row = db.query("SELECT * FROM nodes WHERE is_local = 1 ORDER BY id LIMIT 1", one=True)
    if row:
        return dict(row)
    nid = db.execute(
        "INSERT INTO nodes (name, hostname, status, is_local, node_url, api_key) VALUES (?, ?, 'online', 1, '', '')",
        ("local", socket.gethostname()),
    )
    return dict(db.query("SELECT * FROM nodes WHERE id = ?", (nid,), one=True))


def call_node_api(node, path, method="GET", data=None, timeout=30):
    """Call a remote node agent. Returns (ok, json)."""
    if not node or node.get("is_local") or not node.get("node_url"):
        return False, {"error": "not a remote node"}
    url = node["node_url"].rstrip("/")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        conn = http.client.HTTPSConnection(host, port, timeout=timeout) if parsed.scheme == "https" else http.client.HTTPConnection(host, port, timeout=timeout)
        headers = {"X-API-Key": node.get("api_key", ""), "Content-Type": "application/json"}
        body = json.dumps(data) if data is not None else None
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode()
        conn.close()
        try:
            return resp.status < 400, json.loads(raw)
        except ValueError:
            return resp.status < 400, {"raw": raw}
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}


def node_for_vps(vps):
    if not vps:
        return get_local_node()
    nid = vps.get("node_id")
    if nid:
        row = db.query("SELECT * FROM nodes WHERE id = ?", (nid,), one=True)
        if row:
            return dict(row)
    return get_local_node()


def refresh_node_stats(node):
    if node.get("is_local"):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            count = len(lxc_list())
            db.execute("UPDATE nodes SET cpu_usage=?, ram_usage=?, vps_count=?, status='online' WHERE id=?", (cpu, ram, count, node["id"]))
        except Exception:  # noqa: BLE001
            pass
    else:
        ok, data = call_node_api(node, "/api/health", timeout=8)
        if ok:
            db.execute("UPDATE nodes SET cpu_usage=?, ram_usage=?, vps_count=?, status='online' WHERE id=?",
                       (data.get("cpu", 0), data.get("ram", 0), data.get("vps_count", 0), node["id"]))
        else:
            db.execute("UPDATE nodes SET status='offline' WHERE id=?", (node["id"],))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_ram_to_bytes(ram):
    return _parse_mem_limit(ram)


def parse_disk_to_bytes(disk):
    return _parse_mem_limit(disk)


def parse_cpu_count(cpu):
    m = re.search(r"(\d+)", str(cpu))
    return int(m.group(1)) if m else 1


def generate_container_name(prefix="cryzon"):
    return f"{prefix}-{int(time.time()) % 100000}-{os.urandom(2).hex()}"


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
