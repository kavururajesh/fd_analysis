"""Turn bank labels such as '6m1d–9m' or '₹3Cr–<₹10Cr' into numeric ranges. Strict: anything that is not a
tenor / amount label raises ValueError, so a wrongly chosen table can never slip through.

Convention: 1 month = 30 days; 12/24/36/60 months = 1/2/3/5 years of 365 days.
"""
import re

from src.config.settings import EPS, NO_LIMIT

_TENOR_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:years?|yrs?|y|months?|m|days?|d)(?![A-Za-z])", re.I)
_AMOUNT_RE = re.compile(r"₹|(?<![A-Za-z])(?:crores?|cr)(?![A-Za-z])|(?<![A-Za-z])rs\.?(?![A-Za-z])", re.I)
DEFAULT_AMOUNT_LABEL = "Default/popular"


def is_amount_label(text):
    text = str(text).strip()
    if re.fullmatch(r"default(/popular)?", text, re.I):
        return True
    return bool(re.search(r"\d", text) and _AMOUNT_RE.search(text))


def is_tenor_label(text):
    text = str(text)
    return bool(re.search(r"\d", text) and _TENOR_RE.search(text) and not _AMOUNT_RE.search(text))


def _days(token, default_unit="d"):
    total = 0.0
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|y|months?|m|days?|d)?", token.lower()):
        n, unit = float(n), (unit or default_unit)[0]
        if unit == "d":
            total += n
        elif unit == "y":
            total += n * 365
        else:
            total += n / 12 * 365 if n % 12 == 0 else n * 30
    return int(round(total))


def parse_tenor(label):
    """'31-90 days' -> (31, 90);  '1-<2 years' -> (365, 729);  both ends inclusive."""
    if not is_tenor_label(label):
        raise ValueError(f"not a tenor label: {label!r}")
    parts = re.split(r"\s*[–—-]\s*", re.sub(r"\s+to\s+", "–", str(label).strip(), flags=re.I))
    if len(parts) == 1:
        d = _days(parts[0])
        return d, d
    first, last = parts[0], parts[-1]
    letters = re.findall(r"[a-z]+", last.lower())
    unit = letters[-1][0] if letters else "d"
    lo, hi = _days(first, unit), _days(last, unit)
    return lo, (hi - 1 if "<" in last else hi)


def parse_amount(label):
    """Deposit slab in Rs crore -> (low, high) used as low <= amount < high.
    '<3' = [0,3)  '3-<10' = [3,10)  '3-3.5' = [3,3.5]  '>4-5.6' / 'Above 25-60' = (lo,hi]  '100+' = [100,inf)"""
    if not is_amount_label(label):
        raise ValueError(f"not an amount label: {label!r}")
    text = str(label).strip()
    if re.fullmatch(r"default(/popular)?", text, re.I):
        return 0.0, NO_LIMIT
    text = re.sub(r"\s+to\s+", "–", text, flags=re.I)
    text = re.sub(r"^(less than|below|under)\s*", "<", text, flags=re.I)
    text = re.sub(r"\s*(and above|& above|and more|or more|and over)\s*$", "+", text, flags=re.I)
    open_left = text.startswith(">") or text.lower().startswith("above")
    s = re.sub(r"[₹\s]|crores?|cr|rs\.?|above", "", text, flags=re.I).lstrip(">")
    if s.startswith("<"):
        return 0.0, float(s[1:])
    if s.endswith("+"):
        return float(s[:-1]), NO_LIMIT
    if re.search(r"[–—-]", s):
        a, b = re.split(r"[–—-]", s)
        lo, hi = float(a), float(b.lstrip("<"))
        if "<" in b:
            return lo, hi
        return (lo + EPS, hi + EPS) if open_left else (lo, hi + EPS)
    v = float(s)
    return (v + EPS if open_left else v), NO_LIMIT


def parse_days_arg(value):
    """Accept 60, '60', '90d', '6m', '1y', '2 years' -> days (for tool arguments written by an LLM)."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if is_tenor_label(text):
        return _days(text)
    raise ValueError(f"cannot read tenor from {value!r}")


def fmt_day(d):
    d = int(d)
    return f"{d // 365}y" if d >= 365 and d % 365 == 0 else f"{d}d"
