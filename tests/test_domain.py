import pandas as pd
import pytest

from src.domain.layout import LayoutError, LayoutSpec, apply_layout, suggest_layout
from src.domain.parsing import parse_amount, parse_days_arg, parse_tenor
from src.domain.schema import to_canonical
from src.domain.validation import diff_runs, validate_source


def test_tenor_parsing():
    assert parse_tenor("7–14 days") == (7, 14)
    assert parse_tenor("211d–<1y") == (211, 364)
    assert parse_tenor("1–<2 years") == (365, 729)
    assert parse_days_arg("1y") == 365 and parse_days_arg("6m") == 180


def test_amount_parsing_slab_edges():
    assert parse_amount("₹3Cr–<₹10Cr") == (3.0, 10.0)           # [3,10)
    lo, hi = parse_amount(">₹3.50–4Cr")                          # (3.5,4]
    assert lo > 3.5 and hi > 4.0 and lo < 3.51
    assert parse_amount("₹3Cr to ₹10Cr")[0] == 3.0


def test_bad_labels_rejected():
    for bad in ("Home loan", "Notice", ""):
        with pytest.raises(ValueError):
            parse_tenor(bad)


def raw(rows):
    return pd.DataFrame(rows)


GOOD = [["Tenor", "<₹3Cr", "₹3Cr–<₹10Cr"], ["7–14 days", "0.25%", "3.75%"], ["15–30 days", "0.5%", "4.75%"], ["31–90 days", "0.75%", "6%"]]


def test_layout_suggest_and_apply():
    t = raw(GOOD)
    spec = suggest_layout(t)
    assert spec and spec["orientation"] == "tenor_rows" and spec["value_cols"] == [1, 2]
    tidy = apply_layout(t, LayoutSpec.from_dict({k: v for k, v in spec.items() if not k.startswith("_")}))
    assert len(tidy) == 6 and tidy.rate.max() == 4.75 + 1.25 or tidy.rate.max() == 6.0


def test_layout_transposed_and_decoy():
    transposed = raw([["Amount", "7–14d", "15–30d", "31–45d"], ["₹3–5Cr", 4.75, 5, 5], [">₹5–10Cr", 4.75, 5, 5]])
    s = suggest_layout(transposed)
    assert s and s["orientation"] == "amount_rows"
    assert suggest_layout(raw([["Loan", "Rate"], ["Home", "8.5%"], ["Car", "8.9%"]])) is None


def test_wrong_layout_raises_clear_error():
    with pytest.raises(LayoutError):
        apply_layout(raw(GOOD), LayoutSpec.from_dict({"table_index": 0, "value_cols": [9]}))


def meta(i="x"):
    return dict(id=i, bank="B", product="p", status="current", effective="2026-10-21")


def canon(t=GOOD, i="x"):
    spec = suggest_layout(raw(t))
    tidy = apply_layout(raw(t), LayoutSpec.from_dict({k: v for k, v in spec.items() if not k.startswith("_")}))
    return to_canonical(tidy, meta(i))


def test_canonical_and_validation():
    df = canon()
    assert set(df.columns) >= {"series", "amt_lo", "d_lo", "rate"} and df.series.iloc[0] == "B p"
    ok = validate_source(df, {"min_rows": 4})
    assert not ok["errors"]
    assert validate_source(df, {"min_rows": 50})["errors"]
    bad = df.copy()
    bad.loc[0, "rate"] = 80
    assert validate_source(bad)["errors"]


def test_big_move_and_row_drift_flagged():
    prev = canon()
    cur = prev.copy()
    cur.loc[0, "rate"] += 2
    assert validate_source(cur, {"min_rows": 1}, prev)["warnings"]
    assert validate_source(cur.head(2), {"min_rows": 1}, prev)["errors"]      # >35% rows lost


def test_diff_runs():
    prev = canon()
    cur = prev.copy()
    cur.loc[0, "rate"] += 0.5
    d = diff_runs(cur, prev)
    assert len(d) == 1 and d.iloc[0].change_pp == 0.5


def test_live_config_is_valid_and_covers_many_banks():
    from src.config import settings as S
    from src.tools.sources import load_sources
    live = load_sources(S.CONFIG_DIR / "sources.live.yaml")
    ids = [s.id for s in live]
    assert len(ids) == len(set(ids)) and len(live) >= 11
    assert {"Sberbank", "HDFC", "ICICI", "SBI", "RBL", "Axis", "PNB", "Canara"} <= {s.bank for s in live}
    assert all(s.url.startswith("https://") and s.kind in ("html", "browser", "pdf") for s in live)
