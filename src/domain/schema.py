"""Canonical rate table used everywhere (storage, analytics, UI)."""
import pandas as pd

from src.domain.parsing import parse_amount, parse_tenor

COLUMNS = ["source_id", "bank", "product", "series", "status", "effective", "amt_label", "tenor_label",
           "amt_lo", "amt_hi", "d_lo", "d_hi", "rate"]


def to_canonical(tidy, meta, effective=None):
    """tidy[tenor_label, amt_label, rate] + source metadata -> canonical rows. Raises ValueError on unreadable labels."""
    df = tidy.dropna(subset=["rate"]).copy()
    bad_t = [t for t in df["tenor_label"].unique() if not _ok(parse_tenor, t)]
    bad_a = [a for a in df["amt_label"].unique() if not _ok(parse_amount, a)]
    if bad_t or bad_a:
        raise ValueError(f"unreadable labels - tenor: {bad_t[:4]} amount: {bad_a[:4]} (wrong table or wrong columns chosen?)")
    amounts = {a: parse_amount(a) for a in df["amt_label"].unique()}
    tenors = {t: parse_tenor(t) for t in df["tenor_label"].unique()}
    df["amt_lo"] = df["amt_label"].map(lambda a: amounts[a][0])
    df["amt_hi"] = df["amt_label"].map(lambda a: amounts[a][1])
    df["d_lo"] = df["tenor_label"].map(lambda t: tenors[t][0])
    df["d_hi"] = df["tenor_label"].map(lambda t: tenors[t][1])
    df["source_id"], df["bank"], df["product"] = meta["id"], meta["bank"], meta["product"]
    df["series"] = f'{meta["bank"]} {meta["product"]}'
    df["status"] = meta["status"]
    df["effective"] = str(effective or meta.get("effective", ""))
    return df[COLUMNS].reset_index(drop=True)


def _ok(fn, value):
    try:
        fn(value)
        return True
    except ValueError:
        return False
