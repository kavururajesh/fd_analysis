"""FDService: the one façade used by the UI, the API and the CLI. Wires store + LLM + agents together."""
import threading
from typing import Callable, Optional

from src.agent.analyst import AnalystAgent, Answer, commentary
from src.agent.memory import ConversationMemory
from src.agent.state import Trace, TraceEvent
from src.agent.supervisor import RunContext, Supervisor
from src.config import settings as S
from src.config.logging_config import get_logger
from src.domain import analytics as A
from src.domain import reporting
from src.data.files import DatasetFiles, PromotionError
from src.data.publisher import Publisher
from src.llm.factory import get_llm, llm_status
from src.memory.store import Store
from src.tools.browser import BrowserManager
from src.tools.sources import load_sources
from src.utils.helpers import new_run_id

log = get_logger(__name__)
_refresh_lock = threading.Lock()


class FDService:
    def __init__(self, store: Store = None, llm=None, files: DatasetFiles = None):
        self.store = store or Store()
        self.llm = llm or get_llm()
        self.files = files or DatasetFiles()
        self.publisher = Publisher(self.store, self.files)
        self.memory = ConversationMemory()

    # ---------- info ----------
    @property
    def llm_label(self):
        return llm_status(self.llm)

    def sources(self):
        if S.SOURCE_MODE == "local":
            from src.localsite import fixture_server
            fixture_server.start()
        return load_sources()

    # ---------- refresh (data agents) ----------
    def refresh(self, callback: Optional[Callable[[TraceEvent], None]] = None, only: list = None) -> RunContext:
        if not _refresh_lock.acquire(blocking=False):
            raise RuntimeError("a refresh is already running")
        browser = BrowserManager()
        run_id = new_run_id()
        try:
            sources = self.sources()
            if only:
                sources = [s for s in sources if s.id in only]
            trace = Trace(run_id, self.store, callback)
            return Supervisor(self.llm, self.store, browser, trace, self.files).run(run_id, sources, S.SOURCE_MODE)
        finally:
            browser.close()
            _refresh_lock.release()

    def approve(self, run_id, by="reviewer"):
        run = self.store.get_run(run_id)
        if not run or run["status"] not in ("pending_review",):
            raise ValueError(f"run {run_id} cannot be approved (status: {run['status'] if run else 'not found'})")
        try:
            self.publisher.publish(run_id, by)
        except PromotionError as e:
            raise ValueError(str(e))

    def reject(self, run_id, by="reviewer"):
        run = self.store.get_run(run_id)
        if not run or run["status"] in ("published",):
            raise ValueError(f"run {run_id} cannot be rejected")
        self.store.set_status(run_id, "rejected", by)
        import shutil
        shutil.rmtree(self.files.staging_dir(run_id), ignore_errors=True)

    # ---------- analyst ----------
    def data(self, run_id=None):
        """(run_id, rates, previous rates). Default = the live dataset in data/current (always the latest successfully processed data)."""
        ids = self.store.published_ids()
        if run_id:
            df = self.store.load_rates(run_id)
            prev = self.store.load_rates(ids[1]) if len(ids) > 1 and run_id == ids[0] else (self.store.load_rates(ids[0]) if ids else None)
            return run_id, df, prev
        rid, df = self.files.load_current()
        if df is None:                                           # first start after a migration: fall back to the database copy
            rid, df = self.store.published(0)
        if df is None:
            return None, None, None
        prev = self.store.load_rates(ids[1]) if len(ids) > 1 and ids[0] == rid else None
        return rid, df, prev

    def ask(self, question: str, run_id=None, include_stale=False) -> Answer:
        _, df, prev = self.data(run_id)
        if df is None or df.empty:
            return Answer("No published data yet. Run a refresh and approve it first.", grounded=False, status="no_data")
        return AnalystAgent(self.llm, df, prev, self.memory, history=lambda: self.store.history()).ask(question, include_stale)

    def commentary(self, amount, run_id=None) -> Answer:
        _, df, _ = self.data(run_id)
        return commentary(self.llm, df, amount)

    def report_bytes(self, amount, run_id=None):
        rid, df, prev = self.data(run_id)
        return reporting.report_bytes(df, A.bundle(df, prev, amount), amount)
