import json

from src.agent.executor import ReActExecutor
from src.agent.guardrails import unverified_numbers
from src.agent.planner import ParseError, parse_action
from src.agent.state import Trace
from src.llm.offline import ScriptedLLM
from src.tools.registry import ToolRegistry
import pytest


def reg():
    r = ToolRegistry()
    r.register("add", "adds", lambda a, b: int(a) + int(b), {"a": "n", "b": "n"})
    r.register("boom", "fails", lambda: 1 / 0, {})
    return r


def run(replies, **kw):
    llm = ScriptedLLM(replies)
    res = ReActExecutor(llm, reg(), "default", "t", Trace(), max_steps=kw.get("max_steps", 5)).run("go")
    return res, llm


def J(**d):
    return json.dumps(d)


def test_tool_then_final():
    res, _ = run([J(thought="x", action="add", args={"a": 1, "b": 2}), J(thought="y", final="3")])
    assert res.status == "final" and res.output == "3"


def test_invalid_json_recovers_then_gives_up():
    res, _ = run(["not json", J(thought="x", final="ok")])
    assert res.status == "final"
    res, _ = run(["bad", "bad", "bad"])
    assert res.status == "parse_error"


def test_unknown_tool_and_bad_args_are_feedback_not_crashes():
    res, llm = run([J(thought="x", action="nope", args={}), J(thought="x", action="add", args={"a": 1}), J(thought="x", action="boom", args={}), J(thought="d", final="done")])
    assert res.status == "final"
    obs = [m["content"] for _, msgs in llm.calls for m in msgs if m["content"].startswith("OBSERVATION")]
    assert any("unknown tool" in o for o in obs) and any("needs argument" in o for o in obs) and any("ZeroDivisionError" in o for o in obs)


def test_repeat_call_blocked_and_step_limit():
    same = J(thought="x", action="add", args={"a": 1, "b": 1})
    res, llm = run([same, same, same, J(thought="d", final="ok")])
    assert any("already called" in m["content"] for _, msgs in llm.calls for m in msgs)
    res, _ = run([J(thought="x", action="add", args={"a": i, "b": 1}) for i in range(10)], max_steps=3)
    assert res.status == "max_steps"


def test_llm_error_is_reported():
    from src.llm.client import LLMError
    res, _ = run([LLMError("down")])
    assert res.status == "llm_error"


def test_planner_formats():
    assert parse_action('```json\n{"thought":"a","action":"t","args":{}}\n```').name == "t"
    assert parse_action("Sure! {'thought': 'a', 'final': 'x'}").final == "x"
    with pytest.raises(ParseError):
        parse_action("no json here")


def test_grounding():
    ev = ["Sberbank 7.25 and peer 7.10 gap 0.15 at 90"]
    assert unverified_numbers("1. Sber 7.25% vs 7.10%, gap 0.15 at 90 days", ev) == []
    assert unverified_numbers("Sber pays 9.99%", ev) == [9.99]
