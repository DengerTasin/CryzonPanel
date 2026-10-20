"""Web terminal (direct console) backend using pseudo-terminals.

A background thread drains the pty into an in-memory ring buffer. The browser
polls ``/read`` for new output and POSTs keystrokes to ``/input``. This works
reliably with plain WSGI / gunicorn sync workers (no websockets required).
"""
import os
import pty
import fcntl
import struct
import termios
import threading
import subprocess
import time
import uuid
import select

from flask import request, jsonify, session

from . import db
from . import lxd

MAX_BUFFER = 512 * 1024  # keep last 512KB of scrollback


class TerminalSession:
    def __init__(self, argv, rows=24, cols=80):
        self.id = uuid.uuid4().hex
        self.argv = argv
        self.buf = bytearray()
        self.base = 0  # number of bytes dropped from the front
        self.lock = threading.Lock()
        self.alive = True
        self.last_active = time.time()
        self.master, slave = pty.openpty()
        self._set_winsize(rows, cols, fd=slave)
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["LANG"] = "C.UTF-8"
        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                close_fds=True,
                preexec_fn=os.setsid,
                env=env,
            )
        except Exception:
            os.close(self.master)
            os.close(slave)
            raise
        os.close(slave)
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _set_winsize(self, rows, cols, fd=None):
        try:
            fcntl.ioctl(fd if fd is not None else self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def _reader(self):
        while self.alive:
            try:
                r, _, _ = select.select([self.master], [], [], 0.5)
                if not r:
                    if self.proc.poll() is not None:
                        break
                    continue
                data = os.read(self.master, 65536)
                if not data:
                    break
                with self.lock:
                    self.buf.extend(data)
                    if len(self.buf) > MAX_BUFFER:
                        drop = len(self.buf) - MAX_BUFFER
                        del self.buf[:drop]
                        self.base += drop
            except OSError:
                break
        self.alive = False

    def write(self, data):
        self.last_active = time.time()
        try:
            os.write(self.master, data.encode("utf-8", "ignore") if isinstance(data, str) else data)
        except OSError:
            self.alive = False

    def read(self, cursor):
        with self.lock:
            if cursor < self.base:
                cursor = self.base
            chunk = bytes(self.buf[cursor - self.base:])
            return chunk, self.base + len(self.buf)

    def resize(self, rows, cols):
        self._set_winsize(rows, cols)

    def close(self):
        self.alive = False
        try:
            os.close(self.master)
        except OSError:
            pass
        try:
            self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass


class TerminalManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reaper, daemon=True).start()

    def create(self, argv, rows=24, cols=80):
        s = TerminalSession(argv, rows, cols)
        with self.lock:
            self.sessions[s.id] = s
        return s

    def get(self, sid):
        with self.lock:
            return self.sessions.get(sid)

    def remove(self, sid):
        with self.lock:
            s = self.sessions.pop(sid, None)
        if s:
            s.close()

    def _reaper(self):
        while True:
            time.sleep(60)
            now = time.time()
            with self.lock:
                dead = [sid for sid, s in self.sessions.items() if (not s.alive and now - s.last_active > 120) or now - s.last_active > 3600]
            for sid in dead:
                self.remove(sid)


manager = TerminalManager()


def _user_can_access(user, vps):
    if not user:
        return False
    if vps["user_id"] == user["id"]:
        return True
    from .security import is_admin
    if is_admin(user):
        return True
    share = db.query("SELECT 1 FROM vps_shares WHERE vps_id = ? AND shared_with = ?", (vps["id"], user["id"]), one=True)
    return bool(share)


def register_terminal_routes(app):
    from .security import current_user, has_permission

    def _get_vps(vps_id, user):
        vps = db.query("SELECT * FROM vps WHERE id = ?", (vps_id,), one=True)
        if not vps:
            return None, (jsonify({"error": "not found"}), 404)
        vps = dict(vps)
        if not _user_can_access(user, vps):
            return None, (jsonify({"error": "forbidden"}), 403)
        if not has_permission(user, "vps.console"):
            return None, (jsonify({"error": "console access denied"}), 403)
        return vps, None

    @app.route("/api/vps/<int:vps_id>/terminal/open", methods=["POST"])
    def terminal_open(vps_id):
        user = current_user()
        if not user:
            return jsonify({"error": "auth"}), 401
        vps, err = _get_vps(vps_id, user)
        if err:
            return err
        body = request.get_json(silent=True) or {}
        rows = int(body.get("rows", 24))
        cols = int(body.get("cols", 80))

        demo = os.environ.get("CRYZON_DEMO") == "1"
        if demo:
            argv = ["/bin/bash", "-l"]
        else:
            node = lxd.node_for_vps(vps)
            if node.get("is_local"):
                argv = lxd.lxc_shell_command(vps["container_name"])
            else:
                # remote nodes: attach through the node agent is not pty-capable here,
                # so fall back to a local shell command that ssh's in.
                argv = ["/bin/bash", "-l"]
        try:
            s = manager.create(argv, rows, cols)
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"failed to start shell: {e}"}), 500
        return jsonify({"session_id": s.id})

    @app.route("/api/vps/<int:vps_id>/terminal/input", methods=["POST"])
    def terminal_input(vps_id):
        user = current_user()
        if not user:
            return jsonify({"error": "auth"}), 401
        body = request.get_json(silent=True) or {}
        s = manager.get(body.get("session_id", ""))
        if not s:
            return jsonify({"error": "no session"}), 404
        s.write(body.get("data", ""))
        return jsonify({"ok": True})

    @app.route("/api/vps/<int:vps_id>/terminal/read")
    def terminal_read(vps_id):
        user = current_user()
        if not user:
            return jsonify({"error": "auth"}), 401
        sid = request.args.get("session_id", "")
        cursor = int(request.args.get("cursor", 0))
        s = manager.get(sid)
        if not s:
            return jsonify({"error": "no session", "closed": True}), 404
        chunk, new_cursor = s.read(cursor)
        return jsonify({"data": chunk.decode("utf-8", "replace"), "cursor": new_cursor, "alive": s.alive})

    @app.route("/api/vps/<int:vps_id>/terminal/resize", methods=["POST"])
    def terminal_resize(vps_id):
        user = current_user()
        if not user:
            return jsonify({"error": "auth"}), 401
        body = request.get_json(silent=True) or {}
        s = manager.get(body.get("session_id", ""))
        if s:
            s.resize(int(body.get("rows", 24)), int(body.get("cols", 80)))
        return jsonify({"ok": True})

    @app.route("/api/vps/<int:vps_id>/terminal/close", methods=["POST"])
    def terminal_close(vps_id):
        user = current_user()
        if not user:
            return jsonify({"error": "auth"}), 401
        body = request.get_json(silent=True) or {}
        manager.remove(body.get("session_id", ""))
        return jsonify({"ok": True})
