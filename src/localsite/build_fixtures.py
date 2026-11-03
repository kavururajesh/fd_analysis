"""Builds local copies of the bank pages from the reference workbook, so the whole system can run offline.
Includes the awkward cases real pages have: JS tab, PDF tables, transposed table, decoy table, single default column,
and a 'drift' variant of the Sberbank page (layout changed) to demonstrate self-healing."""
import html
import math
from pathlib import Path

import openpyxl

from src.config import settings as S

SITE = S.FIXTURE_DIR / "site"
SHEETS = dict(sber="Sberbank Raw", hdfc="HDFC Raw", rbl_c="RBL Callable Raw", rbl_n="RBL Noncall Raw", idfc_c="IDFC Callable 30Apr",
              idfc_n="IDFC Noncall 30Apr", sbi="SBI Raw", icici_c="ICICI Default Current", icici_n="ICICI Default Noncall")

CSS = "<style>body{font-family:Arial;margin:30px}table{border-collapse:collapse;margin:14px 0}td,th{border:1px solid #999;padding:5px 9px;text-align:right}th,td:first-child{text-align:left;background:#eef}</style>"


def read_sheet(wb, name):
    rows = [r for r in wb[name].iter_rows(values_only=True)]
    header = [str(c) for c in rows[2] if c is not None]
    data = [list(r[:len(header)]) for r in rows[3:] if r[0] is not None]
    return header, data


def cell(v):
    return "" if v is None else (f"{v:g}%" if isinstance(v, (int, float)) else html.escape(str(v)))


def table(header, data, extra=""):
    th = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{cell(v)}</td>" for v in r) + "</tr>" for r in data)
    return f"<table {extra}><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def page(title, body, scripts=""):
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>{CSS}</head><body>{body}{scripts}</body></html>"


def transpose(header, data):
    return ["Deposit amount"] + [r[0] for r in data], [[header[j]] + [r[j] for r in data] for j in range(1, len(header))]


def write_pdf(path, title, header, data):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = "Helvetica"
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):      # needs a font that has the rupee sign
        if Path(f).exists():
            pdfmetrics.registerFont(TTFont("Demo", f))
            font = "Demo"
            break
    st = getSampleStyleSheet()
    half = math.ceil(len(data) / 2)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A3), leftMargin=20, rightMargin=20)
    story = []
    for i, chunk in enumerate((data[:half], data[half:])):
        story.append(Paragraph(f"{title} - effective 21-Oct-2026 (page {i + 1})", st["Heading3"]))
        rows = [header] + [[cell(v) for v in r] for r in chunk]
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 6.5), ("FONTNAME", (0, 0), (-1, -1), font),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
        story += [t, PageBreak()] if i == 0 else [t]
    doc.build(story)


def build(force=False):
    SITE.mkdir(parents=True, exist_ok=True)
    if not force and (SITE / "sber.html").exists():
        return SITE
    wb = openpyxl.load_workbook(S.FIXTURE_DIR / "reference_workbook.xlsx", data_only=True)
    sh = {k: read_sheet(wb, v) for k, v in SHEETS.items()}

    h, d = sh["sber"]
    note = "<p>Effective 21-Oct-2026. Rates are per annum, subject to change.</p>"
    (SITE / "sber.html").write_text(page("Sberbank India - Tariffs", "<h1>Corporate Fixed Deposit rates</h1>" + note + table(h, d)), encoding="utf-8")
    # drift: a new 'Product' column and a notice table appear, header renamed -> the known layout breaks
    h2 = ["Product", "Maturity"] + h[1:]
    d2 = [["Corporate FD", r[0]] + r[1:] for r in d]
    notice = table(["Notice", "Date"], [["Rates revised", "21-Oct-2026"]])
    (SITE / "sber_drift.html").write_text(page("Sberbank India - Tariffs", "<h1>Corporate Fixed Deposit rates</h1>" + note + notice + table(h2, d2)), encoding="utf-8")

    h, d = sh["hdfc"]
    script = ("<script>document.getElementById('show').onclick=function(){document.getElementById('rates').innerHTML="
              + repr(table(h, d)) + ";};</script>")
    (SITE / "hdfc.html").write_text(page("HDFC Bank - Interest rates",
        "<h1>Domestic / NRE / NRO term deposits</h1><p>Effective 21-Oct-2026</p><button id='show'>Show large deposit rates</button><div id='rates'></div>", script), encoding="utf-8")

    for key, name in (("rbl_c", "callable"), ("rbl_n", "non-callable")):
        h, d = sh[key]
        write_pdf(SITE / f"rbl_{key[-1]}.pdf", f"RBL Bank bulk FD rates ({name})", h, d)

    for key in ("idfc_c", "idfc_n"):
        h, d = sh[key]
        th, td = transpose(h, d)
        (SITE / f"{key}.html").write_text(page("IDFC FIRST Bank", "<h1>Bulk FD rates</h1><p>Effective 30-Apr-2026</p>" + table(th, td)), encoding="utf-8")

    h, d = sh["sbi"]
    decoy = table(["Loan type", "Rate"], [["Home loan", "8.50%"], ["Car loan", "8.90%"]])
    (SITE / "sbi.html").write_text(page("SBI - Bulk term deposits", "<h1>Domestic bulk term deposits</h1><p>w.e.f. 17-Oct-2026</p>" + decoy + table(h, d)), encoding="utf-8")

    for key in ("icici_c", "icici_n"):
        h, d = sh[key]
        (SITE / f"{key}.html").write_text(page("ICICI Bank - FD rates", "<h1>Corporate FD</h1><p>Effective 21-Oct-2026</p>" + table(h, d)), encoding="utf-8")
    return SITE


if __name__ == "__main__":
    print("built", build(force=True))
