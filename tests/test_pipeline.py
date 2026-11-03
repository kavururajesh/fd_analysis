"""End-to-end with a real browser against the local demo pages ."""
import pytest

from evals.evaluate_extraction import evaluate
from src.agent.state import Trace
from src.agent.supervisor import Supervisor
from src.domain import analytics as A
from src.llm.offline import OfflineLLM
from src.service import FDService
from src.tools.sources import load_sources


def stage(store, browser, fixture_site, files, llm=None):
    sup = Supervisor(llm or OfflineLLM(), store, browser, Trace("t", store), files)
    return sup.run("run1", load_sources(), "local")


def test_full_run_extracts_everything_exactly(store, browser, fixture_site, files):
    ctx = stage(store, browser, fixture_site, files)
    assert ctx.status == "pending_review"                       # first run + calibrated layouts -> needs a human
    assert all(r.ok for r in ctx.results.values())
    rows = evaluate(ctx.df)
    assert all(r["exact"] for r in rows), [r for r in rows if not r["exact"]]
    assert {r.method for r in ctx.results.values()} >= {"spec_yaml", "agent_healed"}
    assert store.get_run("run1")["status"] == "pending_review"


def test_approval_gate_and_spec_memory(store, browser, fixture_site, files):
    stage(store, browser, fixture_site, files)
    assert store.get_spec("sbi_bulk") is None                   # healed specs are not trusted before approval
    svc = FDService(store, OfflineLLM(), files)
    svc.approve("run1")
    assert store.published_ids() == ["run1"] and store.get_spec("sbi_bulk")
    sup = Supervisor(OfflineLLM(), store, browser, Trace("run2", store), files)
    ctx = sup.run("run2", load_sources(), "local")
    assert {ctx.results[s].method for s in ("sbi_bulk", "idfc_callable")} == {"spec_memory"}      # no LLM needed any more


def test_layout_drift_is_healed_and_flagged(store, browser, fixture_site, files):
    from src.localsite import fixture_server
    stage(store, browser, fixture_site, files)
    FDService(store, OfflineLLM(), files).approve("run1")
    fixture_server.set_drift(True)
    try:
        ctx = Supervisor(OfflineLLM(), store, browser, Trace("run2", store), files).run("run2", load_sources(), "local")
    finally:
        fixture_server.set_drift(False)
    r = ctx.results["sber_corporate"]
    assert r.ok and r.method == "agent_healed" and r.healed
    assert any("layout" in x for x in ctx.reasons)
    assert not [x for x in evaluate(ctx.df) if x["source"] == "sber_corporate" and not x["exact"]]


def test_failed_source_is_carried_forward_and_sber_failure_blocks(store, browser, fixture_site, files):
    stage(store, browser, fixture_site, files)
    FDService(store, OfflineLLM(), files).approve("run1")
    srcs = load_sources()
    for s in srcs:
        if s.id == "rbl_callable":
            s.url = fixture_site + "/does-not-exist.pdf"
    ctx = Supervisor(OfflineLLM(), store, browser, Trace("run2", store), files).run("run2", srcs, "local")
    assert ctx.status == "pending_review" and "rbl_callable" in ctx.carried
    assert (ctx.df[ctx.df.source_id == "rbl_callable"].status == "stale").all()
    srcs = load_sources()
    for s in srcs:
        if s.id == "sber_corporate":
            s.url = fixture_site + "/missing.html"
    ctx = Supervisor(OfflineLLM(), store, browser, Trace("run3", store), files).run("run3", srcs, "local")
    assert ctx.status == "blocked"
    with pytest.raises(ValueError):
        FDService(store, OfflineLLM(), files).approve("run3")


def test_agent_falls_back_when_llm_is_down(store, browser, fixture_site, files):
    from src.llm.client import LLMError
    from src.llm.offline import ScriptedLLM
    ctx = stage(store, browser, fixture_site, files, ScriptedLLM([LLMError("down")] * 60))
    assert all(r.ok for r in ctx.results.values())               # heuristic safety net + SOP in code
    assert ctx.brief and ctx.status == "pending_review"


def test_analyst_answers_are_grounded(store, browser, fixture_site, files):
    stage(store, browser, fixture_site, files)
    svc = FDService(store, OfflineLLM(), files)
    svc.approve("run1")
    a = svc.ask("What is the best rate for 10 cr for 90 days?")
    assert a.grounded and "7%" in a.text and "Sberbank" in a.text
    off = svc.ask("What is the weather?")
    assert "only help with FD" in off.text
    assert len(svc.report_bytes(10)) > 5000
    assert A.key_findings(svc.data()[1], 10)


def test_hallucinated_numbers_are_caught(store, browser, fixture_site, files):
    import json
    from src.agent.analyst import AnalystAgent
    from src.llm.offline import ScriptedLLM
    stage(store, browser, fixture_site, files)
    FDService(store, OfflineLLM(), files).approve("run1")
    _, df, prev = FDService(store, OfflineLLM(), files).data()
    J = json.dumps
    llm = ScriptedLLM([J(dict(thought="x", action="get_rates", args={"amount_cr": 10, "days": 90})),
                       J(dict(thought="y", final="Sberbank pays 12.34% for 10 Cr at 90 days.\nRBL noncallable pays 5.65%.")),
                       "RBL noncallable pays 5.65%."])
    a = AnalystAgent(llm, df, prev).ask("rate for 10 cr 90 days")
    assert a.grounded and "12.34" not in a.text
