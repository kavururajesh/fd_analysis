"""ReAct executor: the generic think -> act -> observe loop used by every agent.
Guards: step limit, invalid-JSON recovery, unknown-tool feedback, repeated-call detection, early stop condition."""
from collections import Counter
from typing import Callable, Dict, List, Optional

from src.agent.planner import ParseError, parse_action
from src.agent.state import AgentResult, Trace
from src.config import settings as S
from src.llm.client import LLMError
from src.prompts.system_prompts import react_system_prompt
from src.tools.registry import ToolRegistry
from src.utils.helpers import truncate

MAX_BAD_FORMAT = 3
OBS_LIMIT = 3500


class ReActExecutor:
    def __init__(self, llm, registry: ToolRegistry, task: str, agent_name: str, trace: Trace, max_steps: int = 10,
                 temperature: Optional[float] = None, require_tool: bool = False):
        self.require_tool = require_tool          # reject a final answer given before any successful tool call (stops made-up numbers)
        self.llm, self.registry, self.task = llm, registry, task
        self.agent, self.trace, self.max_steps, self.temperature = agent_name, trace, max_steps, temperature

    def run(self, goal: str, history: Optional[List[Dict[str, str]]] = None,
            stop_when: Callable[[], bool] = lambda: False) -> AgentResult:
        messages = [{"role": "system", "content": react_system_prompt(self.task, self.registry.describe())}]
        messages += list(history or [])
        messages.append({"role": "user", "content": goal})
        calls, bad_format, tool_ok, nudges = Counter(), 0, 0, 0
        for step in range(1, self.max_steps + 1):
            try:
                text = self.llm.chat(messages, task=self.task, temperature=self.temperature)
            except LLMError as e:
                self.trace.emit(self.agent, "error", f"LLM error: {e}")
                return AgentResult("llm_error", steps=step - 1, error=str(e))
            try:
                action = parse_action(text)
            except ParseError as e:
                bad_format += 1
                self.trace.emit(self.agent, "warning", f"Invalid reply format ({e}); asking the model to retry")
                if bad_format >= MAX_BAD_FORMAT:
                    return AgentResult("parse_error", steps=step, error="the model did not follow the JSON protocol")
                messages += [{"role": "assistant", "content": truncate(text, 800)},
                             {"role": "user", "content": 'Invalid format. Reply with ONE JSON object only: {"thought": "...", "action": "<tool>", "args": {...}} or {"thought": "...", "final": ...}'}]
                continue
            if action.thought:
                self.trace.emit(self.agent, "thought", action.thought)
            if action.final is not None and self.require_tool and not tool_ok and nudges < 2:
                nudges += 1
                self.trace.emit(self.agent, "warning", "Answer given without using any data tool; asking the model to use a tool first")
                messages += [{"role": "assistant", "content": truncate(text, 800)},
                             {"role": "user", "content": 'You answered without using a tool, so those numbers are not verified. Call a data tool now (for example a comparison or lookup tool) and answer only from its OBSERVATION. Reply with ONE JSON object: {"thought": "...", "action": "<tool>", "args": {...}}. Only if the question is not about FD rates, reply {"thought": "...", "final": "I can only help with FD rate comparison."}'}]
                continue
            if action.final is not None:
                self.trace.emit(self.agent, "final", action.final if isinstance(action.final, str) else str(action.final))
                return AgentResult("final", output=action.final, steps=step)
            signature = (action.name, str(sorted(action.args.items())))
            calls[signature] += 1
            if calls[signature] > 2:
                obs = f"ERROR: you already called {action.name} with these arguments twice. Choose a different action or give the final answer."
                ok = False
            else:
                self.trace.emit(self.agent, "action", f"{action.name}({', '.join(f'{k}={v}' for k, v in action.args.items())})", action.args)
                ok, obs = self.registry.call(action.name, action.args)
                tool_ok += 1 if ok else 0
            self.trace.emit(self.agent, "observation" if ok else "warning", truncate(obs, 600))
            messages += [{"role": "assistant", "content": truncate(text, 1500)},
                         {"role": "user", "content": "OBSERVATION: " + truncate(obs, OBS_LIMIT)}]
            if stop_when():
                return AgentResult("done", steps=step)
        self.trace.emit(self.agent, "warning", f"Step limit ({self.max_steps}) reached")
        return AgentResult("max_steps", steps=self.max_steps)
