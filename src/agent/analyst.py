"""Analyst agent: answers RM questions by calling analytics tools (ReAct), then checks every number it wrote."""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.agent.executor import ReActExecutor
from src.agent.guardrails import unverified_numbers
from src.agent.memory import ConversationMemory
from src.agent.state import Trace
from src.config import settings as S
from src.domain import analytics as A
from src.tools.analytics_tools import build_analytics_tools
from src.utils.helpers import dumps


@dataclass
class Answer:
    text: str
    grounded: bool = True
    unverified: List[float] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    status: str = "ok"
    chart: Optional[dict] = None
    chart_note: str = ""


class AnalystAgent:
    def __init__(self, llm, df, prev=None, memory: Optional[ConversationMemory] = None, history=None):
        self.llm, self.df, self.prev, self.history = llm, df, prev, history
        self.memory = memory or ConversationMemory()

    def ask(self, question: str, include_stale=False) -> Answer:
        trace = Trace("chat")
        charts: List[dict] = []
        tools = build_analytics_tools(self.df, self.prev, include_stale, charts, self.history)
        observations: List[str] = []
        original_call = tools.call

        def recording_call(name, args):
            ok, obs = original_call(name, args)
            if ok:
                observations.append(obs)
            return ok, obs
        tools.call = recording_call

        res = ReActExecutor(self.llm, tools, "analyst", "analyst", trace, S.ANALYST_MAX_STEPS).run(
            "QUESTION: " + question, history=self.memory.history())
        steps = [f"{e.kind}: {e.text}" for e in trace.events if e.kind in ("action", "warning", "error")]
        if res.status != "final" or not isinstance(res.output, str) or not res.output.strip():
            msg = f"I could not complete the analysis ({res.status}{': ' + res.error if res.error else ''}). Please rephrase or try again."
            return Answer(msg, grounded=False, steps=steps, status=res.status)
        text = res.output.strip()
        if not observations and not unverified_numbers(text, [question]):
            return Answer(text, steps=steps, status="no_data_needed")         # e.g. out-of-scope refusal: nothing to verify
        if not observations:
            text += "\n\n(No data tools were used for this answer - treat it as unverified.)"
            return Answer(text, grounded=False, steps=steps, status="no_tools")
        bad = unverified_numbers(text, observations + [question])
        if bad:
            fixed = self._repair(text, observations, bad)
            bad2 = unverified_numbers(fixed, observations + [question])
            steps.append(f"warning: {len(bad)} figure(s) could not be verified - answer rewritten" + ("" if not bad2 else " (still unverified)"))
            text, bad = fixed, bad2
        self.memory.add(question, text)
        chart = charts[-1] if charts else None
        return Answer(text, grounded=not bad, unverified=bad, steps=steps, chart=chart, chart_note=self._explain(chart) if chart else "")

    def _explain(self, chart) -> str:
        """2-3 plain sentences about the graph. Written by the LLM from the chart's computed facts, figures checked; falls back to the facts themselves."""
        data = dumps(dict(title=chart["title"], facts=chart["facts"], x=chart["x"][:30], series=[dict(name=s["name"], values=s["values"][:30]) for s in chart["series"]]))
        fallback = " ".join(chart["facts"][:3])
        try:
            text = self.llm.chat([{"role": "system", "content": "Explain the graph to a bank relationship manager in 2-3 short, natural sentences in simple English. Use only numbers that appear in DATA. Do not invent anything."},
                                  {"role": "user", "content": "DATA:\n" + data}], task="chart_note", temperature=0.1).strip()
        except Exception:
            return fallback
        return text if text and not unverified_numbers(text, [data]) else fallback

    def _repair(self, answer, observations, bad):
        prompt = f"ANSWER:\n{answer}\n\nDATA:\n{chr(10).join(observations)[:6000]}\n\nUNVERIFIED: {bad}"
        try:
            return self.llm.chat([{"role": "system", "content": "Rewrite the ANSWER so that every number in it appears in DATA. Remove or replace every number listed in UNVERIFIED. Keep it short and in simple English. Reply with the corrected answer text only."},
                                  {"role": "user", "content": prompt}], task="repair", temperature=0).strip() or answer
        except Exception:
            return answer


def commentary(llm, df, amount) -> Answer:
    """Written commentary for the dashboard, grounded against the facts it was given."""
    data = dumps(A.facts(df, amount))
    msgs = [{"role": "system", "content": __import__("src.prompts.system_prompts", fromlist=["x"]).get_system_prompt("commentary")},
            {"role": "user", "content": "DATA:\n" + data}]
    try:
        text = llm.chat(msgs, task="commentary", temperature=0.1).strip()
    except Exception as e:
        return Answer("AI commentary unavailable: " + str(e), grounded=False, status="llm_error")
    bad = unverified_numbers(text, [data])
    if bad:
        try:
            text = llm.chat([{"role": "system", "content": "Rewrite the ANSWER so that every number in it appears in DATA. Remove or replace every number listed in UNVERIFIED. Keep it short."},
                             {"role": "user", "content": f"ANSWER:\n{text}\n\nDATA:\n{data}\n\nUNVERIFIED: {bad}"}], task="repair", temperature=0).strip()
            bad = unverified_numbers(text, [data])
        except Exception:
            pass
    return Answer(text, grounded=not bad, unverified=bad)
