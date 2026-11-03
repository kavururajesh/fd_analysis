"""HTML / PDF tables -> raw DataFrames with ALL rows kept (headers included), rowspan / colspan expanded.
pandas.read_html moves header rows away from the body, so we parse ourselves."""
import re
from typing import List

import pandas as pd
from lxml import html as lxml_html


def _text(el):
    return re.sub(r"\s+", " ", " ".join(el.itertext())).strip()


def parse_html_tables(html: str) -> List[pd.DataFrame]:
    if not html or not html.strip():
        return []
    doc = lxml_html.fromstring(html)
    tables = []
    for tbl in doc.iter("table"):
        grid, busy = {}, {}                       # busy[(row, col)] = text carried down by a rowspan
        trs = tbl.xpath("./thead/tr|./tbody/tr|./tfoot/tr|./tr")
        for r, tr in enumerate(trs):
            c = 0
            for cell in tr.xpath("./th|./td"):
                while (r, c) in busy:
                    grid[(r, c)] = busy[(r, c)]
                    c += 1
                text = _text(cell)
                try:
                    cs, rs = max(1, int(cell.get("colspan", 1))), max(1, int(cell.get("rowspan", 1)))
                except ValueError:
                    cs = rs = 1
                for dr in range(rs):
                    for dc in range(cs):
                        if dr == 0:
                            grid[(r, c + dc)] = text
                        else:
                            busy[(r + dr, c + dc)] = text
                c += cs
            while (r, c) in busy:
                grid[(r, c)] = busy[(r, c)]
                c += 1
        if not grid:
            continue
        nrows, ncols = max(k[0] for k in grid) + 1, max(k[1] for k in grid) + 1
        data = [[grid.get((r, c), "") for c in range(ncols)] for r in range(nrows)]
        tables.append(pd.DataFrame(data))
    return tables


def pdf_tables(content: bytes) -> List[pd.DataFrame]:
    """Ruled tables from a PDF (pdfplumber). Tables on consecutive pages with the same column count are joined."""
    import io

    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                df = pd.DataFrame(t).fillna("")
                df = df.astype(object).apply(lambda col: col.map(lambda x: re.sub(r"\s+", " ", str(x)).strip()))
                if out and out[-1].shape[1] == df.shape[1]:
                    out[-1] = pd.concat([out[-1], df], ignore_index=True)
                else:
                    out.append(df)
    return out


def pdf_text(content: bytes, max_pages=1) -> str:
    import io

    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])


def page_text(html: str) -> str:
    if not html:
        return ""
    return re.sub(r"\s+", " ", lxml_html.fromstring(html).text_content())
