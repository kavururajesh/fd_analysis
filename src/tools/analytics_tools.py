"""Tools the Analyst agent may call. Thin wrappers over domain.analytics - the LLM never calculates, it only reads these results."""
import pandas as pd

from src.config import settings as S
from src.domain import analytics as A
from src.domain import charts as C
from src.domain.parsing import fmt_day, parse_days_arg
from src.domain.validation import diff_runs
from src.tools.registry import ToolRegistry


def _amount(x):
    v = float(str(x).lower().replace("cr", "").replace("₹", "").strip())
    if v <= 0:
        raise ValueError("amount must be > 0 (Rs crore)")
    return v


def _day(x):
    return int(parse_days_arg(str(x))) if not isinstance(x, (int, float)) else int(x)


def build_analytics_tools(df: pd.DataFrame, prev: pd.DataFrame = None, include_stale: bool = False, sink: list = None, history=None) -> ToolRegistry:
    statuses = S.STATUSES if include_stale else S.DEFAULT_STATUSES
    reg = ToolRegistry()

    def get_rates(amount_cr, days):
        amount, day = _amount(amount_cr), _day(days)
        r = A.rates_at(df, amount, day, statuses)
        if r.empty:
            return dict(note=f"no rates cover Rs {amount:g} Cr at {fmt_day(day)}")
        return dict(amount_cr=amount, tenor=fmt_day(day), days=day,
                    ranking=[dict(rank=int(x.rank), bank=x.name, rate_pct=x.rate, vs_sber_pp=x.vs_sber_pp, status=x.status) for x in r.itertuples()])

    def get_findings(amount_cr):
        return dict(amount_cr=_amount(amount_cr), findings=A.key_findings(df, _amount(amount_cr), statuses))

    def compare_tenors(amount_cr):
        amount = _amount(amount_cr)
        c = A.comparison(df, [amount], S.TENOR_GRID, statuses).dropna(subset=["gap"]).sort_values("day")
        return dict(amount_cr=amount, rows=[dict(tenor=fmt_day(r.day), sber_pct=r.sber, best_peer=r.best_peer, peer_pct=r.best_rate, sber_minus_peer_pp=r.gap)
                                            for r in c.itertuples()])

    def size_sensitivity(days):
        day = _day(days)
        c = A.comparison(df, S.AMOUNT_GRID, [day], statuses).dropna(subset=["sber"])
        return dict(tenor=fmt_day(day), rows=[dict(amount_cr=r.amount, sber_pct=r.sber, best_peer=r.best_peer, peer_pct=r.best_rate, sber_minus_peer_pp=r.gap)
                                              for r in c.itertuples()])

    def scorecard():
        return dict(sber_win_share_pct=A.scorecard(df, statuses).to_dict("index"))

    def data_quality():
        s = A.source_status(df)
        return dict(sources=s.to_dict("records"), non_current=sorted({A._label(a, b) for a, b in zip(df.series, df.status) if b != "current"}))

    def recent_changes():
        d = diff_runs(df, prev)
        if d.empty:
            return dict(note="no changes versus the previous published data (or no previous data)")
        return dict(n_changes=len(d), top=d.head(10).to_dict("records"))


    SUBJECTS = ("rate_curve", "bank_ranking", "deposit_size", "lead_share", "heatmap", "history")

    def plot(subject, amount_cr=5, days=90):
        if subject not in SUBJECTS:
            raise ValueError(f"subject must be one of {list(SUBJECTS)}")
        a, d = _amount(amount_cr), _day(days)
        build = {"rate_curve": lambda: C.rate_curve(df, a, statuses), "bank_ranking": lambda: C.bank_ranking(df, a, d, statuses),
                 "deposit_size": lambda: C.deposit_size(df, d, statuses), "lead_share": lambda: C.lead_share(df, a, statuses),
                 "heatmap": lambda: C.gap_heatmap(df, statuses),
                 "history": lambda: C.history(history() if history else [], a, d, statuses)}
        spec = build[subject]()
        if not spec["series"] or not spec["x"]:
            return dict(note="no data available for this chart")
        if sink is not None:
            sink.append(spec)
        return dict(chart_created=spec["title"], facts=spec["facts"])

    reg.register("plot", "draw a chart that is shown next to the answer; use it for comparison, trend or analytical questions only, never for a simple lookup. "
                 "subjects: rate_curve (Sber vs peers across tenors), bank_ranking (all banks at one amount and tenor), deposit_size (rate by deposit size at one tenor), "
                 "lead_share (pie of where Sber leads or trails), heatmap (gap grid), history (rate over time)", plot,
                 {"subject": "one of the subjects above", "amount_cr": "Rs crore (default 5)", "days": "tenor (default 90)"}, required=["subject"])

    reg.register("get_rates", "all banks' rates for one deposit amount and tenor, best first, with gap vs Sberbank", get_rates,
                 {"amount_cr": "Rs crore, e.g. 5", "days": "tenor, e.g. 90, '1y', '6m'"})
    reg.register("get_findings", "key findings for one deposit amount (where Sber leads / trails)", get_findings, {"amount_cr": "Rs crore"})
    reg.register("compare_tenors", "Sberbank vs best peer at every tenor for one amount", compare_tenors, {"amount_cr": "Rs crore"})
    reg.register("size_sensitivity", "Sberbank vs best peer at every deposit size for one tenor", size_sensitivity, {"days": "tenor"})
    reg.register("scorecard", "share of points where Sberbank is highest, by deposit size and tenor group", scorecard, {})
    reg.register("data_quality", "which sources are current / stale / proxy and their effective dates", data_quality, {})
    reg.register("recent_changes", "rate changes versus the previous published data", recent_changes, {})
    return reg
