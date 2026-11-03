"""Tool registry: name + description + callable. Errors become observations the LLM can react to."""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

from src.utils.helpers import dumps


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    params: Dict[str, str] = field(default_factory=dict)         # arg name -> short description
    required: List[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name, description, fn, params=None, required=None):
        self._tools[name] = Tool(name, description, fn, params or {}, required if required is not None else list((params or {}).keys()))
        return self

    def __contains__(self, name):
        return name in self._tools

    def names(self):
        return list(self._tools)

    def describe(self) -> str:
        lines = []
        for t in self._tools.values():
            args = ", ".join(f"{k}: {v}" for k, v in t.params.items()) or "no arguments"
            lines.append(f"- {t.name}({args}) - {t.description}")
        return "\n".join(lines)

    def call(self, name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        tool = self._tools.get(name)
        if tool is None:
            return False, f"ERROR: unknown tool '{name}'. Available tools: {', '.join(self._tools)}"
        missing = [r for r in tool.required if r not in args]
        if missing:
            return False, f"ERROR: tool '{name}' needs argument(s): {', '.join(missing)}. Usage: {name}({', '.join(tool.params)})"
        unknown = [k for k in args if k not in tool.params]
        if unknown:
            return False, f"ERROR: tool '{name}' has no argument(s) {unknown}. Usage: {name}({', '.join(tool.params)})"
        try:
            result = tool.fn(**args)
        except Exception as e:                                   # tool errors are information for the agent
            return False, f"ERROR: {type(e).__name__}: {e}"
        return True, result if isinstance(result, str) else dumps(result)
