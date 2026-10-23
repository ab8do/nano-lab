"""Upload the firmware of a project to the Arduino Nano with a bundled avrdude."""
import shutil
import subprocess
import sys

from .logbus import log
from .util import resource_path

FIRMWARE = {"dino": "firmware/dino.hex", "games": "firmware/games.hex", "robo": "firmware/robo.hex"}


def find_avrdude():
    exe = "avrdude.exe" if sys.platform == "win32" else "avrdude"
    bundled = resource_path(f"tools/avrdude/bin/{exe}")
    conf = resource_path("tools/avrdude/etc/avrdude.conf")
    if bundled.exists():
        return str(bundled), (str(conf) if conf.exists() else None)
    system = shutil.which("avrdude")
    return (system, None) if system else (None, None)


def hex_for(project):
    p = resource_path(FIRMWARE[project])
    return p if p.exists() else None


def availability():
    exe, _ = find_avrdude()
    return {"avrdude": bool(exe), **{k: bool(hex_for(k)) for k in FIRMWARE}}


def flash(project: str, port: str):
    """Returns (ok, code). Tries the new bootloader speed first, then the old one (many clones)."""
    exe, conf = find_avrdude()
    if not exe:
        return False, "no_avrdude"
    hx = hex_for(project)
    if not hx:
        return False, "no_hex"
    dev = port
    if sys.platform == "win32" and not port.startswith("\\\\.\\"):
        dev = "\\\\.\\" + port                       # needed for COM10 and above
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    for baud in (115200, 57600):
        cmd = [exe] + (["-C", conf] if conf else []) + [
            "-p", "atmega328p", "-c", "arduino", "-P", dev, "-b", str(baud), "-D", "-U", f"flash:w:{hx}:i"]
        log(f"Flashing {project} ({baud} baud)...")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=flags)
        except Exception as e:
            log(f"avrdude could not run: {e}")
            return False, "failed"
        tail = [l for l in (r.stderr or "").replace("\r", "\n").splitlines() if l.strip()][-3:]
        if r.returncode == 0:
            log("Flash complete: " + (tail[-1] if tail else "ok"))
            return True, "ok"
        log("avrdude: " + " | ".join(tail))
    return False, "failed"
