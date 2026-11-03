"""Analytics dashboard: KPIs, comparison, curves, deposit size, composition, trends, drill-down."""
import pandas as pd
import streamlit as st

from src.config import settings as S
from src.domain import analytics as an
from src.domain import charts as C
from src.domain.parsing import fmt_day
from ui import charts as UC
from ui import theme as T


def filters(df):
    """Sidebar filters -> (amount, days, statuses, banks)."""
    sb = st.sidebar
    sb.markdown("##### Filters")
    amount = sb.number_input("Deposit amount (₹ crore)", min_value=0.1, max_value=1000.0, value=st.session_state.get("amount", 10.0), step=0.5, key="amount")
    days = sb.number_input("Tenor (days)", min_value=7, max_value=3650, value=st.session_state.get("days", 90), step=1, key="days")
    present = [s for s in S.STATUSES if s in set(df.status)]
    picked = sb.multiselect("Source types", present, default=[s for s in S.DEFAULT_STATUSES if s in present],
                            help="current = official corporate rates · proxy = large-deposit table, not corporate-only · default_table = amount tabs not read · stale = older sheet")
    statuses = tuple(dict.fromkeys(["current"] + picked))
    peers = sorted(set(df.series) - {S.SBER})
    banks = sb.multiselect("Peer banks", peers, default=peers)
    return float(amount), int(days), statuses, banks


def render(svc, df, prev, run_id):
    amount, days, statuses, banks = filters(df)
    view = df[df.series.isin([S.SBER] + banks)]
    st_list = list(statuses)

    here = an.rates_at(view, amount, days, st_list)
    sber_row, peers_here = here[here.name == S.SBER], here[here.name != S.SBER]
    c1, c2, c3, c4, c5 = st.columns(5)
    if len(sber_row) and len(peers_here):
        best, gap = peers_here.iloc[0], float(sber_row.rate.iloc[0] - peers_here.iloc[0].rate)
        T.kpi(c1, "Sberbank rate", f"{sber_row.rate.iloc[0]:.2f}%", f"₹{amount:g} Cr · {fmt_day(days)}")
        T.kpi(c2, "Best peer", f"{best.rate:.2f}%", best["name"])
        T.kpi(c3, "Gap to best peer", f"{gap:+.2f} pp", "Sberbank ahead" if gap >= 0 else "Sberbank behind")
        T.kpi(c4, "Sberbank rank", f"{int(sber_row['rank'].iloc[0])} of {len(here)}", "1 = highest rate")
    else:
        T.kpi(c1, "Sberbank rate", "n/a", "no rate for this amount / tenor")
    comp = an.comparison(view, [amount], S.TENOR_GRID, st_list).dropna(subset=["gap"])
    if len(comp):
        T.kpi(c5, "Tenor points led", f"{int((comp.gap >= 0).sum())} of {len(comp)}", f"at ₹{amount:g} Cr")
    st.write("")

    tabs = st.tabs(["Overview", "Market comparison", "Rate curves", "Deposit size", "Composition", "Trends", "Rate explorer"])

    with tabs[0]:
        left, right = st.columns([1.05, 1])
        with left:
            st.markdown(f"##### Key findings at ₹{amount:g} Cr")
            for text in an.key_findings(view, amount, st_list):
                st.markdown(f'<div class="find">{text}</div>', unsafe_allow_html=True)
        with right:
            st.markdown("##### Where Sberbank is #1 (% of cases)")
            score = an.scorecard(view, st_list)
            st.dataframe(score.style.format("{:.0f}%").background_gradient(cmap="Greens", vmin=0, vmax=100), width="stretch")
            st.plotly_chart(UC.render(C.lead_share(view, amount, st_list), 330), width="stretch", key="ov_pie")

    with tabs[1]:
        st.markdown(f"##### All banks at ₹{amount:g} Cr for {fmt_day(days)}")
        if here.empty:
            st.warning("No rates found for this amount and tenor.")
        else:
            spec = C.bank_ranking(view, amount, days, st_list)
            ev = st.plotly_chart(UC.render(spec), width="stretch", on_select="rerun", selection_mode="points", key="rank_chart")
            clicked = None
            try:
                pts = ev.selection.points if ev and ev.selection else []
                clicked = pts[0]["y"] if pts else None
            except Exception:
                clicked = None
            if clicked:
                st.session_state["drill_bank"] = clicked
            show = here.rename(columns={"rank": "Rank", "name": "Bank / product", "rate": "Rate %", "vs_sber_pp": "vs Sber (pp)", "status": "Source type",
                                        "effective": "Effective", "amt_label": "Amount slab", "tenor_label": "Tenor slab"})
            st.dataframe(show.style.apply(lambda r: [f"background-color:{T.MINT};font-weight:700" if r["Bank / product"] == S.SBER else "" for _ in r], axis=1)
                         .format({"Rate %": "{:.2f}", "vs Sber (pp)": "{:+.2f}"}), hide_index=True, width="stretch")
            st.caption("Click a bar to drill into that bank in the **Rate explorer** tab. Quote only 'current' sources to clients.")

    with tabs[2]:
        st.plotly_chart(UC.render(C.rate_curve(view, amount, st_list), 470), width="stretch", key="curve")
        st.plotly_chart(UC.render(C.gap_heatmap(view, st_list), 470), width="stretch", key="heat")

    with tabs[3]:
        st.plotly_chart(UC.render(C.deposit_size(view, days, st_list), 440), width="stretch", key="size")

    with tabs[4]:
        a, b = st.columns(2)
        counts = view.groupby("series").size().sort_values(ascending=False)
        a.plotly_chart(UC.render(dict(kind="pie", title="Rate points collected by bank", x=list(counts.index), series=[dict(name="Rates", values=[int(v) for v in counts.values])], unit="")),
                       width="stretch", key="pie_banks")
        mix = view.drop_duplicates(["series", "status"]).groupby("status").size()
        b.plotly_chart(UC.render(dict(kind="pie", title="Sources by type", x=list(mix.index), series=[dict(name="Sources", values=[int(v) for v in mix.values])], unit="")),
                       width="stretch", key="pie_status")
        st.dataframe(an.source_status(view), hide_index=True, width="stretch")

    with tabs[5]:
        spec = C.history(svc.store.history(), amount, days, st_list)
        st.plotly_chart(UC.render(spec), width="stretch", key="hist")
        for f in spec["facts"]:
            st.markdown(f'<div class="note">{f}</div>', unsafe_allow_html=True)
        st.markdown("##### Rate changes since the previous update")
        from src.domain.validation import diff_runs
        d = diff_runs(df, prev)
        st.dataframe(d.head(300), hide_index=True, width="stretch") if len(d) else st.info("No rate changes since the previous update.")

    with tabs[6]:
        names = sorted(set(view.series) - {S.SBER})
        default = st.session_state.get("drill_bank")
        idx = names.index(default) if default in names else 0
        if not names:
            st.info("No peer banks selected.")
        else:
            bank = st.selectbox("Bank / product", names, index=idx)
            peer = view[view.series == bank]
            cc = C.rate_curve(view, amount, st_list, banks=[S.SBER, bank])
            st.plotly_chart(UC.render(cc), width="stretch", key="drill_curve")
            st.markdown(f"##### {bank}: published rate grid")
            grid = peer.pivot_table(index="tenor_label", columns="amt_label", values="rate", aggfunc="max", sort=False)
            st.dataframe(grid.style.format("{:.2f}", na_rep="–"), width="stretch")
            st.caption(f"Source type: {peer.status.iloc[0]} · effective {peer.effective.iloc[0]} · {len(peer)} rates")
