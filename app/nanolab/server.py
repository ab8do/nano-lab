"""Tiny local web server: the control panel (web/index.html), a JSON API and the camera stream."""
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, config, flasher, logbus
from .logbus import log
from .preview import PREVIEW
from .util import resource_path

PROJECTS = ("dino", "games", "robo")


class AppState:
    def __init__(self, token):
        self.token = token
        self.cfg = config.load()
        self.engine = None
        self.project = None
        self.busy = False
        self.flash = {"active": False, "project": "", "code": ""}
        self.lock = threading.Lock()
        self.quit = threading.Event()

    # ---------------------------------------------------------------- engines
    def stop_engine(self):
        eng = self.engine
        if eng:
            eng.request_stop()
            if eng.thread:
                eng.thread.join(timeout=8)
        self.engine = None
        self.project = None

    def make_engine(self, project, port):
        if project == "dino":
            from .dino import DinoEngine as E
        elif project == "games":
            from .games import GamesEngine as E
        else:
            from .robo import RoboEngine as E
        return E(dict(self.cfg), port)

    def do_flash(self, project, port):
        self.flash = {"active": True, "project": project, "code": ""}
        ok, code = False, "failed"
        try:
            ok, code = flasher.flash(project, port)
        finally:
            self.flash = {"active": False, "project": project, "code": "ok" if ok else code}
        if ok:
            self.cfg.setdefault("flashed", {})[port] = project
            config.save(self.cfg)
        return ok

    def start_job(self, project, port):
        with self.lock:
            if self.busy:
                return
            self.busy = True
        try:
            self.stop_engine()
            self.cfg["port"] = port
            config.save(self.cfg)
            av = flasher.availability()
            need = (self.cfg.get("auto_flash", True) and av["avrdude"] and av.get(project)
                    and self.cfg.get("flashed", {}).get(port) != project)
            if need and not self.do_flash(project, port):
                return
            try:
                eng = self.make_engine(project, port)
            except Exception as e:                      # missing library in a source install
                log(f"Cannot start {project}: {e}")
                self.flash = {"active": False, "project": project, "code": "import:" + str(e)[:120]}
                return
            self.engine, self.project = eng, project
            eng.start()
        finally:
            self.busy = False

    def flash_job(self, project, port):
        with self.lock:
            if self.busy:
                return
            self.busy = True
        try:
            self.stop_engine()
            self.do_flash(project, port)
        finally:
            self.busy = False

    # ---------------------------------------------------------------- state for the page
    def snapshot(self, since):
        try:
            from serial.tools import list_ports
            ports = []
            for p in list_ports.comports():
                likely = (p.vid or 0) in (0x2341, 0x1A86, 0x0403, 0x10C4)
                ports.append({"device": p.device, "desc": p.description or "", "likely": likely})
            ports.sort(key=lambda x: (not x["likely"], x["device"]))
        except Exception:
            ports = []
        eng = self.engine
        c = self.cfg
        lines, seq = logbus.since(since)
        return {
            "version": __version__, "busy": self.busy, "ports": ports,
            "cfg": {k: c.get(k) for k in ("lang", "port", "auto_flash", "camera", "history_turns",
                                          "token_budget", "mic_threshold", "robo_camera", "remember_key")}
                   | {"has_key": bool(c.get("api_key"))},
            "engine": {"project": self.project, "status": eng.status if eng else "idle",
                       "error": eng.error if eng else None, "info": eng.info if eng else {}},
            "flash": self.flash, "firmware": flasher.availability(),
            "log": {"lines": [l for _, l in lines], "seq": seq},
        }


def make_handler(app: AppState, port_holder):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # -- security: only our page on 127.0.0.1 with the session token
        def _ok(self, q):
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{port_holder[0]}", f"localhost:{port_holder[0]}"):
                return False
            tok = self.headers.get("X-Token") or (q.get("t") or [""])[0]
            return secrets.compare_digest(tok, app.token)

        def _send(self, code, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._ok(q):
                return self._send(403, {"error": "forbidden"})
            if u.path == "/":
                html = resource_path("web/index.html").read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                return self._send(200, html, "text/html")
            if u.path == "/api/state":
                since = int((q.get("since") or ["0"])[0] or 0)
                return self._send(200, app.snapshot(since))
            if u.path == "/video":
                return self._stream()
            self._send(404, {"error": "not found"})

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            last = -1
            try:
                while not app.quit.is_set():
                    jpg, stamp = PREVIEW.get()
                    if jpg and stamp != last:
                        last = stamp
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def do_POST(self):
            u = urlparse(self.path)
            if not self._ok(parse_qs(u.query)):
                return self._send(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except Exception:
                return self._send(400, {"error": "bad json"})
            p = u.path
            if p == "/api/config":
                for k in ("lang", "port", "auto_flash", "camera", "history_turns", "token_budget",
                          "mic_threshold", "robo_camera", "remember_key", "api_key"):
                    if k in body:
                        app.cfg[k] = body[k]
                config.save(app.cfg)
                return self._send(200, {"ok": True})
            if p in ("/api/start", "/api/flash"):
                project, port = body.get("project"), body.get("port")
                if project not in PROJECTS or not port:
                    return self._send(400, {"error": "project and port required"})
                target = app.start_job if p == "/api/start" else app.flash_job
                threading.Thread(target=target, args=(project, port), daemon=True).start()
                return self._send(200, {"ok": True})
            if p == "/api/stop":
                threading.Thread(target=app.stop_engine, daemon=True).start()
                return self._send(200, {"ok": True})
            if p == "/api/command":
                if app.engine:
                    app.engine.command(str(body.get("name", "")))
                return self._send(200, {"ok": True})
            if p == "/api/quit":
                self._send(200, {"ok": True})
                app.quit.set()
                return
            self._send(404, {"error": "not found"})

    return H


def run_server(open_browser=True, port=0):
    import webbrowser
    app = AppState(secrets.token_urlsafe(24))
    holder = [0]
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, holder))
    srv.daemon_threads = True
    holder[0] = srv.server_address[1]
    url = f"http://127.0.0.1:{holder[0]}/?t={app.token}"
    log(f"Nano Lab {__version__} control panel: {url}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while not app.quit.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_engine()
        srv.shutdown()
    return app
