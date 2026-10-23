import threading
import time

from .logbus import log


class Link:
    """Thread-safe serial connection to the Arduino."""

    def __init__(self, port: str, baud: int):
        import serial
        self.port, self.baud = port, baud
        self.ser = serial.Serial(port, baud, timeout=0.01)
        self.lock = threading.Lock()
        self._warned = False
        time.sleep(2)                       # the Nano resets when the port is opened

    def write(self, data: bytes):
        with self.lock:
            try:
                self.ser.write(bytes(data))
            except Exception as e:
                if not self._warned:
                    self._warned = True
                    log(f"Serial write error: {e}")

    def cmd(self, c: str):
        self.write(bytes([254, ord(c)]))

    def gaze(self, x, y):
        self.write(bytes([255, int(max(0, min(100, x))), int(max(0, min(100, y)))]))

    def mouth(self, level):
        self.write(bytes([253, int(max(0, min(100, level)))]))

    def energy(self, pct):
        self.write(bytes([252, int(max(0, min(100, pct)))]))

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass
