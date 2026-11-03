"""Planner = reads the LLM's next decision. The LLM must answer with one JSON object (see prompts.PROTOCOL).
GigaChat sometimes adds prose or code fences, so extraction is tolerant."""
import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ParseError(ValueError):
    pass


@dataclass
class Action:
    thought: str = ""
    name: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    final: Any = None
    raw: str = ""


def extract_json(text: str):
    """First balanced {...} object in the text (handles ```json fences and surrounding prose)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start:i + 1]
                    for loader in (json.loads, ast.literal_eval):
                        try:
                            obj = loader(chunk)
                            if isinstance(obj, dict):
                                return obj
                        except Exception:
                            pass
                    break
        start = text.find("{", start + 1)
    return None


def parse_action(text: str) -> Action:
    obj = extract_json(text)
    if obj is None:
        raise ParseError("no JSON object found")
    thought = str(obj.get("thought", ""))
    for key in ("final", "final_answer", "answer"):
        if key in obj:
            return Action(thought=thought, final=obj[key], raw=text)
    name = obj.get("action") or obj.get("tool") or obj.get("name")
    if not name or not isinstance(name, str):
        raise ParseError("JSON has neither 'action' nor 'final'")
    args = obj.get("args", obj.get("arguments", obj.get("input", obj.get("action_input", {}))))
    if isinstance(args, str):
        args = extract_json(args) or {}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ParseError("'args' must be a JSON object")
    return Action(thought=thought, name=name.strip(), args=args, raw=text)
