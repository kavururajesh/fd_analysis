"""Sberbank India - Corporate Deposits Analytics.   Run:  python -m src.main ui   (or run_ui.bat)"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import streamlit as st

from src.config import settings as S
from src.service import FDService
from ui import theme as T
from ui.views import assistant, dashboard, operations

st.set_page_config(page_title="Corporate Deposits Analytics · Sberbank India", page_icon="🟢", layout="wide")
T.inject()


@st.cache_resource
def service():
    return FDService()


svc = service()
run_id, df, prev = svc.data()

# ---------------- sidebar ----------------
sb = st.sidebar
sb.markdown(f"<div style='font-weight:800;font-size:1.05rem;color:{T.DARK}'>Sberbank India</div><div style='color:#6B736E;font-size:.8rem;margin-bottom:10px'>Corporate Deposits Analytics</div>", unsafe_allow_html=True)
page = sb.radio("Navigate", ["Dashboard", "Analytics assistant", "Data operations"], label_visibility="collapsed")
sb.divider()

# ---------------- header ----------------
as_of = df.loc[df.series == S.SBER, "effective"].iloc[0] if df is not None and (df.series == S.SBER).any() else "–"
updated = (svc.files.manifest() or {}).get("created", "")[:16].replace("T", " ")
st.markdown(f"""<div class="topbar"><div class="brand"><div class="logo">S</div><div><h1>Corporate Fixed Deposit Benchmark</h1>
<div class="sub">Sberbank India vs peer banks · official bank sources</div></div></div>
<div class="sub" style="text-align:right">Sberbank rates as of <b>{as_of}</b><br>Dataset updated {updated or '–'}</div></div>""", unsafe_allow_html=True)

if page == "Dashboard":
    if df is None:
        st.info("No data is available yet. Open **Data operations** and run the first refresh.")
    else:
        dashboard.render(svc, df, prev, run_id)
elif page == "Analytics assistant":
    assistant.render(svc, df is not None)
else:
    operations.render(svc)

# ---------------- sidebar footer ----------------
engine = "GigaChat" if not svc.llm.is_offline else "Rule-based (GigaChat not connected)"
sb.caption(f"Language engine: {engine}")
sb.caption("Data source: " + ("saved page snapshots" if S.SOURCE_MODE == "local" else "live bank websites"))
if df is not None:
    from src.domain import reporting, analytics as an
    amount = float(st.session_state.get("amount", 10.0))
    bundle = an.bundle(df, prev, amount)
    sb.download_button("Download Excel report", reporting.report_bytes(df, bundle, amount), "FD_Benchmark_Report.xlsx", width="stretch")
