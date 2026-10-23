import threading

from .link import Link
from .logbus import log


class Engine:
    """Base class: one running project (a background thread that talks to the Arduino)."""
    name = ""
    baud = 57600

    def __init__(self, cfg: dict, port: str):
        self.cfg, self.port = cfg, port
        self.stop = threading.Event()
        self.thread = None
        self.status = "idle"
        self.error = None
        self.info = {}
        self.link = None

    def start(self):
        self.thread = threading.Thread(target=self._main, daemon=True, name=self.name)
        self.thread.start()

    def _main(self):
        try:
            self.status = "starting"
            log(f"{self.name}: opening {self.port} at {self.baud} baud")
            self.link = Link(self.port, self.baud)
            self.status = "running"
            self.run()
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
            log(f"{self.name}: error: {self.error}")
        finally:
            if self.link:
                try:
                    self.cleanup()
                except Exception:
                    pass
                self.link.close()
            self.status = "stopped"
            log(f"{self.name}: stopped")

    def request_stop(self):
        self.stop.set()

    def run(self):                    # implemented by subclasses
        raise NotImplementedError

    def cleanup(self):                # optional
        pass

    def command(self, name: str):     # optional (e.g. "menu")
        pass
