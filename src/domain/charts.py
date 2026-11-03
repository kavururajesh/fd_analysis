"""Chart specifications built from the rates table. Pure data (no plotting library): the UI renders them, the chatbot returns them.
Every number in a spec comes from domain.analytics, so a chart can never show something that is not in the data."""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import settings as S
from src.domain import analytics as A
from src.domain.parsing import fmt_day
from src.utils.helpers import clean

SIZE_POINTS = [0.5, 1, 2, 3, 5, 7.5, 10, 15, 20, 25, 35, 50, 75, 100, 150, 200]


def _spec(kind, title, x, series, x_title="", y_title="", facts=None, subtitle="", unit="%"):
    return clean(dict(kind=kind, title=title, subtitle=subtitle, x=list(x), series=series, x_title=x_title, y_title=y_title,
                      unit=unit, highlight=S.SBER, facts=facts or []))


def rate_curve(df, amount, statuses=S.DEFAULT_STATUSES, banks: Optional[List[str]] = None) -> Dict:
    c = A.curve(df, amount, statuses).dropna(how="all")
    cols = [n for n in c.columns if banks is None or n in banks]
    series = [dict(name=n, values=[None if pd.isna(v) else float(v) for v in c[n]]) for n in ([S.SBER] if S.SBER in cols else []) + [n for n in cols if n != S.SBER]]
    return _spec("line", f"Rate by tenor at ₹{amount:g} Cr", [fmt_day(d) for d in c.index], series, "Tenor", "Interest rate (% p.a.)",
                 _curve_facts(df, amount, statuses))


def _curve_facts(df, amount, statuses):
    c = A.comparison(df, [amount], S.TENOR_GRID, statuses).dropna(subset=["gap"]).sort_values("day")
    if c.empty:
        return []
    lead, facts = c[c.gap >= 0], []
    facts.append(f"At ₹{amount:g} Cr, Sberbank pays the highest or joint-highest rate at {len(lead)} of {len(c)} tenor points.")
    lose = c[c.gap < 0]
    if len(lose):
        f, w = lose.iloc[0], c.loc[c.gap.idxmin()]
        facts.append(f"It is first overtaken at {fmt_day(f.day)}, where {f.best_peer} pays {f.best_rate:g}% against {f.sber:g}%.")
        facts.append(f"The widest shortfall is {abs(w.gap):g} pp at {fmt_day(w.day)} against {w.best_peer}.")
    return facts


def bank_ranking(df, amount, day, statuses=S.DEFAULT_STATUSES) -> Dict:
    r = A.rates_at(df, amount, day, statuses)
    facts = []
    if len(r):
        top = r.iloc[0]
        facts.append(f"At ₹{amount:g} Cr for {fmt_day(day)}, {top['name']} pays the highest rate: {top['rate']:g}%.")
        s = r[r.name == S.SBER]
        if len(s):
            facts.append(f"Sberbank pays {s.rate.iloc[0]:g}% and ranks {int(s['rank'].iloc[0])} of {len(r)}.")
    return _spec("bar", f"Banks compared: ₹{amount:g} Cr, {fmt_day(day)}", list(r["name"]), [dict(name="Rate (% p.a.)", values=list(r["rate"]))],
                 "", "Interest rate (% p.a.)", facts)


def deposit_size(df, day, statuses=S.DEFAULT_STATUSES) -> Dict:
    c = A.comparison(df, SIZE_POINTS, [day], statuses).dropna(subset=["sber"])
    facts = []
    if len(c) > 1:
        lo, hi = c.loc[c.sber.idxmin()], c.loc[c.sber.idxmax()]
        facts.append(f"At {fmt_day(day)}, Sberbank pays {lo.sber:g}% for ₹{lo.amount:g} Cr and {hi.sber:g}% for ₹{hi.amount:g} Cr.")
        beh = c[c.gap < 0]
        facts.append(f"A peer pays more at {len(beh)} of {len(c)} deposit sizes." if len(beh) else "Sberbank is highest or joint-highest at every deposit size shown.")
    return _spec("bar_line", f"Rate by deposit size at {fmt_day(day)}", [f"₹{a:g} Cr" for a in c.amount],
                 [dict(name=S.SBER, values=list(c.sber), type="bar"), dict(name="Best peer", values=list(c.best_rate), type="line", labels=list(c.best_peer))],
                 "Deposit size", "Interest rate (% p.a.)", facts)


def lead_share(df, amount, statuses=S.DEFAULT_STATUSES) -> Dict:
    c = A.comparison(df, [amount], S.TENOR_GRID, statuses).dropna(subset=["gap"])
    lead, tie, trail = int((c.gap > 0).sum()), int((c.gap == 0).sum()), int((c.gap < 0).sum())
    facts = [f"At ₹{amount:g} Cr, Sberbank pays more than every peer at {lead} of {len(c)} tenor points, ties at {tie} and trails at {trail}."]
    return _spec("pie", f"Where Sberbank stands at ₹{amount:g} Cr", ["Sberbank highest", "Joint highest", "Peer higher"], [dict(name="Tenor points", values=[lead, tie, trail])],
                 facts=facts, unit="")


def gap_heatmap(df, statuses=S.DEFAULT_STATUSES) -> Dict:
    c = A.comparison(df, S.AMOUNT_GRID, S.TENOR_GRID, statuses)
    g = c.pivot(index="amount", columns="day", values="gap")
    share = float((c.gap.dropna() >= 0).mean() * 100) if c.gap.notna().any() else 0.0
    return _spec("heatmap", "Sberbank minus best peer (pp)", [fmt_day(d) for d in g.columns],
                 [dict(name=f"₹{a:g} Cr", values=[None if pd.isna(v) else float(v) for v in row]) for a, row in zip(g.index, g.values)],
                 "Tenor", "Deposit size", [f"Sberbank is highest or joint-highest in {share:.0f}% of the amount × tenor points."], unit="pp")


def history(store_history, amount, day, statuses=S.DEFAULT_STATUSES) -> Dict:
    """Sberbank vs best peer across published refreshes."""
    xs, sber, peer = [], [], []
    for rid, created, d in store_history:
        r = A.rates_at(d, amount, day, statuses)
        s, p = r[r.name == S.SBER], r[r.name != S.SBER]
        if len(s):
            xs.append((created or rid)[:10]); sber.append(float(s.rate.iloc[0])); peer.append(float(p.rate.max()) if len(p) else None)
    facts = []
    if len(xs) >= 2:
        facts.append(f"Sberbank's rate at ₹{amount:g} Cr for {fmt_day(day)} went from {sber[0]:g}% to {sber[-1]:g}% across {len(xs)} updates.")
    elif xs:
        facts.append(f"Only one update is stored so far: Sberbank {sber[0]:g}%. Trends appear as more refreshes are published.")
    return _spec("line", f"Rate history: ₹{amount:g} Cr, {fmt_day(day)}", xs, [dict(name=S.SBER, values=sber), dict(name="Best peer", values=peer)],
                 "Update date", "Interest rate (% p.a.)", facts)
