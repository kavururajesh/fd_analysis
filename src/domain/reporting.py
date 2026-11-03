"""Excel pack: summary, curve with native chart, gap heatmap, scorecard, all rates, changes."""
import io

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows

from src.config.settings import SBER
from src.domain.parsing import fmt_day

GREEN = "21A038"
HEAD_FILL, HEAD_FONT = PatternFill("solid", fgColor=GREEN), Font(bold=True, color="FFFFFF")


def _sheet(wb, title, df, index_name=None):
    ws = wb.create_sheet(title)
    d = df.reset_index() if index_name else df
    if index_name:
        d = d.rename(columns={d.columns[0]: index_name})
    d = d.astype(object).where(d.notna(), None)
    for row in dataframe_to_rows(d, index=False, header=True):
        ws.append(row)
    for c in ws[1]:
        c.fill, c.font = HEAD_FILL, HEAD_FONT
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 3, 40)
    ws.freeze_panes = "B2"
    return ws


def report_bytes(df, b, amount):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"Sberbank corporate FD benchmark - deposit of ₹{amount:g}Cr"
    ws["A1"].font = Font(bold=True, size=14, color=GREEN)
    for i, text in enumerate(b["findings"], start=3):
        ws.cell(i, 1, f"{i - 2}. {text}").alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 130

    cur = b["curve"].copy()
    cur.index = [fmt_day(d) for d in cur.index]
    cs = _sheet(wb, "Curve", cur, "Tenor")
    chart = LineChart()
    chart.title, chart.height, chart.width = f"Rate (%) by tenor at ₹{amount:g}Cr", 11, 26
    chart.add_data(Reference(cs, min_col=2, max_col=cur.shape[1] + 1, min_row=1, max_row=len(cur) + 1), titles_from_data=True)
    chart.set_categories(Reference(cs, min_col=1, min_row=2, max_row=len(cur) + 1))
    for s, name in zip(chart.series, cur.columns):
        s.smooth = False
        if name == SBER:
            s.graphicalProperties.line.solidFill, s.graphicalProperties.line.width = GREEN, 38100
    cs.add_chart(chart, f"A{len(cur) + 4}")

    gap = b["gap"].copy()
    gap.index = [f"₹{a:g}Cr" for a in gap.index]
    gap.columns = [fmt_day(d) for d in gap.columns]
    gs = _sheet(wb, "Sber vs best peer (pp)", gap, "Deposit")
    gs.conditional_formatting.add(f"B2:{gs.cell(1, gap.shape[1] + 1).column_letter}{len(gap) + 1}",
                                  ColorScaleRule(start_type="num", start_value=-4, start_color="9AA5A0", mid_type="num", mid_value=0, mid_color="FFFFFF", end_type="num", end_value=4, end_color=GREEN))
    gs.cell(len(gap) + 3, 1, "Green = Sberbank pays more than the best peer; grey = less. Values are percentage points.")
    _sheet(wb, "Scorecard (win %)", b["score"], "Deposit size")
    _sheet(wb, "All rates", df.drop(columns=["run"], errors="ignore"))
    _sheet(wb, "Changes", b["changes"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
