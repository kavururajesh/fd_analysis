"""Grounding check: every figure the LLM writes must come from tool output (or the question). No figure, no trust."""
import re
from typing import Iterable, List

NUM = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")


def numbers(text: str) -> List[float]:
    out = []
    for m in NUM.findall(str(text)):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _strip_markers(text: str) -> str:
    return re.sub(r"(?m)^\s*(?:[-*•]|\d{1,2}[.)])\s+", "", text)          # list numbering is not data


def unverified_numbers(answer: str, evidence: Iterable[str], tol: float = 0.006) -> List[float]:
    """Numbers in `answer` that are not in `evidence`. Small whole numbers (<=12, e.g. 'top 3', '1 year') are ignored."""
    known = set()
    for e in evidence:
        known.update(numbers(e))
    bad = []
    for n in numbers(_strip_markers(answer)):
        if float(n).is_integer() and abs(n) <= 12:
            continue
        if not any(abs(n - k) <= tol for k in known) and n not in bad:
            bad.append(n)
    return bad
