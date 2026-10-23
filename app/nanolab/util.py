import sys
from pathlib import Path


def resource_path(rel: str) -> Path:
    """Path of a bundled resource (works from source and from a PyInstaller build)."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[1]
    return root / rel
