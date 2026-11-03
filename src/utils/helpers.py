"""Small shared helpers (no business logic)."""
import hashlib
import json
from datetime import datetime

import numpy as np


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def new_run_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else str(data).encode("utf-8")).hexdigest()


def truncate(text, limit=3000):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"... [truncated {len(text) - limit} chars]"


def clean(x):
    """Make nested data JSON-safe: numpy -> python, NaN -> None, floats to 2 decimals."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if np.isnan(x) else round(float(x), 2)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def dumps(obj, limit=None):
    text = json.dumps(clean(obj), ensure_ascii=False, default=str, separators=(",", ":"))
    return truncate(text, limit) if limit else text
