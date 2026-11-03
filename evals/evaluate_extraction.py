"""Extraction accuracy: compare what the agents extracted from the local snapshots with the reference workbook (ground truth).
Run:  python -m evals.evaluate_extraction            (uses the latest staged/published run)"""
import sys
from collections import Counter

import openpyxl

from src.config import settings as S
from src.localsite.build_fixtures import SHEETS, read_sheet
from src.memory.store import Store

SOURCE_SHEET = dict(sber_corporate="sber", hdfc_withdrawable="hdfc", rbl_callable="rbl_c", rbl_noncallable="rbl_n", idfc_callable="idfc_c",
                    idfc_noncallable="idfc_n", sbi_bulk="sbi", icici_callable="icici_c", icici_noncallable="icici_n")


def truth():
    wb = openpyxl.load_workbook(S.FIXTURE_DIR / "reference_workbook.xlsx", data_only=True)
    out = {}
    for sid, key in SOURCE_SHEET.items():
        _, data = read_sheet(wb, SHEETS[key])
        out[sid] = Counter(round(float(v), 2) for r in data for v in r[1:] if isinstance(v, (int, float)))
    return out


def evaluate(df):
    t, rows = truth(), []
    for sid, expected in t.items():
        got = Counter(round(float(v), 2) for v in df.loc[df.source_id == sid, "rate"])
        rows.append(dict(source=sid, expected_cells=sum(expected.values()), extracted=sum(got.values()),
                         exact=got == expected, missing=sum((expected - got).values()), extra=sum((got - expected).values())))
    return rows


if __name__ == "__main__":
    store = Store()
    runs = store.list_runs(1)
    if runs.empty:
        sys.exit("no runs yet - run a refresh first")
    rid = runs.iloc[0]["run_id"]
    rows = evaluate(store.load_rates(rid))
    print(f"run {rid}")
    for r in rows:
        print(f"{'OK ' if r['exact'] else 'BAD'} {r['source']:<18} expected {r['expected_cells']:>4}  extracted {r['extracted']:>4}  missing {r['missing']}  extra {r['extra']}")
    ok = sum(r["exact"] for r in rows)
    print(f"\n{ok}/{len(rows)} sources match the ground truth exactly")
    sys.exit(0 if ok == len(rows) else 1)
