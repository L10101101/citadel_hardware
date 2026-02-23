import logging
import os
import json
from pathlib import Path
from logging.handlers import RotatingFileHandler


_CONFIGURED = False


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _default_log_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(base) / "Citadel" / "logs"


def configure_logging(app_name: str = "citadel", level: int = logging.INFO) -> Path | None:
    global _CONFIGURED
    if _CONFIGURED:
        return None

    root = logging.getLogger()
    root.setLevel(level)
    log_format = (os.environ.get("CITADEL_LOG_FORMAT") or "text").strip().lower()
    if log_format == "json":
        fmt = JsonLogFormatter()
    else:
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    log_file = None
    try:
        log_dir = _default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{app_name}.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        # Keep app startup resilient even if file logging cannot initialize.
        pass

    logging.captureWarnings(True)
    _CONFIGURED = True
    return log_file
