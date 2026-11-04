"""Parallel collection of many sources at once.

Design (why it is safe):
- Worker threads. Each worker owns its OWN Playwright browser (the sync API is bound to the thread that created it), so
  browsers are never shared between threads. One browser per worker, one isolated context (page) per source.
- Shared work queue. A source is taken by exactly one worker. Results are written once, under a lock, keyed by source id;
  the dataset is assembled later in CONFIG order, so the output does not depend on which source finished first.
- Politeness gate. At most N simultaneous requests per website (default 1): two PDFs on the same host never hit it together.
  A worker that finds a host busy puts the source back and takes another one, so no worker sits idle.
- LLM gate. Self-healing calls GigaChat; at most N calls run at the same time so the gateway is not flooded.
- Failure isolation. One source failing (or crashing, or timing out) never stops the others. Transient network errors are
  retried with back-off. A total deadline protects the run from a hung page.
- workers=1 runs everything in the calling thread with the browser it was given (the old, sequential behaviour)."""
import queue
import re
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from src.agent.collector import CollectorAgent, CollectResult
from src.config import settings as S
from src.config.logging_config import get_logger
from src.tools.sources import SourceConfig

log = get_logger(__name__)

_TRANSIENT = re.compile(r"timeout|timed out|connection|net::err|temporar|reset by peer|\b50[234]\b|\b429\b|name resolution|ssl", re.I)


class LimitedLLM:
    """One LLM shared by all workers, with a cap on simultaneous calls."""

    def __init__(self, llm, limit: int):
        self._llm, self._sem = llm, threading.Semaphore(max(1, limit))
        self.is_offline = getattr(llm, "is_offline", False)

    def chat(self, *a, **k):
        with self._sem:
            return self._llm.chat(*a, **k)

    def __getattr__(self, name):
        return getattr(self._llm, name)


class HostGate:
    """At most `limit` simultaneous requests per website."""

    def __init__(self, limit: int):
        self.limit, self._sems, self._lock = max(1, limit), {}, threading.Lock()

    def sem(self, url: str) -> threading.Semaphore:
        host = urlparse(url).netloc.lower() or "-"
        with self._lock:
            if host not in self._sems:
                self._sems[host] = threading.Semaphore(self.limit)
            return self._sems[host]


class ParallelCollector:
    def __init__(self, llm, store, trace, evidence_dir, browser_factory: Callable = None, workers: int = None,
                 per_host: int = None, llm_limit: int = None, retries: int = None, total_deadline_s: int = None,
                 agent_factory: Callable = None):
        self.store, self.trace, self.evidence_dir = store, trace, evidence_dir
        self.workers = max(1, workers if workers is not None else S.COLLECT_WORKERS)
        self.llm = LimitedLLM(llm, llm_limit if llm_limit is not None else S.COLLECT_LLM_LIMIT)
        self.gate = HostGate(per_host if per_host is not None else S.COLLECT_PER_HOST)
        self.retries = retries if retries is not None else S.COLLECT_RETRIES
        self.deadline = total_deadline_s if total_deadline_s is not None else S.COLLECT_TOTAL_DEADLINE_S
        self.browser_factory = browser_factory
        self.agent_factory = agent_factory or (lambda browser: CollectorAgent(self.llm, store, browser, trace, evidence_dir))

    # ---------- one source, with retry ----------
    def _collect_one(self, agent, source: SourceConfig, run_id, prev) -> CollectResult:
        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            try:
                r = agent.collect(source, run_id, prev)
            except Exception as e:                                           # a crash in one source must not stop the others
                r = CollectResult(source.id, False, "failed", errors=[f"{type(e).__name__}: {e}"])
            r.metrics = dict(r.metrics or {}, seconds=round(time.time() - t0, 1), attempts=attempt)
            transient = (not r.ok) and any(_TRANSIENT.search(str(e)) for e in r.errors)
            if r.ok or not transient or attempt > self.retries:
                return r
            self.trace.emit(f"collector:{source.id}", "warning", f"Temporary problem ({r.errors[0][:120]}); retrying ({attempt}/{self.retries})")
            time.sleep(min(2 ** attempt, 8))

    # ---------- the shared worker pool ----------
    def _pool(self, sources, make_ctx, work, on_timeout, label, browser=None):
        """Run work(ctx, source) for every source. make_ctx(browser_manager) builds the per-worker context (inside the worker
        thread). Returns {source_id: result}. With one worker everything runs inline using `browser`."""
        results = {}
        if not sources:
            return results
        n_workers = min(self.workers, len(sources))
        t0 = time.time()
        if n_workers <= 1:
            ctx = make_ctx(browser)
            for s in sources:
                results[s.id] = work(ctx, s)
            return results
        self.trace.emit("supervisor", "info", f"{label} {len(sources)} sources in parallel with {n_workers} workers")
        q: "queue.Queue[SourceConfig]" = queue.Queue()
        for s in sources:
            q.put(s)
        lock, remaining = threading.Lock(), [len(sources)]

        def worker(idx: int):
            bm = self.browser_factory() if self.browser_factory else None
            ctx = make_ctx(bm)
            try:
                while True:
                    with lock:
                        if remaining[0] <= 0:
                            return
                    try:
                        s = q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    sem = self.gate.sem(s.url)
                    if not sem.acquire(blocking=False):                    # host busy: let another source go first
                        q.put(s)
                        time.sleep(0.15)
                        continue
                    try:
                        r = work(ctx, s)
                    finally:
                        sem.release()
                    with lock:
                        results[s.id] = r
                        remaining[0] -= 1
                        done = len(sources) - remaining[0]
                    ok = getattr(r, "ok", None) if not isinstance(r, dict) else r.get("ok")
                    self.trace.emit("supervisor", "info", f"{s.id}: {'ok' if ok else 'FAILED'} ({done}/{len(sources)} done)")
            finally:
                if bm is not None:
                    try:
                        bm.close()                                         # closed by the same thread that opened it
                    except Exception:
                        pass

        threads = [threading.Thread(target=worker, args=(i,), name=f"collector-{i}", daemon=True) for i in range(n_workers)]
        for t in threads:
            t.start()
        end = t0 + self.deadline
        for t in threads:
            t.join(timeout=max(0.0, end - time.time()))
        with lock:
            for s in sources:                                              # anything still missing timed out
                if s.id not in results:
                    results[s.id] = on_timeout(s, f"timed out after {self.deadline}s")
        self.trace.emit("supervisor", "info", f"{label} finished in {time.time() - t0:.1f}s")
        return results

    # ---------- public ----------
    def collect(self, sources: List[SourceConfig], run_id: str, prev, browser=None) -> Dict[str, CollectResult]:
        return self._pool(sources, self.agent_factory, lambda agent, s: self._collect_one(agent, s, run_id, prev),
                          lambda s, msg: CollectResult(s.id, False, "failed", errors=[msg]), "Collecting", browser)

    def probe(self, sources: List[SourceConfig], browser=None) -> Dict[str, dict]:
        """Open every source (no extraction) and report what was found - used to calibrate new banks quickly."""
        def make_ctx(bm):
            return bm

        def work(bm, s):
            from src.tools.acquire import SourceSession
            t0 = time.time()
            sess = SourceSession(s, bm or browser)
            try:
                info = sess.open()
                return dict(id=s.id, bank=s.bank, kind=s.kind, ok=info["n_tables"] > 0, tables=info["n_tables"],
                            effective=info["effective_detected"] or "", seconds=round(time.time() - t0, 1), error="")
            except Exception as e:
                return dict(id=s.id, bank=s.bank, kind=s.kind, ok=False, tables=0, effective="", seconds=round(time.time() - t0, 1),
                            error=f"{type(e).__name__}: {str(e).splitlines()[0][:140]}")
            finally:
                sess.close()
        return self._pool(sources, make_ctx, work, lambda s, msg: dict(id=s.id, bank=s.bank, kind=s.kind, ok=False, tables=0, effective="", seconds=0, error=msg),
                          "Probing", browser)
