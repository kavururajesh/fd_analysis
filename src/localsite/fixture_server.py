"""Tiny local web server for the local bank-page snapshots. Create the file data/fixtures/.drift to make the Sberbank page change layout."""
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from src.config import settings as S
from src.localsite.build_fixtures import SITE, build

DRIFT_FLAG = S.FIXTURE_DIR / ".drift"
_server = None


def drift_enabled():
    return DRIFT_FLAG.exists()


def set_drift(on: bool):
    if on:
        DRIFT_FLAG.write_text("on")
    elif DRIFT_FLAG.exists():
        DRIFT_FLAG.unlink()


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.split("?")[0] == "/sber.html" and drift_enabled():
            path = "/sber_drift.html"
        return super().translate_path(path)

    def guess_type(self, path):
        t = super().guess_type(path)
        return t + "; charset=utf-8" if t.startswith("text/") else t

    def log_message(self, *a):
        pass


def start():
    """Start once per process (idempotent). Returns the base url."""
    global _server
    base = f"http://127.0.0.1:{S.FIXTURE_PORT}"
    if _server is not None:
        return base
    build()
    handler = functools.partial(Handler, directory=str(SITE))
    try:
        _server = ThreadingHTTPServer(("127.0.0.1", S.FIXTURE_PORT), handler)
    except OSError:                          # already served by another process (e.g. API + UI)
        _server = False
        return base
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return base


if __name__ == "__main__":
    print(start(), "- Ctrl+C to stop")
    threading.Event().wait()
