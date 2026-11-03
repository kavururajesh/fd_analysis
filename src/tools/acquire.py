"""Open a source (plain HTML, browser page, or PDF), expose its raw tables, and keep audit evidence."""
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

from src.config import settings as S
from src.tools.browser import BrowserManager
from src.tools.html_tables import page_text, parse_html_tables, pdf_tables, pdf_text
from src.tools.sources import SourceConfig
from src.utils.helpers import now_iso, sha256

_DATE = r"(\d{1,2}[-/ .](?:\d{1,2}|[A-Za-z]{3,9})[-/ .,]+\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})"
_EFFECTIVE = re.compile(r"(?:effective|w\.?e\.?f\.?|with effect from|valid(?: from| for)?|as (?:of|on))\W{0,12}" + _DATE, re.I)


def detect_effective_date(text: str) -> Optional[str]:
    """First date written next to 'effective / w.e.f. / valid / as on' -> ISO date, else None."""
    for m in _EFFECTIVE.finditer(text or ""):
        d = pd.to_datetime(m.group(1), dayfirst=True, errors="coerce")
        if pd.notna(d) and 2000 <= d.year <= 2100:
            return d.date().isoformat()
    return None


def _decode(r):
    """requests guesses latin-1 for pages without a charset header; bank pages are UTF-8 (the rupee sign breaks otherwise)."""
    if "charset" in r.headers.get("content-type", "").lower():
        return r.text
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        return r.text


class SourceSession:
    def __init__(self, source: SourceConfig, browser: BrowserManager, evidence_dir: Path = None):
        self.source, self.browser = source, browser
        self.evidence_dir = Path(evidence_dir or S.STAGING_DIR)
        self.page = None
        self.tables: List[pd.DataFrame] = []
        self.title, self.text, self._html, self._pdf = "", "", "", None

    # ---------- open ----------
    def open(self) -> dict:
        kind = self.source.kind
        if kind == "browser":
            self._open_browser()
        elif kind == "html":
            r = self._get(self.source.url)
            self._html = _decode(r)
            self.tables, self.text = parse_html_tables(self._html), page_text(self._html)
        elif kind == "pdf":
            self._pdf = self._get(self.source.url).content
            self.tables, self.text = pdf_tables(self._pdf), pdf_text(self._pdf)
        else:
            raise ValueError(f"unknown source kind '{kind}' (use html, browser or pdf)")
        return self.summary()

    @staticmethod
    def _get(url):
        r = requests.get(url, headers={"User-Agent": S.USER_AGENT}, timeout=60)
        r.raise_for_status()
        return r

    def _open_browser(self):
        self.page = self.browser.new_page()
        self.page.goto(self.source.url, wait_until="load")
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        for action in self.source.actions:
            self._do(action)
        self._refresh()

    def _do(self, action):
        if "click" in action:
            self.page.click(action["click"])
        elif "select" in action:
            self.page.select_option(action["select"]["selector"], action["select"]["value"])
        elif "wait_ms" in action:
            self.page.wait_for_timeout(int(action["wait_ms"]))
        self.page.wait_for_timeout(int(action.get("wait_ms", 600)) if "wait_ms" not in action else 0)

    def _refresh(self):
        self._html = self.page.content()
        self.tables = parse_html_tables(self._html)
        self.title = self.page.title()
        try:
            self.text = self.page.inner_text("body")
        except Exception:
            self.text = page_text(self._html)

    def click(self, selector: str) -> dict:
        if self.page is None:
            raise ValueError("click is only possible for browser sources")
        self.page.click(selector, timeout=10000)
        self.page.wait_for_timeout(800)
        self._refresh()
        return self.summary()

    # ---------- info ----------
    @property
    def effective_detected(self):
        return detect_effective_date(self.text)

    def summary(self) -> dict:
        return dict(url=self.source.url, kind=self.source.kind, title=self.title, n_tables=len(self.tables),
                    effective_detected=self.effective_detected)

    def save_evidence(self, run_id: str) -> dict:
        d = self.evidence_dir / run_id / "evidence"
        d.mkdir(parents=True, exist_ok=True)
        info = dict(url=self.source.url, retrieved_at=now_iso(), n_tables=len(self.tables), title=self.title,
                    effective_detected=self.effective_detected)
        try:
            if self.page is not None:
                path = d / f"{self.source.id}.png"
                self.page.screenshot(path=str(path), full_page=True)
                info["screenshot"], info["sha256"] = str(path), sha256(self._html)
            elif self._pdf is not None:
                path = d / f"{self.source.id}.pdf"
                path.write_bytes(self._pdf)
                info["file"], info["sha256"] = str(path), sha256(self._pdf)
            else:
                path = d / f"{self.source.id}.html"
                path.write_text(self._html, encoding="utf-8")
                info["file"], info["sha256"] = str(path), sha256(self._html)
        except Exception as e:                       # evidence is best-effort
            info["evidence_error"] = str(e)
        return info

    def close(self):
        if self.page is not None:
            try:
                self.page.context.close()
            except Exception:
                pass
            self.page = None
