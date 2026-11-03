"""All comparison maths. Pure functions on the rates table - no UI, no AI. Every number shown anywhere comes from here."""
import numpy as np
import pandas as pd

from src.utils.helpers import clean

from src.config.settings import AMOUNT_GRID, DEFAULT_STATUSES, SBER, TENOR_GRID
from src.domain.parsing import fmt_day


# ---------- helpers ----------
def _days(days):
    return ", ".join(fmt_day(d) for d in days)


def _label(series, status):
    return series if status == "current" else f"{series} ({status})"


# ---------- core lookups ----------
def rates_at(df, amount, day, statuses=DEFAULT_STATUSES):
    """Every bank's rate for one deposit amount (Rs cr) and tenor (days), best first."""
    d = df[df["status"].isin(statuses)]
    m = d[(d.amt_lo <= amount) & (amount < d.amt_hi) & (d.d_lo <= day) & (day <= d.d_hi)].copy()
    cols = ["rank", "name", "rate", "vs_sber_pp", "status", "effective", "amt_label", "tenor_label"]
    if m.empty:
        return pd.DataFrame(columns=cols)
    m["name"] = [_label(s, t) for s, t in zip(m.series, m.status)]
    m = m.sort_values("rate", ascending=False).drop_duplicates("name").reset_index(drop=True)
    m["rank"] = m["rate"].rank(method="min", ascending=False).astype(int)
    sber = m.loc[m.series == SBER, "rate"]
    m["vs_sber_pp"] = (m["rate"] - sber.iloc[0]).round(2) if len(sber) else np.nan
    return m[cols]


def grid_long(df, amounts, days, statuses=DEFAULT_STATUSES):
    """One row per (amount, tenor, bank): the rate that applies."""
    d = df[df["status"].isin(statuses)]
    names = np.array([_label(s, t) for s, t in zip(d.series, d.status)])
    series, lo, hi, a, b, r = d.series.values, d.amt_lo.values, d.amt_hi.values, d.d_lo.values, d.d_hi.values, d.rate.values
    parts = []
    for amt in amounts:
        for day in days:
            m = (lo <= amt) & (amt < hi) & (a <= day) & (day <= b)
            if m.any():
                parts.append(pd.DataFrame({"amount": amt, "day": day, "name": names[m], "series": series[m], "rate": r[m]}))
    if not parts:
        return pd.DataFrame(columns=["amount", "day", "name", "series", "rate"])
    return pd.concat(parts).groupby(["amount", "day", "name", "series"], as_index=False)["rate"].max()


def comparison(df, amounts=AMOUNT_GRID, days=TENOR_GRID, statuses=DEFAULT_STATUSES):
    """Per (amount, tenor): Sber rate, best peer, best peer rate, gap = Sber - best peer (pp)."""
    g = grid_long(df, amounts, days, statuses)
    cols = ["amount", "day", "sber", "best_peer", "best_rate", "gap"]
    if g.empty:
        return pd.DataFrame(columns=cols)
    sber = g[g.series == SBER].set_index(["amount", "day"])["rate"].rename("sber")
    peers = g[g.series != SBER]
    best = peers.loc[peers.groupby(["amount", "day"])["rate"].idxmax()].set_index(["amount", "day"])[["name", "rate"]]
    best.columns = ["best_peer", "best_rate"]
    c = pd.concat([sber, best], axis=1).reset_index()
    c["gap"] = (c["sber"] - c["best_rate"]).round(2)
    return c[cols]


def curve(df, amount, statuses=DEFAULT_STATUSES, days=TENOR_GRID):
    g = grid_long(df, [amount], days, statuses)
    return g.pivot(index="day", columns="name", values="rate").reindex(days)


# ---------- insights ----------
def scorecard(df, statuses=DEFAULT_STATUSES):
    """% of (amount, tenor) points where Sber is the highest or tied-highest, by deposit size and tenor group."""
    c = comparison(df, AMOUNT_GRID, TENOR_GRID, statuses).dropna(subset=["gap"]).copy()
    c["Tenor"] = pd.cut(c["day"], [0, 91, 366, 10 ** 6], right=False, labels=["Short (≤90d)", "Medium (91d–1y)", "Long (>1y)"])
    c["Deposit size"] = pd.cut(c["amount"], [0, 3, 10, 25, 10 ** 6], right=False, labels=["Under ₹3Cr", "₹3Cr to <10Cr", "₹10Cr to <25Cr", "₹25Cr and above"])
    c["win"] = (c["gap"] >= 0) * 100.0
    return c.pivot_table(index="Deposit size", columns="Tenor", values="win", aggfunc="mean", observed=False).round(0)


def key_findings(df, amount, statuses=DEFAULT_STATUSES):
    c = comparison(df, [amount], TENOR_GRID, statuses).dropna(subset=["gap"]).sort_values("day")
    if c.empty:
        return ["No comparable Sber and peer rates for this amount."]
    out, win = [], c[c.gap >= 0]
    if len(win):
        out.append(f"At ₹{amount:g}Cr, Sberbank pays the highest (or joint-highest) rate at {len(win)} of {len(c)} tenor points: {_days(win.day)}.")
    else:
        out.append(f"At ₹{amount:g}Cr, Sberbank is not the highest at any of the {len(c)} tenor points checked.")
    lose = c[c.gap < 0]
    if len(lose):
        f = lose.iloc[0]
        out.append(f"Sberbank is first overtaken at {fmt_day(f.day)}: {f.best_peer} pays {f.best_rate:g}% vs Sberbank {f.sber:g}%.")
        w = c.loc[c.gap.idxmin()]
        out.append(f"Widest shortfall: {abs(w.gap):g} pp at {fmt_day(w.day)} against {w.best_peer} ({w.best_rate:g}%).")
    if len(win):
        b = c.loc[c.gap.idxmax()]
        out.append(f"Biggest lead: {b.gap:g} pp at {fmt_day(b.day)} over {b.best_peer} ({b.best_rate:g}%).")
    s = c.set_index("day")["sber"].dropna()
    drop = s.diff()
    if len(drop) > 1 and drop.min() <= -0.5:
        d2 = drop.idxmin()
        d1 = s.index[s.index.get_loc(d2) - 1]
        out.append(f"Sberbank's own curve drops {abs(drop.min()):g} pp between {fmt_day(d1)} and {fmt_day(d2)} ({s[d1]:g}% to {s[d2]:g}%).")
    sz = comparison(df, AMOUNT_GRID, [60], statuses).dropna(subset=["sber"])
    if len(sz) > 1:
        lo, hi = sz.loc[sz.sber.idxmin()], sz.loc[sz.sber.idxmax()]
        out.append(f"Deposit size matters: at 60 days Sberbank pays {lo.sber:g}% for ₹{lo.amount:g}Cr but {hi.sber:g}% for ₹{hi.amount:g}Cr ({hi.sber - lo.sber:.2f} pp spread).")
    d = df[df.status.isin(statuses) & (df.status != "current")].drop_duplicates(["series", "status"])
    if len(d):
        out.append("Comparison includes non-current sources: " + "; ".join(_label(s, t) for s, t in zip(d.series, d.status)) + ".")
    return out


def source_status(df):
    g = df.groupby(["series", "status", "effective"]).agg(rows=("rate", "size"), min_rate=("rate", "min"), max_rate=("rate", "max")).reset_index()
    return g.rename(columns={"series": "Bank / product", "status": "Status", "effective": "Effective date", "rows": "Rates", "min_rate": "Min %", "max_rate": "Max %"})


def facts(df, amount, statuses=DEFAULT_STATUSES):
    """Everything the AI service may talk about - all computed here, nothing is left for the AI to calculate."""
    c = comparison(df, [amount], TENOR_GRID, statuses).dropna(subset=["gap"]).sort_values("day")
    full = comparison(df, AMOUNT_GRID, TENOR_GRID, statuses)
    gap = full.pivot(index="amount", columns="day", values="gap")
    gap.index = [f"{a:g}Cr" for a in gap.index]
    gap.columns = [fmt_day(d) for d in gap.columns]
    return clean({
        "selected_amount_cr": amount,
        "sber_rate_by_tenor": {fmt_day(r.day): r.sber for r in c.itertuples()},
        "best_peer_by_tenor": {fmt_day(r.day): {"bank": r.best_peer, "rate": r.best_rate, "sber_minus_peer_pp": r.gap} for r in c.itertuples()},
        "gap_grid_pp_by_amount_and_tenor": gap.to_dict("index"),
        "sber_win_share_pct": scorecard(df, statuses).to_dict("index"),
        "key_findings": key_findings(df, amount, statuses),
        "data_as_of": df.groupby("series")["effective"].first().to_dict(),
        "non_current_sources": sorted({_label(s, t) for s, t in zip(df.series, df.status) if t != "current"}),
    })


def bundle(df, prev, amount, statuses=DEFAULT_STATUSES):
    """Everything the UI and the Excel report need, in one call."""
    from src.domain.validation import diff_runs
    full = comparison(df, AMOUNT_GRID, TENOR_GRID, statuses)
    return {
        "curve": curve(df, amount, statuses),
        "gap": full.pivot(index="amount", columns="day", values="gap"),
        "score": scorecard(df, statuses),
        "findings": key_findings(df, amount, statuses),
        "facts": facts(df, amount, statuses),
        "changes": diff_runs(df, prev),
        "sources": source_status(df),
    }
