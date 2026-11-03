"""LayoutSpec = a small JSON recipe that says WHERE the numbers are in a raw table.
The LLM (or a config file) only produces the recipe; this code reads the numbers. The LLM never types a rate.
"""
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import pandas as pd

from src.domain.parsing import DEFAULT_AMOUNT_LABEL, is_amount_label, is_tenor_label


class LayoutError(ValueError):
    pass


@dataclass
class LayoutSpec:
    table_index: int = 0                         # which table on the page / PDF
    orientation: str = "tenor_rows"              # tenor_rows: each row is a tenor, columns are amount slabs | amount_rows: the opposite
    label_col: int = 0                           # column that holds the row labels
    value_cols: Optional[List[int]] = None       # columns that hold the rates (None = every other column)
    header_row: Optional[int] = 0                # row that holds the column labels (None = no header row)
    column_labels: Optional[List[str]] = None    # override the header labels
    default_label: Optional[str] = None          # for tables without an amount dimension, e.g. "Default/popular"
    skip_rows: List[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise LayoutError("spec must be a JSON object")
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        try:
            spec = cls(**known)
            spec.table_index = int(spec.table_index)
            spec.label_col = int(spec.label_col)
            spec.header_row = None if spec.header_row in (None, "null") else int(spec.header_row)
            spec.value_cols = None if spec.value_cols in (None, []) else [int(c) for c in spec.value_cols]
            spec.skip_rows = [int(r) for r in (spec.skip_rows or [])]
        except (TypeError, ValueError) as e:
            raise LayoutError(f"invalid spec field: {e}")
        if spec.orientation not in ("tenor_rows", "amount_rows"):
            raise LayoutError("orientation must be 'tenor_rows' or 'amount_rows'")
        return spec

    def to_dict(self):
        return asdict(self)


def _cell(x):
    return "" if pd.isna(x) else re.sub(r"\s+", " ", str(x)).strip()


def to_number(x):
    s = _cell(x).replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def normalise(raw):
    """Raw table -> all-text table with integer column names (rows keep their positions)."""
    t = raw.copy().reset_index(drop=True)
    t.columns = range(t.shape[1])
    return t.astype(object).apply(lambda col: col.map(_cell))


def apply_layout(raw, spec):
    """Raw table + spec -> DataFrame[tenor_label, amt_label, rate]. Raises LayoutError with a precise reason."""
    t = normalise(raw)
    nrows, ncols = t.shape
    if spec.label_col >= ncols:
        raise LayoutError(f"label_col {spec.label_col} does not exist (table has {ncols} columns)")
    value_cols = spec.value_cols or [c for c in range(ncols) if c != spec.label_col]
    if any(c >= ncols or c < 0 for c in value_cols):
        raise LayoutError(f"value_cols {value_cols} out of range (table has {ncols} columns)")
    if spec.header_row is not None and spec.header_row >= nrows:
        raise LayoutError(f"header_row {spec.header_row} out of range (table has {nrows} rows)")
    if spec.column_labels is not None:
        if len(spec.column_labels) != len(value_cols):
            raise LayoutError(f"column_labels has {len(spec.column_labels)} items but value_cols has {len(value_cols)}")
        labels = [str(x) for x in spec.column_labels]
    elif spec.header_row is not None and not spec.default_label:
        labels = [t.iat[spec.header_row, c] for c in value_cols]
    elif spec.default_label:
        labels = [spec.default_label] * len(value_cols)
    else:
        raise LayoutError("no column labels: set header_row, column_labels or default_label")
    body = t.iloc[(spec.header_row + 1) if spec.header_row is not None else 0:]
    body = body.drop(index=[i for i in spec.skip_rows if i in body.index])
    rows = []
    for _, r in body.iterrows():
        label = r[spec.label_col]
        if not label:
            continue
        for c, col_label in zip(value_cols, labels):
            value = to_number(r[c])
            if value is not None:
                rows.append((label, col_label, value))
    if not rows:
        raise LayoutError("no numeric rate cells found with this spec")
    df = pd.DataFrame(rows, columns=["row_label", "col_label", "rate"])
    if spec.orientation == "tenor_rows":
        df = df.rename(columns={"row_label": "tenor_label", "col_label": "amt_label"})
    else:
        df = df.rename(columns={"row_label": "amt_label", "col_label": "tenor_label"})
    return df[["tenor_label", "amt_label", "rate"]]


def suggest_layout(raw):
    """Heuristic: find a header row, the label column and the numeric columns. Returns a spec dict with '_score', or None."""
    t = normalise(raw)
    nrows, ncols = t.shape
    if nrows < 3 or ncols < 2:
        return None
    best = None
    for hr in range(min(4, nrows - 1)):
        body = t.iloc[hr + 1:]
        for orientation, header_test, label_test in (("tenor_rows", is_amount_label, is_tenor_label),
                                                     ("amount_rows", is_tenor_label, is_amount_label)):
            scores = [(sum(label_test(v) for v in body[c]), c) for c in range(min(3, ncols))]
            label_score, lc = max(scores, key=lambda s: (s[0], -s[1]))
            if label_score < 2:
                continue
            rows = body[body[lc].map(label_test)]
            value_cols = [c for c in range(ncols) if c != lc and len(rows) and
                          sum(to_number(v) is not None for v in rows[c]) / len(rows) >= 0.6]
            header_ok = [c for c in value_cols if header_test(t.iat[hr, c])]
            if header_ok:
                cols, default, score = header_ok, None, label_score + 2 * len(header_ok)
            elif orientation == "tenor_rows" and len(value_cols) == 1:
                cols, default, score = value_cols, DEFAULT_AMOUNT_LABEL, label_score
            else:
                continue
            if best is None or (score, -hr) > (best[0], -best[1]):
                best = (score, hr, dict(orientation=orientation, label_col=lc, value_cols=cols, header_row=hr,
                                        column_labels=None, default_label=default, skip_rows=[]))
    if best is None:
        return None
    spec = best[2]
    spec["_score"] = best[0]
    return spec


def preview(raw, max_rows=6, max_cols=8, width=20):
    """Compact view of a raw table for the LLM / UI: a list of rows (index, cells)."""
    t = normalise(raw)
    return [[i] + [c[:width] for c in t.iloc[i, :max_cols].tolist()] for i in range(min(max_rows, len(t)))]
