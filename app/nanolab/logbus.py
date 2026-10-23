import collections
import threading
import time

from .config import APP_DIR

_lock = threading.Lock()
_lines = collections.deque(maxlen=500)
_seq = 0


def log(msg: str):
    """Append a line to the in-app log (and to ~/.nanolab/app.log)."""
    global _seq
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    with _lock:
        _seq += 1
        _lines.append((_seq, line))
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(APP_DIR / "app.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def since(n: int):
    with _lock:
        return [(s, l) for s, l in _lines if s > n], _seq
