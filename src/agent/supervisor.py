"""Supervisor agent: runs the whole refresh. It orders the work (list -> collect each source -> finalize -> brief),
but the publish decision is made by code policy, and publishing always needs a human."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from src.agent.collector import CollectorAgent, CollectResult
from src.agent.executor import ReActExecutor
from src.agent.guardrails import unverified_numbers
from src.agent.state import Trace
from src.config import settings as S
from src.data.files import DatasetFiles, PromotionError
from src.data.publisher import Publisher
from src.domain.schema import COLUMNS
from src.domain.validation import diff_runs, validate_dataset
from src.memory.store import Store
from src.prompts.system_prompts import get_system_prompt
from src.tools.registry import ToolRegistry
from src.tools.sources import SourceConfig
from src.utils.helpers import dumps


@dataclass
class RunContext:
    run_id: str
    sources: List[SourceConfig]
    prev: Optional[pd.DataFrame]
    prev_id: Optional[str]
    results: Dict[str, CollectResult] = field(default_factory=dict)
    df: Optional[pd.DataFrame] = None
    status: str = "running"
    reasons: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    brief: str = ""
    finished: bool = False
    carried: List[str] = field(default_factory=list)


class Supervisor:
    def __init__(self, llm, store: Store, browser, trace: Trace, files: DatasetFiles = None):
        self.llm, self.store, self.browser, self.trace = llm, store, browser, trace
        self.files = files or DatasetFiles()
        self.publisher = Publisher(store, self.files)
        self.collector = CollectorAgent(llm, store, browser, trace, self.files.staging)

    # ---------------- tools ----------------
    def _tools(self, ctx: RunContext) -> ToolRegistry:
        reg = ToolRegistry()
        by_id = {s.id: s for s in ctx.sources}

        def list_sources():
            return [dict(id=s.id, bank=s.bank, product=s.product, status=s.status, kind=s.kind, done=s.id in ctx.results) for s in ctx.sources]

        def collect_source(source_id):
            if source_id not in by_id:
                raise ValueError(f"unknown source id '{source_id}'. Valid: {list(by_id)}")
            if source_id in ctx.results:
                return f"{source_id} was already collected ({'ok' if ctx.results[source_id].ok else 'failed'})"
            r = self.collector.collect(by_id[source_id], ctx.run_id, ctx.prev)
            ctx.results[source_id] = r
            return dict(source_id=source_id, ok=r.ok, method=r.method, rows=0 if r.df is None else len(r.df),
                        errors=r.errors[:2], warnings=r.warnings[:3])

        def finalize_run():
            self._finalize(ctx)
            return dict(status=ctx.status, reasons=ctx.reasons, errors=ctx.errors[:4], rows=0 if ctx.df is None else len(ctx.df))

        def write_review_brief():
            if ctx.df is None:
                raise ValueError("call finalize_run first")
            self._write_brief(ctx)
            return "brief written"

        def finish(summary=""):
            ctx.finished = True
            return "done"

        reg.register("list_sources", "list all sources with their ids and whether they are collected", list_sources, {})
        reg.register("collect_source", "read one source (opens the page, extracts, validates, self-heals if needed)", collect_source, {"source_id": "id from list_sources"})
        reg.register("finalize_run", "combine, validate and stage the collected data (decides review status)", finalize_run, {})
        reg.register("write_review_brief", "write the review brief for the human approver", write_review_brief, {})
        reg.register("finish", "end the run", finish, {"summary": "2-3 line summary"}, required=[])
        return reg

    # ---------------- run ----------------
    def run(self, run_id: str, sources: List[SourceConfig], mode: str) -> RunContext:
        prev_id, prev = self.store.published(0)
        ctx = RunContext(run_id, sources, prev, prev_id)
        self.trace.emit("supervisor", "info", f"Run {run_id}: {len(sources)} sources; previous published run: {prev_id or 'none'}")
        reg = self._tools(ctx)
        goal = f"Refresh the FD rate benchmark. Source ids: {[s.id for s in sources]}. Follow the procedure."
        res = ReActExecutor(self.llm, reg, "supervisor", "supervisor", self.trace, S.SUPERVISOR_MAX_STEPS).run(goal, stop_when=lambda: ctx.finished)
        # Safety net: whatever the LLM skipped, the standard procedure completes - a flaky model cannot leave a run half-done.
        if res.status not in ("final", "done") or len(ctx.results) < len(sources) or ctx.df is None:
            self.trace.emit("supervisor", "warning", f"Supervisor LLM ended with '{res.status}'; completing the standard procedure in code")
        for s in sources:
            if s.id not in ctx.results:
                reg.call("collect_source", {"source_id": s.id})
        if ctx.df is None:
            self._finalize(ctx)
        if not ctx.brief:
            self._write_brief(ctx)
        self._save(ctx, mode)
        self.trace.emit("supervisor", "final", f"Run {run_id} staged as '{ctx.status}'. " + ("; ".join(ctx.reasons) if ctx.reasons else "No issues."))
        return ctx

    # ---------------- finalize / policy ----------------
    def _finalize(self, ctx: RunContext):
        frames, ctx.carried = [], []
        for s in ctx.sources:
            r = ctx.results.get(s.id)
            if r and r.ok and r.df is not None:
                frames.append(r.df)
            elif ctx.prev is not None and len(ctx.prev):
                old = ctx.prev[ctx.prev.source_id == s.id].copy()
                if len(old):
                    old["status"] = "stale"
                    frames.append(old[COLUMNS])
                    ctx.carried.append(s.id)
        ctx.df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
        errors, warnings = validate_dataset(ctx.df, ctx.prev)
        reasons = []
        for s in ctx.sources:
            r = ctx.results.get(s.id)
            if r is None or not r.ok:
                own = f"{s.bank} {s.product}" == S.SBER                       # our own rates must be fresh: never carry them forward silently
                (errors if own else warnings).append(                   # one unreadable peer must not stop the whole refresh
                    
                    f"{s.bank} {s.product}: could not be read" + (" - previous published rates carried forward and marked stale" if s.id in ctx.carried else "") +
                    (f" ({r.errors[0]})" if r and r.errors else ""))
                continue
            warnings += [f"{s.id}: {w}" for w in r.warnings]
            if r.healed:
                first = s.layout is None and self.store.get_spec(s.id) is None
                reasons.append(f"{s.bank} {s.product}: " + ("layout calibrated by the agent for the first time" if first else "layout changed - agent healed it") + " (check evidence)")
            moved = r.metrics.get("max_move_pp")
            if moved and moved > S.MAX_RATE_MOVE_PP:
                reasons.append(f"{s.bank} {s.product}: a rate moved by {moved:g} pp (limit {S.MAX_RATE_MOVE_PP:g})")
            det, conf = r.evidence.get("effective_detected"), s.effective
            if det and conf and det != conf:
                reasons.append(f"{s.bank} {s.product}: effective date on page is {det}, configured {conf}")
        if ctx.carried:
            reasons.append("carried-forward (stale) sources: " + ", ".join(ctx.carried))
        if ctx.prev is None:
            reasons.append("first run - no published baseline to compare with")
        ctx.errors, ctx.warnings = errors, warnings
        if errors:
            ctx.status = "blocked"
            ctx.reasons = errors + reasons
        elif reasons or not S.AUTO_PUBLISH_CLEAN:
            ctx.status = "pending_review"
            ctx.reasons = reasons or ["every run needs human approval (auto-publish is off)"]
        else:
            ctx.status = "published"
            ctx.reasons = []

    # ---------------- brief ----------------
    def _write_brief(self, ctx: RunContext):
        changes = diff_runs(ctx.df, ctx.prev)
        data = dict(status=ctx.status, reasons=ctx.reasons, errors=ctx.errors[:6], warnings=ctx.warnings[:8],
                    sources=[dict(id=s.id, ok=ctx.results[s.id].ok, method=ctx.results[s.id].method, rows=0 if ctx.results[s.id].df is None else len(ctx.results[s.id].df))
                             for s in ctx.sources if s.id in ctx.results],
                    n_rate_changes=int(len(changes)), biggest_changes=changes.head(5)[["series", "amt_label", "tenor_label", "old", "new", "change_pp"]].to_dict("records"))
        blob = dumps(data)
        text = ""
        try:
            text = self.llm.chat([{"role": "system", "content": get_system_prompt("brief")}, {"role": "user", "content": "DATA:\n" + blob}],
                                 task="brief", temperature=0.1).strip()
            bad = unverified_numbers(text, [blob])
            if bad:
                self.trace.emit("supervisor", "warning", f"Brief contained unverified figures {bad}; using the deterministic brief")
                text = ""
        except Exception as e:
            self.trace.emit("supervisor", "warning", f"Brief by LLM failed ({e}); using the deterministic brief")
        ctx.brief = text or self._plain_brief(data)

    @staticmethod
    def _plain_brief(d):
        lines = [f"- Status: {d['status']}."]
        lines += [f"- {r}" for r in d["reasons"][:5]]
        lines += [f"- Warning: {w}" for w in d["warnings"][:4]]
        lines.append(f"- {d['n_rate_changes']} rate cell(s) differ from the last published data.")
        lines.append("- All checks passed; the live dataset was replaced automatically." if d["status"] == "published" else
                     "- Check the evidence (screenshot / file) of any healed or flagged source, then approve or reject.")
        return "\n".join(lines)

    def _save(self, ctx: RunContext, mode: str):
        results = [dict(source_id=s.id, ok=ctx.results[s.id].ok, method=ctx.results[s.id].method, detail=ctx.results[s.id].detail())
                   for s in ctx.sources if s.id in ctx.results]
        qa = dict(errors=ctx.errors, warnings=ctx.warnings, carried=ctx.carried, prev_run=ctx.prev_id)
        wanted = ctx.status
        self.store.save_run(ctx.run_id, "pending_review" if wanted == "published" else wanted, mode, ctx.df, results, ctx.reasons, qa, ctx.brief)
        if wanted == "blocked":                                      # nothing is staged; evidence stays for diagnosis until the next good run
            return
        meta = dict(mode=mode, sources=[dict(id=s.id, ok=ctx.results[s.id].ok, method=ctx.results[s.id].method) for s in ctx.sources if s.id in ctx.results])
        self.publisher.stage(ctx.run_id, ctx.df, meta)
        if wanted == "published":                                    # clean + validated: replace the live dataset automatically
            try:
                self.publisher.publish(ctx.run_id, "auto")
            except PromotionError as e:
                ctx.status = "pending_review"
                ctx.reasons = [f"automatic replacement failed, previous data kept: {e}"]
                self.trace.emit("supervisor", "error", ctx.reasons[0])
