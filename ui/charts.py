"""Plotly renderer for chart specs (src/domain/charts.py). One function used by the dashboard and the chatbot."""
import plotly.graph_objects as go

from src.config.settings import SBER
from ui import theme as T


def _fmt(unit):
    return "%{y:.2f}%" if unit == "%" else "%{y:.2f}"


def render(spec, height=430):
    kind, unit = spec["kind"], spec.get("unit", "%")
    fig = go.Figure()
    colours = iter(T.PEERS)
    if kind == "line":
        for s in spec["series"]:
            sber = s["name"] in (SBER, "Sberbank")
            fig.add_trace(go.Scatter(x=spec["x"], y=s["values"], name=s["name"], mode="lines+markers", connectgaps=False,
                                     line=dict(color=T.GREEN if sber else next(colours), width=5 if sber else 2.5, dash="dot" if "(" in s["name"] else "solid"),
                                     marker=dict(size=9 if sber else 6), hovertemplate="%{x}: " + _fmt(unit) + "<extra>" + s["name"] + "</extra>"))
        fig.update_xaxes(type="category")
    elif kind == "bar":
        s = spec["series"][0]
        fig.add_trace(go.Bar(x=s["values"], y=spec["x"], orientation="h", marker_color=[T.GREEN if n == SBER else T.TEAL for n in spec["x"]],
                             text=s["values"], texttemplate="%{x:.2f}%", textposition="outside", hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, max([v for v in s["values"] if v is not None] + [1]) * 1.18])
        height = max(260, 70 + 46 * len(spec["x"]))
    elif kind == "bar_line":
        for s in spec["series"]:
            if s.get("type") == "bar":
                fig.add_trace(go.Bar(x=spec["x"], y=s["values"], name=s["name"], marker_color=T.GREEN, text=s["values"], texttemplate="%{y:.2f}%", textposition="outside"))
            else:
                fig.add_trace(go.Scatter(x=spec["x"], y=s["values"], name=s["name"], mode="lines+markers", line=dict(color=T.TEAL, width=3),
                                         text=s.get("labels"), hovertemplate="%{text}: %{y:.2f}%<extra></extra>"))
        fig.update_xaxes(type="category")
    elif kind == "pie":
        s = spec["series"][0]
        fig.add_trace(go.Pie(labels=spec["x"], values=s["values"], hole=0.55, sort=False, marker=dict(colors=[T.GREEN, "#7FBF9A", T.GREY, T.TEAL, T.INK, "#A3B8AE", "#0B4F3F", "#5BC0A0"]),
                             textinfo="percent", hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"))
        fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-0.05))
        height = min(height, 380)
    elif kind == "heatmap":
        z = [s["values"] for s in spec["series"]]
        m = max([abs(v) for r in z for v in r if v is not None] + [1])
        text = [["" if v is None else f"{v:+.2f}" for v in r] for r in z]
        fig.add_trace(go.Heatmap(z=z, x=spec["x"], y=[s["name"] for s in spec["series"]], text=text, texttemplate="%{text}", zmin=-m, zmax=m, xgap=2, ygap=2,
                                 colorscale=[[0, "#6B7570"], [0.5, "#FFFFFF"], [1, T.GREEN]], colorbar=dict(title="pp")))
        fig.update_yaxes(autorange="reversed", type="category")
        fig.update_xaxes(type="category", side="top")
    fig.update_layout(title=dict(text=spec.get("title", ""), font=dict(size=15), x=0.0) if spec.get("title") else None)
    if spec.get("y_title") and kind in ("line", "bar_line"):
        fig.update_yaxes(title=spec["y_title"])
    if spec.get("x_title") and kind in ("line", "bar_line"):
        fig.update_xaxes(title=spec["x_title"])
    fig = T.style(fig, height)
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10))
    if kind == "pie":
        fig.update_layout(legend=dict(orientation="h", y=-0.02))
    return fig
