"""Collector agent: reads ONE source.
Fast path  : known layout (approved memory spec, else the YAML layout) -> validate. No LLM, no cost.
Self-heal  : if that fails (page changed / no layout yet) the ReAct agent inspects the page, proposes a layout spec,
             the code validates it. Healed specs are saved UNAPPROVED - a human approves them with the run."""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.agent.executor import ReActExecutor
from src.agent.state import Trace
from src.config import settings as S
from src.domain.layout import suggest_layout
from src.memory.store import Store
from src.tools.acquire import SourceSession
from src.tools.collector_tools import CollectorContext, build_collector_tools, evaluate_layout
from src.tools.sources import SourceConfig


@dataclass
class CollectResult:
    source_id: str
    ok: bool
    method: str                                  # spec_memory | spec_yaml | agent_healed | heuristic_healed | failed
    df: Optional[pd.DataFrame] = None
    spec: Optional[dict] = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    effective: str = ""
    healed: bool = False

    def detail(self):
        return dict(errors=self.errors, warnings=self.warnings, metrics=self.metrics, evidence=self.evidence,
                    effective=self.effective, spec=self.spec, healed=self.healed)


class CollectorAgent:
    def __init__(self, llm, store: Store, browser, trace: Trace, evidence_dir=None):
        self.llm, self.store, self.browser, self.trace, self.evidence_dir = llm, store, browser, trace, evidence_dir

    def collect(self, source: SourceConfig, run_id: str, prev: Optional[pd.DataFrame] = None) -> CollectResult:
        say = lambda kind, text: self.trace.emit(f"collector:{source.id}", kind, text)
        session = SourceSession(source, self.browser, self.evidence_dir)
        try:
            say("info", f"Opening {source.url} ({source.kind})")
            info = session.open()
            say("observation", f"{info['n_tables']} table(s) found; effective date on page: {info['effective_detected'] or 'not found'}")
            evidence = session.save_evidence(run_id)
            effective = session.effective_detected or source.effective
            prev_src = prev[prev.source_id == source.id] if prev is not None and len(prev) else None

            # ---- fast path ----
            known = [("spec_memory", self.store.get_spec(source.id)), ("spec_yaml", source.layout)]
            reason = "no known layout - calibrating"
            for method, spec in known:
                if not spec:
                    continue
                ok, df, check, err = evaluate_layout(source, session, spec, prev_src, effective)
                if ok:
                    say("info", f"Known layout ({method}) worked: {len(df)} rates")
                    return self._result(source, True, method, df, spec, check, evidence, effective)
                reason = f"known layout ({method}) failed: {err}"
                say("warning", reason)

            # ---- self-heal ----
            say("info", "Starting self-healing agent: " + reason)
            ctx = CollectorContext(source, session, prev_src)
            res = ReActExecutor(self.llm, build_collector_tools(ctx), "collector", f"collector:{source.id}", self.trace,
                                S.COLLECTOR_MAX_STEPS).run(self._goal(source, reason, prev_src, info), stop_when=lambda: ctx.accepted or bool(ctx.gave_up))
            method = "agent_healed"
            if not ctx.accepted:
                # LLM unavailable or failed: deterministic heuristic as a safety net (still validated, still needs approval)
                say("warning", f"Agent did not finish ({res.status}); trying the deterministic heuristic")
                method = "heuristic_healed"
                for i, t in enumerate(session.tables):
                    s = suggest_layout(t)
                    if not s:
                        continue
                    spec = {k: v for k, v in s.items() if not k.startswith("_")}
                    spec["table_index"] = i
                    ok, df, check, err = evaluate_layout(source, session, spec, prev_src, effective)
                    if ok:
                        ctx.candidate, ctx.accepted = dict(spec=spec, df=df, validation=check), True
                        break
            if not ctx.accepted:
                msg = ctx.gave_up or (ctx.last_errors[0] if ctx.last_errors else f"agent finished with status {res.status}")
                say("error", "Could not read this source: " + msg)
                return CollectResult(source.id, False, "failed", errors=[msg], evidence=evidence, effective=effective)
            c = ctx.candidate
            self.store.save_spec(source.id, c["spec"], origin=method, run_id=run_id, approved=False)
            say("info", f"Healed ({method}): {len(c['df'])} rates; layout saved for approval")
            return self._result(source, True, method, c["df"], c["spec"], c["validation"], evidence, effective, healed=True)
        except Exception as e:
            say("error", f"{type(e).__name__}: {e}")
            return CollectResult(source.id, False, "failed", errors=[f"{type(e).__name__}: {e}"])
        finally:
            session.close()

    @staticmethod
    def _result(source, ok, method, df, spec, check, evidence, effective, healed=False):
        return CollectResult(source.id, ok, method, df, spec, check["errors"], check["warnings"], check["metrics"], evidence, effective, healed)

    @staticmethod
    def _goal(source, reason, prev_src, info):
        ref = "no previous data for this source"
        if prev_src is not None and len(prev_src):
            ref = (f"previously {len(prev_src)} rates, amount slabs {sorted(prev_src.amt_label.unique())[:6]}, "
                   f"tenors {sorted(prev_src.tenor_label.unique())[:4]}..., rates {prev_src.rate.min():g}-{prev_src.rate.max():g}%")
        return (f"Source: {source.bank} {source.product} ({source.id}), {source.kind} page, {info['n_tables']} tables on the page.\n"
                f"Problem: {reason}\nReference: {ref}\nExpected: {source.expect or 'corporate FD rates by tenor and amount slab'}\n"
                f"Find the right table and describe its layout.")
