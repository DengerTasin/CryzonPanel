"""Container operations with a transparent demo fallback.

When LXD is unavailable (or CRYZON_DEMO=1) every operation is simulated so the
whole panel remains fully browsable for demos, screenshots and development.
"""
import os
import random
import time

from . import lxd


def is_demo():
    return os.environ.get("CRYZON_DEMO") == "1" or not lxd.lxc_is_available()


def _demo_ip(name):
    random.seed(hash(name) & 0xFFFF)
    return f"10.132.115.{random.randint(20, 240)}"


def create(name, os_type, ram, cpu, disk, password=None):
    if is_demo():
        time.sleep(0.4)
        return True, "demo container created"
    return lxd.lxc_create(name, os_type, ram, cpu, disk, password)


def start(name):
    if is_demo():
        return True
    return lxd.lxc_start(name)


def stop(name):
    if is_demo():
        return True
    return lxd.lxc_stop(name)


def restart(name):
    if is_demo():
        return True
    return lxd.lxc_restart(name)


def destroy(name):
    if is_demo():
        return True
    return lxd.lxc_destroy(name)


def status(name):
    if is_demo():
        return "running"
    return lxd.lxc_status(name)


def get_ip(name):
    if is_demo():
        return _demo_ip(name)
    return lxd.lxc_get_ip(name)


def get_stats(name, ram, disk, cpu):
    if is_demo():
        random.seed(hash(name) & 0xFFFF)
        ram_total = lxd.parse_ram_to_bytes(ram)
        disk_total = lxd.parse_disk_to_bytes(disk)
        ram_used = int(ram_total * random.uniform(0.18, 0.62))
        disk_used = int(disk_total * random.uniform(0.12, 0.4))
        return {
            "status": "running",
            "cpu": round(random.uniform(2, 42), 1),
            "ram_used": ram_used,
            "ram_total": ram_total,
            "ram_pct": round(ram_used / ram_total * 100, 1) if ram_total else 0,
            "disk_used": disk_used,
            "disk_total": disk_total,
            "disk_pct": round(disk_used / disk_total * 100, 1) if disk_total else 0,
            "processes": random.randint(8, 46),
            "uptime": random.randint(3600, 864000),
        }
    st = lxd.lxc_get_stats(name)
    st["disk_pct"] = round(st["disk_used"] / st["disk_total"] * 100, 1) if st.get("disk_total") else 0
    return st


def exec_cmd(name, command, timeout=60):
    if is_demo():
        return 0, "", ""
    return lxd.lxc_exec(name, command, timeout)


def regen_ssh(name, password):
    if is_demo():
        return True
    return lxd.lxc_regen_ssh(name, password)
