"""Sberbank look & feel + chart helpers (colours: Sber green family only, plus neutral greys)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config.settings import SBER
from src.domain.parsing import fmt_day

GREEN, DARK, MINT, TEAL, INK, GREY = "#21A038", "#0E6B2D", "#F1F7F3", "#107F8C", "#1A1A1A", "#8C9A93"
PEERS = [TEAL, INK, "#5BC0A0", GREY, "#0B4F3F", "#A3B8AE", "#3B5B52", "#7FBF9A"] * 2

CSS = f"""<style>
html, body, [class*="css"] {{font-family: "Segoe UI", Calibri, Arial, sans-serif;}}
.stApp {{background:#F6F8F7;}}
.block-container {{padding-top: 1.2rem; max-width: 1480px;}}
header[data-testid="stHeader"] {{background: transparent;}}
section[data-testid="stSidebar"] {{background:#FFFFFF; border-right:1px solid #E3E9E5;}}
.topbar {{display:flex; align-items:center; justify-content:space-between; background:#FFFFFF; border:1px solid #E3E9E5; border-radius:12px; padding:14px 22px; margin-bottom:14px; flex-wrap:wrap; gap:8px;}}
.topbar .brand {{display:flex; align-items:center; gap:12px;}}
.topbar .logo {{width:34px; height:34px; border-radius:9px; background:linear-gradient(135deg,{GREEN},{DARK}); color:#fff; font-weight:800; display:flex; align-items:center; justify-content:center;}}
.topbar h1 {{font-size:1.25rem; margin:0; padding:0; color:{INK};}}
.topbar .sub {{font-size:.8rem; color:#6B736E;}}
.card {{background:#FFFFFF; border:1px solid #E3E9E5; border-radius:12px; padding:14px 18px; margin-bottom:12px;}}
.kpi {{background:#FFFFFF; border:1px solid #E3E9E5; border-top:4px solid {GREEN}; border-radius:10px; padding:12px 16px; height:100%;}}
.kpi .l {{font-size:.72rem; color:#6B736E; text-transform:uppercase; letter-spacing:.06em;}}
.kpi .v {{font-size:1.75rem; font-weight:700; color:{DARK}; line-height:1.25;}}
.kpi .s {{font-size:.82rem; color:#6B736E;}}
.find {{background:#FFFFFF; border:1px solid #E3E9E5; border-left:4px solid {GREEN}; border-radius:8px; padding:9px 14px; margin-bottom:8px; font-size:.92rem;}}
.note {{background:{MINT}; border-radius:8px; padding:10px 14px; font-size:.92rem; color:#2B3A31; margin-top:4px;}}
.pill {{display:inline-block; padding:2px 10px; border-radius:12px; font-size:.76rem; font-weight:600; margin-right:6px;}}
.p-ok {{background:#DDF1E2; color:{DARK};}} .p-warn {{background:#FFF1CC; color:#7A5A00;}} .p-bad {{background:#F9D9D6; color:#8A1C13;}} .p-grey {{background:#E6EAE8; color:#44504A;}}
.trace {{font-family: Consolas, monospace; font-size:.8rem; line-height:1.45; background:#0F1A14; color:#CFE8D6; padding:12px 14px; border-radius:8px; max-height:380px; overflow:auto;}}
.trace .a {{color:#7CE39A;}} .trace .w {{color:#F2C65B;}} .trace .e {{color:#FF8E86;}} .trace .t {{color:#8FB3A0;}}
.stTabs [data-baseweb="tab-list"] {{gap:4px; border-bottom:1px solid #E3E9E5;}}
.stTabs [aria-selected="true"] {{color:{GREEN} !important; font-weight:600;}}
div.stButton > button, div.stDownloadButton > button {{background:{GREEN}; color:#fff; border:0; border-radius:8px; font-weight:600;}}
div.stButton > button:hover, div.stDownloadButton > button:hover {{background:{DARK}; color:#fff;}}
div[data-testid="stPlotlyChart"] {{background:#FFFFFF; border:1px solid #E3E9E5; border-radius:12px; padding:6px;}}
@media (max-width: 780px) {{ .kpi .v {{font-size:1.4rem;}} .topbar {{padding:10px 14px;}} }}
</style>"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def pill(text, kind="grey"):
    return f'<span class="pill p-{kind}">{text}</span>'


def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>', unsafe_allow_html=True)


def style(fig, height=430):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white", paper_bgcolor="white",
                      font=dict(family="Segoe UI, Arial", color=INK), legend=dict(orientation="h", y=-0.22))
    fig.update_xaxes(showgrid=False, linecolor="#D5DDD8")
    fig.update_yaxes(gridcolor="#E8EEEA", zeroline=False)
    return fig


def curve_fig(curve):
    fig, colours = go.Figure(), iter(PEERS)
    x = [fmt_day(d) for d in curve.index]
    for name in [SBER] + [c for c in curve.columns if c != SBER]:
        if name not in curve.columns:
            continue
        is_sber = name == SBER
        fig.add_trace(go.Scatter(x=x, y=curve[name], name=name, mode="lines+markers", connectgaps=False,
                                 line=dict(color=GREEN if is_sber else next(colours), width=5 if is_sber else 2.5, dash="dot" if "(" in name else "solid"),
                                 marker=dict(size=9 if is_sber else 6)))
    fig.update_yaxes(title="Interest rate (% p.a.)")
    fig.update_xaxes(title="Tenor", type="category")
    return style(fig, 460)


def heat_fig(gap):
    m = max(float(gap.abs().max().max()), 1)
    text = [["" if pd.isna(v) else f"{v:+.2f}" for v in row] for row in gap.values]
    fig = go.Figure(go.Heatmap(z=gap.values, x=[fmt_day(d) for d in gap.columns], y=[f"₹{a:g}Cr" for a in gap.index], text=text, texttemplate="%{text}",
                               colorscale=[[0, "#6B7570"], [0.5, "#FFFFFF"], [1, GREEN]], zmin=-m, zmax=m, colorbar=dict(title="pp"), xgap=2, ygap=2))
    fig.update_yaxes(autorange="reversed", type="category")
    fig.update_xaxes(type="category", side="top")
    return style(fig, 460)


def trace_html(events):
    cls = {"action": "a", "warning": "w", "error": "e", "thought": "t", "final": "a"}
    icon = {"action": "▶", "thought": "·", "observation": "←", "warning": "!", "error": "✖", "final": "✔", "info": "i"}
    rows = []
    for e in events[-24:]:
        text = str(e["text"]).replace("&", "&amp;").replace("<", "&lt;")[:260]
        rows.append(f'<div class="{cls.get(e["kind"], "")}">{icon.get(e["kind"], " ")} <b>{e["agent"]}</b> {text}</div>')
    return '<div class="trace">' + "".join(rows) + "</div>"
