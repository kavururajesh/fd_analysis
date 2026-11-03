"""Quality gates. Errors = structurally invalid (blocked). Warnings = plausible but needs a human look."""
import pandas as pd

from src.config.settings import MAX_RATE_MOVE_PP, SBER

KEY = ["amt_lo", "amt_hi", "d_lo", "d_hi"]


def _keyed(df):
    d = df.copy()
    for c in KEY:
        d[c] = d[c].round(6)
    return d


def validate_source(df, expect=None, prev=None):
    """Check one source's canonical rows. Returns {'errors','warnings','metrics'}."""
    expect = expect or {}
    errors, warnings = [], []
    lo, hi = expect.get("rate_range", (0, 15))
    if not df["rate"].between(lo, hi).all():
        errors.append(f"rates outside {lo}-{hi}%: {sorted(df.loc[~df['rate'].between(lo, hi), 'rate'].unique())[:5]}")
    if (df["d_lo"] > df["d_hi"]).any() or (df["amt_lo"] >= df["amt_hi"]).any():
        errors.append("a tenor or amount range is inverted")
    if df.duplicated(["amt_label", "tenor_label"]).any():
        errors.append("duplicate (amount slab, tenor) rows - a table may have been read twice")
    min_rows = expect.get("min_rows", 4)
    if len(df) < min_rows:
        errors.append(f"only {len(df)} rates found (expected at least {min_rows})")
    if "slabs" in expect and df["amt_label"].nunique() != expect["slabs"]:
        errors.append(f"found {df['amt_label'].nunique()} amount slabs, expected {expect['slabs']}")
    metrics = dict(rows=len(df), slabs=int(df["amt_label"].nunique()), tenors=int(df["tenor_label"].nunique()),
                   rate_min=float(df["rate"].min()), rate_max=float(df["rate"].max()))
    if prev is not None and len(prev):
        merged = _keyed(df).merge(_keyed(prev)[KEY + ["rate"]], on=KEY, how="outer", suffixes=("", "_old"), indicator=True)
        both = merged[merged["_merge"] == "both"]
        overlap = len(both) / max(len(prev), 1)
        metrics["similarity_to_published"] = round(overlap, 2)
        if overlap < 0.5:
            warnings.append(f"only {overlap:.0%} of the published rate grid matches this layout")
        change = (both["rate"] - both["rate_old"]).abs()
        metrics["rates_changed"] = int((change > 1e-9).sum())
        metrics["max_move_pp"] = round(float(change.max()), 2) if len(change) else 0.0
        if len(change) and change.max() > MAX_RATE_MOVE_PP:
            warnings.append(f"{int((change > MAX_RATE_MOVE_PP).sum())} rates moved by more than {MAX_RATE_MOVE_PP:g} pp")
        drift = abs(len(df) - len(prev)) / len(prev)
        if drift > 0.35:
            errors.append(f"row count changed {len(prev)} -> {len(df)} ({drift:.0%}); extraction is probably partial")
        elif drift > 0.2:
            warnings.append(f"row count changed {len(prev)} -> {len(df)}")
    return dict(errors=errors, warnings=warnings, metrics=metrics)


def validate_dataset(df, prev=None):
    """Cross-source checks on the combined staged dataset."""
    errors, warnings = [], []
    if df.empty:
        return ["no rates at all"], warnings
    if SBER not in set(df["series"]):
        errors.append(f"{SBER} rates are missing - the benchmark needs our own rates")
    if df.duplicated(["series", "amt_lo", "amt_hi", "d_lo", "d_hi"]).any():
        errors.append("duplicate rate cells in the combined dataset")
    if prev is not None and len(prev):
        missing = set(prev["series"]) - set(df["series"])
        if missing:
            warnings.append(f"series missing compared with the published data: {sorted(missing)}")
    non_current = df[df["status"] != "current"].drop_duplicates(["series", "status"])
    for r in non_current.itertuples():
        warnings.append(f"{r.series}: source status is '{r.status}'")
    return errors, warnings


def diff_runs(cur, prev):
    """Rates added / removed / changed between two datasets (matched by numeric slab, so renamed labels still match)."""
    cols = ["series", "amt_label", "tenor_label", "old", "new", "change_pp", "kind"]
    if cur is None or prev is None or len(prev) == 0:
        return pd.DataFrame(columns=cols)
    key = ["series"] + KEY
    a, b = _keyed(cur), _keyed(prev)
    m = a[key + ["amt_label", "tenor_label", "rate"]].merge(
        b[key + ["amt_label", "tenor_label", "rate"]], on=key, how="outer", suffixes=("_new", "_old"), indicator=True)
    m["amt_label"] = m["amt_label_new"].fillna(m["amt_label_old"])
    m["tenor_label"] = m["tenor_label_new"].fillna(m["tenor_label_old"])
    m["kind"] = m["_merge"].map({"left_only": "added", "right_only": "removed", "both": "changed"})
    m = m[(m["kind"] != "changed") | (m["rate_new"].sub(m["rate_old"]).abs() > 1e-9)]
    m = m.rename(columns={"rate_old": "old", "rate_new": "new"})
    m["change_pp"] = (m["new"] - m["old"]).round(2)
    return m[cols].sort_values("change_pp", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
