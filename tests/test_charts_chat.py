import json

import pytest

from src.domain import charts as C
from src.llm.offline import OfflineLLM
from src.service import FDService


@pytest.fixture()
def live(store, fixture_site, files):
    svc = FDService(store, OfflineLLM(), files)
    ctx = svc.refresh()
    svc.approve(ctx.run_id)
    return svc


def test_chart_specs_come_from_data(live):
    _, df, _ = live.data()
    spec = C.rate_curve(df, 10)
    assert spec["kind"] == "line" and spec["series"][0]["name"].startswith("Sberbank") and len(spec["x"]) == len(spec["series"][0]["values"])
    assert C.bank_ranking(df, 10, 90)["series"][0]["values"][0] == 7.0
    pie = C.lead_share(df, 10)
    assert pie["kind"] == "pie" and sum(pie["series"][0]["values"]) == 20
    assert C.gap_heatmap(df)["kind"] == "heatmap" and C.deposit_size(df, 90)["kind"] == "bar_line"
    h = C.history(live.store.history(), 10, 90)
    assert h["series"][0]["values"][-1] == 7.0
    json.dumps(spec)                                              # specs are plain JSON


def test_comparison_question_gets_a_chart_with_explanation(live):
    a = live.ask("Compare Sberbank with other banks at 10 cr across tenors")
    assert a.chart and a.chart["kind"] == "line" and a.chart_note and a.grounded
    assert "14 of 20" in a.chart_note


def test_simple_question_gets_text_only(live):
    a = live.ask("What is the rate for 10 cr for 90 days?")
    assert a.chart is None and "7%" in a.text and a.grounded


def test_chart_note_never_contains_invented_numbers(live):
    from src.agent.analyst import AnalystAgent
    from src.llm.offline import ScriptedLLM
    _, df, prev = live.data()
    llm = ScriptedLLM([json.dumps(dict(thought="x", action="plot", args=dict(subject="lead_share", amount_cr=5))),
                       json.dumps(dict(thought="y", final="Here is the split.")),
                       "Sberbank leads at 99 of 100 points."])                 # invented figures in the explanation
    a = AnalystAgent(llm, df, prev).ask("what share of tenors does Sberbank lead at 5 cr?")
    assert a.chart and "99" not in a.chart_note and "tenor points" in a.chart_note     # falls back to the computed facts


def test_unknown_chart_subject_is_reported_to_the_agent(live):
    from src.tools.analytics_tools import build_analytics_tools
    _, df, prev = live.data()
    ok, obs = build_analytics_tools(df, prev, sink=[]).call("plot", {"subject": "radar"})
    assert not ok and "subject must be one of" in obs
