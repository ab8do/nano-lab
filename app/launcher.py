"""Nano Lab: start the local control panel and open it in the browser."""
import argparse
import os
import sys
import traceback


def _fatal(msg):
    try:
        from nanolab.logbus import log
        log(msg)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg[-900:], "Nano Lab", 0x10)
        except Exception:
            pass


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ap.add_argument("--port", type=int, default=0, help="fixed local port (default: random free port)")
    args = ap.parse_args()
    try:
        from nanolab.server import run_server
        run_server(open_browser=not args.no_browser, port=args.port)
    except Exception:
        _fatal("Nano Lab could not start:\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
