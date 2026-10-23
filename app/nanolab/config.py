import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("NANOLAB_HOME", Path.home() / ".nanolab"))
CFG_PATH = APP_DIR / "config.json"

DEFAULTS = {
    "lang": None,             # "ar" | "fr" | "en" | None (browser decides)
    "port": "",               # last used serial port
    "auto_flash": True,       # upload the right firmware when the project changes
    "flashed": {},            # port -> project last flashed from this app
    "camera": 0,
    "api_key": "",
    "remember_key": False,
    "history_turns": 3,
    "token_budget": 100000,
    "mic_threshold": 0,       # 0 = automatic
    "robo_camera": True,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("GEMINI_API_KEY", "")
    return cfg


def save(cfg: dict):
    data = dict(cfg)
    if not data.get("remember_key"):
        data["api_key"] = ""          # never write the key unless the user ticked the box
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
