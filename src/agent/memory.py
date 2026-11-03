"""Short-term conversation memory for the analyst chat (last few question/answer pairs)."""
from typing import Dict, List


class ConversationMemory:
    def __init__(self, max_turns: int = 4):
        self.max_turns, self.turns = max_turns, []

    def add(self, question: str, answer: str):
        self.turns.append((question, answer))
        self.turns = self.turns[-self.max_turns:]

    def history(self) -> List[Dict[str, str]]:
        msgs = []
        for q, a in self.turns:
            msgs += [{"role": "user", "content": "QUESTION: " + q}, {"role": "assistant", "content": '{"thought": "answered", "final": ' + _js(a) + "}"}]
        return msgs

    def clear(self):
        self.turns = []


def _js(s):
    import json
    return json.dumps(s, ensure_ascii=False)
