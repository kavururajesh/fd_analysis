"""Long-term memory (SQLite): datasets per run, per-source results + evidence, layout specs, agent traces."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from src.config.settings import DB_PATH, KEEP_RUNS
from src.domain.schema import COLUMNS
from src.utils.helpers import dumps, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, created TEXT, status TEXT, mode TEXT, reasons TEXT, qa TEXT, brief TEXT, decided_by TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS rates(run_id TEXT, source_id TEXT, bank TEXT, product TEXT, series TEXT, status TEXT, effective TEXT,
  amt_label TEXT, tenor_label TEXT, amt_lo REAL, amt_hi REAL, d_lo INTEGER, d_hi INTEGER, rate REAL);
CREATE INDEX IF NOT EXISTS idx_rates_run ON rates(run_id);
CREATE TABLE IF NOT EXISTS source_results(run_id TEXT, source_id TEXT, ok INTEGER, method TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS specs(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, spec TEXT, origin TEXT, run_id TEXT, created TEXT, approved INTEGER DEFAULT 0, approved_at TEXT);
CREATE TABLE IF NOT EXISTS traces(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts TEXT, agent TEXT, kind TEXT, text TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
"""


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as con, con:
            con.executescript(SCHEMA)

    def _conn(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    # ------------- runs -------------
    def save_run(self, run_id, status, mode, df, source_results, reasons=None, qa=None, brief=None):
        with closing(self._conn()) as con, con:
            con.execute("INSERT OR REPLACE INTO runs(run_id,created,status,mode,reasons,qa,brief) VALUES(?,?,?,?,?,?,?)",
                        (run_id, now_iso(), status, mode, dumps(reasons or []), dumps(qa or {}), brief))
            con.execute("DELETE FROM rates WHERE run_id=?", (run_id,))
            con.execute("DELETE FROM source_results WHERE run_id=?", (run_id,))
            if df is not None and len(df):
                df[COLUMNS].assign(run_id=run_id).to_sql("rates", con, if_exists="append", index=False)
            for r in source_results:
                con.execute("INSERT INTO source_results(run_id,source_id,ok,method,detail) VALUES(?,?,?,?,?)",
                            (run_id, r["source_id"], int(r["ok"]), r["method"], dumps(r.get("detail", {}))))
        self.prune()

    def get_run(self, run_id):
        with closing(self._conn()) as con:
            row = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            run = dict(row)
            for k in ("reasons", "qa"):
                run[k] = json.loads(run[k] or "null")
            run["sources"] = [dict(r, detail=json.loads(r["detail"] or "{}")) for r in
                              con.execute("SELECT * FROM source_results WHERE run_id=?", (run_id,))]
            return run

    def list_runs(self, limit=30):
        with closing(self._conn()) as con:
            return pd.read_sql("SELECT run_id, created, status, mode, decided_by, decided_at FROM runs ORDER BY created DESC LIMIT ?",
                               con, params=[limit])

    def load_rates(self, run_id):
        with closing(self._conn()) as con:
            df = pd.read_sql("SELECT * FROM rates WHERE run_id=?", con, params=[run_id])
        return df.drop(columns="run_id")

    def published_ids(self):
        with closing(self._conn()) as con:
            return [r["run_id"] for r in con.execute("SELECT run_id FROM runs WHERE status='published' ORDER BY created DESC")]

    def published(self, offset=0):
        """(run_id, rates DataFrame) of the offset-th latest published run, or (None, None)."""
        ids = self.published_ids()
        if len(ids) <= offset:
            return None, None
        return ids[offset], self.load_rates(ids[offset])

    def set_status(self, run_id, status, by="system"):
        with closing(self._conn()) as con, con:
            con.execute("UPDATE runs SET status=?, decided_by=?, decided_at=? WHERE run_id=?", (status, by, now_iso(), run_id))

    def supersede_pending(self, except_run):
        """A newer dataset went live: older runs still waiting for review can no longer be approved."""
        with closing(self._conn()) as con, con:
            con.execute("UPDATE runs SET status='superseded' WHERE status IN ('pending_review') AND run_id<>?", (except_run,))

    def history(self, limit=60):
        """[(run_id, created, DataFrame)] of published runs, oldest first - for trend charts."""
        ids = self.published_ids()[:limit][::-1]
        with closing(self._conn()) as con:
            created = {r["run_id"]: r["created"] for r in con.execute("SELECT run_id, created FROM runs")}
        return [(i, created.get(i), self.load_rates(i)) for i in ids]

    def set_brief(self, run_id, brief):
        with closing(self._conn()) as con, con:
            con.execute("UPDATE runs SET brief=? WHERE run_id=?", (brief, run_id))

    def prune(self, keep=KEEP_RUNS):
        with closing(self._conn()) as con, con:
            ids = [r["run_id"] for r in con.execute("SELECT run_id FROM runs ORDER BY created DESC")]
            keep_ids = set(ids[:keep]) | set(self.published_ids()[:1])
            for rid in ids:
                if rid not in keep_ids:
                    for t in ("runs", "rates", "source_results", "traces"):
                        con.execute(f"DELETE FROM {t} WHERE run_id=?", (rid,))

    # ------------- layout specs -------------
    def save_spec(self, source_id, spec, origin, run_id, approved=False):
        with closing(self._conn()) as con, con:
            con.execute("INSERT INTO specs(source_id,spec,origin,run_id,created,approved,approved_at) VALUES(?,?,?,?,?,?,?)",
                        (source_id, json.dumps(spec), origin, run_id, now_iso(), int(approved), now_iso() if approved else None))

    def get_spec(self, source_id):
        """Latest APPROVED layout spec for a source, or None."""
        with closing(self._conn()) as con:
            row = con.execute("SELECT spec FROM specs WHERE source_id=? AND approved=1 ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
        return json.loads(row["spec"]) if row else None

    def approve_specs(self, run_id):
        with closing(self._conn()) as con, con:
            con.execute("UPDATE specs SET approved=1, approved_at=? WHERE run_id=? AND approved=0", (now_iso(), run_id))

    def list_specs(self, limit=50):
        with closing(self._conn()) as con:
            return pd.read_sql("SELECT id, source_id, origin, run_id, created, approved, spec FROM specs ORDER BY id DESC LIMIT ?", con, params=[limit])

    # ------------- traces -------------
    def add_trace(self, run_id, agent, kind, text, data=None):
        with closing(self._conn()) as con, con:
            con.execute("INSERT INTO traces(run_id,ts,agent,kind,text,data) VALUES(?,?,?,?,?,?)",
                        (run_id, now_iso(), agent, kind, text, dumps(data) if data is not None else None))

    def get_traces(self, run_id):
        with closing(self._conn()) as con:
            return pd.read_sql("SELECT ts, agent, kind, text FROM traces WHERE run_id=? ORDER BY id", con, params=[run_id])
