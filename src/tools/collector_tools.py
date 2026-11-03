"""Tools the Collector agent may call. They never return invented data: every number comes from the page through a layout spec."""
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from src.domain.layout import LayoutError, LayoutSpec, apply_layout, preview, suggest_layout
from src.domain.schema import to_canonical
from src.domain.validation import validate_source
from src.tools.acquire import SourceSession
from src.tools.registry import ToolRegistry
from src.tools.sources import SourceConfig

MAX_TRIES = 6


@dataclass
class CollectorContext:
    source: SourceConfig
    session: SourceSession
    prev: Optional[pd.DataFrame] = None
    candidate: Optional[dict] = None          # {"spec", "df", "validation"}
    accepted: bool = False
    gave_up: Optional[str] = None
    tries: int = 0
    last_errors: list = field(default_factory=list)


def evaluate_layout(source, session, spec_dict, prev, effective=None):
    """Apply a spec to the loaded tables and validate. Returns (ok, df, validation, error_text)."""
    try:
        spec = LayoutSpec.from_dict(spec_dict)
        if spec.table_index >= len(session.tables) or spec.table_index < 0:
            raise LayoutError(f"table_index {spec.table_index} does not exist (page has {len(session.tables)} tables)")
        tidy = apply_layout(session.tables[spec.table_index], spec)
        df = to_canonical(tidy, source.meta(effective), effective)
        check = validate_source(df, source.expect, prev)
    except (LayoutError, ValueError, IndexError, KeyError) as e:
        return False, None, None, str(e)
    if check["errors"]:
        return False, df, check, "; ".join(check["errors"])
    return True, df, check, None


def build_collector_tools(ctx: CollectorContext) -> ToolRegistry:
    reg = ToolRegistry()

    def open_source():
        return ctx.session.summary()

    def click(selector):
        return ctx.session.click(str(selector))

    def list_tables():
        scored = []
        for i, t in enumerate(ctx.session.tables):
            s = suggest_layout(t)
            scored.append((s["_score"] if s else 0, i, t, s))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = []
        for score, i, t, s in scored[:5]:
            if score == 0 and top:
                break
            suggestion = None
            if s:
                suggestion = {k: v for k, v in s.items() if not k.startswith("_")}
                suggestion["table_index"] = i
            top.append(dict(index=i, shape=list(t.shape), score=score, suggested_spec=suggestion, preview=preview(t)))
        shown = {x["index"] for x in top}
        others = [dict(index=i, shape=list(t.shape), first_cell=str(t.iat[0, 0])[:30]) for _, i, t, _ in scored if i not in shown][:10]
        return dict(n_tables=len(ctx.session.tables), tables=top, other_tables=others,
                    hint="rows in 'preview' are [row_index, cell, cell, ...]")

    def show_table(index, start_row=0, rows=12):
        i, a, n = int(index), int(start_row), min(int(rows), 25)
        if i >= len(ctx.session.tables):
            raise ValueError(f"no table {i} (page has {len(ctx.session.tables)})")
        return dict(index=i, shape=list(ctx.session.tables[i].shape), rows=preview(ctx.session.tables[i].iloc[a:a + n], max_rows=n, max_cols=10))

    def suggest(table_index):
        i = int(table_index)
        s = suggest_layout(ctx.session.tables[i])
        if not s:
            return dict(suggested_spec=None, note="the heuristic found no tenor/amount structure in this table")
        spec = {k: v for k, v in s.items() if not k.startswith("_")}
        spec["table_index"] = i
        return dict(suggested_spec=spec)

    def try_layout(spec):
        ctx.tries += 1
        if ctx.tries > MAX_TRIES:
            return dict(ok=False, errors=["too many tries - call give_up(reason)"])
        if isinstance(spec, str):
            from src.agent.planner import extract_json
            spec = extract_json(spec) or {}
        effective = ctx.session.effective_detected or ctx.source.effective
        ok, df, check, error = evaluate_layout(ctx.source, ctx.session, spec, ctx.prev, effective)
        if not ok:
            ctx.last_errors = [error]
            return dict(ok=False, errors=[error], hint="fix the spec (table_index / orientation / label_col / value_cols / header_row) and retry")
        ctx.candidate = dict(spec=LayoutSpec.from_dict(spec).to_dict(), df=df, validation=check)
        sample = df.head(3)[["tenor_label", "amt_label", "rate"]].to_dict("records")
        return dict(ok=True, metrics=check["metrics"], warnings=check["warnings"], sample=sample, next="call accept_candidate")

    def accept_candidate():
        if ctx.candidate is None:
            raise ValueError("no valid candidate yet - call try_layout until it returns ok=true")
        ctx.accepted = True
        return "accepted"

    def give_up(reason):
        ctx.gave_up = str(reason)
        return "ok"

    reg.register("open_source", "page summary: title, number of tables, detected effective date", open_source, {})
    reg.register("click", "click a tab/button on a browser page (CSS or text= selector) and reload the table list", click,
                 {"selector": "string, e.g. text=Show rates"})
    reg.register("list_tables", "tables on the page ranked by score, with preview rows and a suggested spec", list_tables, {})
    reg.register("show_table", "more rows of one table", show_table,
                 {"index": "table index", "start_row": "first row (default 0)", "rows": "how many rows (max 25)"}, required=["index"])
    reg.register("suggest_layout", "heuristic layout spec for one table", suggest, {"table_index": "table index"})
    reg.register("try_layout", "apply a layout spec, validate the result and keep it as candidate", try_layout, {"spec": "layout spec object"})
    reg.register("accept_candidate", "accept the last valid candidate and finish", accept_candidate, {})
    reg.register("give_up", "stop if no table can be read", give_up, {"reason": "string"})
    return reg
