"""Live market snapshot shared between the Streamlit dashboard (writer) and the trader (reader)."""
import json
import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "history" / "live_rules.json"


def write_snapshot(payload, path=SNAPSHOT_PATH):
    """Write atomically so the trader never reads a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temp, path)


def read_snapshot(path=SNAPSHOT_PATH, now=None, max_age=5.0):
    """(snapshot or None, age in seconds or None). None when missing, unreadable or too old."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        age = (now if now is not None else time.time()) - float(data["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, None
    return (data if age <= max_age else None), age
