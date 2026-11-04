"""Offline stand-in for GigaChat (rule-based). It follows the same JSON protocol so the whole agent system can be
demonstrated and tested without network access. It is NOT an LLM and the UI always labels it as the rule-based engine.
ScriptedLLM replays fixed replies (for unit tests)."""
import json
import re
from typing import List

from src.agent.planner import extract_json
from src.domain.parsing import parse_days_arg


def _j(thought, action=None, args=None, final=None):
    d = {"thought": thought}
    if action:
        d.update(action=action, args=args or {})
    else:
        d["final"] = final
    return json.dumps(d)


def _history(messages):
    calls, obs = [], []
    for m in messages:
        if m["role"] == "assistant":
            a = extract_json(m["content"]) or {}
            if a.get("action"):
                calls.append((a["action"], a.get("args") or {}))
        elif m["content"].startswith("OBSERVATION: "):
            obs.append(m["content"][len("OBSERVATION: "):])
    return calls, obs


def _load(text):
    try:
        return json.loads(text)
    except Exception:
        return None


class OfflineLLM:
    is_offline = True

    def chat(self, messages, task=None, temperature=None, **kw) -> str:
        fn = getattr(self, f"_{task}", None)
        return fn(messages) if fn else "Offline engine: no rule for this task."

    # ---------------- supervisor: fixed SOP ----------------
    def _supervisor(self, messages):
        calls, obs = _history(messages)
        names = [c[0] for c in calls]
        if "list_sources" not in names:
            return _j("First I list the sources.", "list_sources")
        srcs = _load(obs[names.index("list_sources")]) or []
        if "collect_all_sources" not in names:
            return _j(f"Collect all {len(srcs)} sources at the same time.", "collect_all_sources")
        if "finalize_run" not in names:
            return _j("All sources collected; stage the run.", "finalize_run")
        if "write_review_brief" not in names:
            return _j("Write the brief for the reviewer.", "write_review_brief")
        if "finish" not in names:
            return _j("Done.", "finish", {"summary": "Run staged for human review."})
        return _j("Finished.", final="Run staged; a human reviewer must approve it.")

    # ---------------- collector: use the suggested spec ----------------
    def _collector(self, messages):
        calls, obs = _history(messages)
        names = [c[0] for c in calls]
        if "list_tables" not in names:
            return _j("See which tables the page has.", "list_tables")
        tables = (_load(obs[names.index("list_tables")]) or {}).get("tables", [])
        last_name, last_obs = (names[-1] if names else ""), (obs[-1] if obs else "")
        if last_name == "try_layout" and '"ok":true' in last_obs:
            return _j("The layout validates; accept it.", "accept_candidate")
        tried = [json.dumps(a.get("spec"), sort_keys=True) for n, a in calls if n == "try_layout"]
        for t in tables:
            spec = t.get("suggested_spec")
            if spec and json.dumps(spec, sort_keys=True) not in tried:
                return _j(f"Table {t['index']} looks like the rate table; try its suggested layout.", "try_layout", {"spec": spec})
        return _j("No table could be read.", "give_up", {"reason": "no table with a valid tenor/amount layout was found"})

    # ---------------- analyst: keyword routing + templated answer ----------------
    def _analyst(self, messages):
        calls, obs = _history(messages)
        q = next((m["content"] for m in reversed(messages) if m["role"] == "user" and m["content"].startswith("QUESTION:")), "QUESTION: ")[9:].strip()
        ql = q.lower()
        amount = self._amount(ql)
        days = self._days(ql)
        if calls and calls[-1][0] == "plot" and "chart_created" in obs[-1]:
            return _j("The chart is ready.", final=self._plot_text(_load(obs[-1]) or {}))
        if not calls:
            plot = self._plot_choice(ql, amount, days)
            if plot:
                return _j("A chart explains this best.", "plot", plot)
            if any(w in ql for w in ("stale", "current", "quality", "source", "effective")):
                return _j("Check data quality.", "data_quality")
            if any(w in ql for w in ("size", "larger", "bigger")) and days and amount is None:
                return _j("Check deposit-size sensitivity.", "size_sensitivity", {"days": days})
            if any(w in ql for w in ("changed", "moved", "yesterday", "last week", "new rate", "recent change")):
                return _j("Look at recent changes.", "recent_changes")
            if any(w in ql for w in ("score", "win", "share", "overall")):
                return _j("Use the scorecard.", "scorecard")
            if days and ("overtak" not in ql and "trail" not in ql and "lead" not in ql):
                return _j("Look up the rate.", "get_rates", {"amount_cr": amount or 5, "days": days})
            if any(w in ql for w in ("where", "trail", "lead", "overtak", "beat", "behind", "ahead", "tenor", "curve")):
                return _j("Compare across tenors.", "compare_tenors", {"amount_cr": amount or 5})
            if not any(w in ql for w in ("rate", "sber", "fd", "deposit", "bank", "hdfc", "icici", "sbi", "rbl", "idfc", "cr", "crore", "interest", "finding", "summary")):
                return _j("This is outside my scope.", final="I can only help with FD rate comparison (Sberbank vs peer banks).")
            return _j("Get the key findings.", "get_findings", {"amount_cr": amount or 5})
        return _j("Summarise the tool result.", final=self._summarise(calls[-1][0], _load(obs[-1]) or {}))

    @staticmethod
    def _plot_choice(ql, amount, days):
        graph_words = ("chart", "graph", "plot", "visual", "curve", "trend", "compare", "comparison", "versus", " vs ", "across", "over time", "history", "distribution", "share", "breakdown", "heatmap", "heat map", "where", "overtak", "trail", "behind", "ahead", "beat", "how often", "proportion", "effect", "impact", "show")
        if not any(w in ql for w in graph_words):
            return None
        a = amount or 5
        if any(w in ql for w in ("over time", "history", "trend", "moved")):
            return dict(subject="history", amount_cr=a, days=days or 90)
        if any(w in ql for w in ("pie", "share", "how often", "proportion", "percentage")):
            return dict(subject="lead_share", amount_cr=a)
        if any(w in ql for w in ("heatmap", "heat map")):
            return dict(subject="heatmap")
        if any(w in ql for w in ("size", "amount", "larger", "deposit")) and days:
            return dict(subject="deposit_size", days=days)
        if days and amount:
            return dict(subject="bank_ranking", amount_cr=a, days=days)
        if any(w in ql for w in ("bank", "peer", "banks")) and days:
            return dict(subject="bank_ranking", amount_cr=a, days=days)
        return dict(subject="rate_curve", amount_cr=a)

    @staticmethod
    def _plot_text(d):
        return (d.get("facts") or ["I have drawn the chart: " + d["chart_created"] + "."])[0]

    def _chart_note(self, messages):
        d = _load(messages[-1]["content"].split("DATA:\n", 1)[-1]) or {}
        return " ".join(d.get("facts", [])[:3]) or "The chart shows the data requested."

    @staticmethod
    def _amount(ql):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr|crore)", ql)
        return float(m.group(1)) if m else None

    @staticmethod
    def _days(ql):
        m = re.search(r"(\d+)\s*(days?|d\b|months?|m\b|years?|yrs?|y\b)", ql)
        if not m:
            return None
        try:
            return str(parse_days_arg(m.group(0)))
        except Exception:
            return None

    @staticmethod
    def _summarise(tool, d):
        if "note" in d:
            return d["note"]
        if tool == "get_rates":
            r = d["ranking"]
            top = r[0]
            sb = next((x for x in r if x["bank"].startswith("Sberbank")), None)
            lines = [f"For Rs {d['amount_cr']:g} Cr at {d['tenor']}, {top['bank']} pays the most: {top['rate_pct']:g}%."]
            if sb:
                lines.append(f"Sberbank pays {sb['rate_pct']:g}% (rank {sb['rank']} of {len(r)}).")
            lines += [f"- {x['bank']}: {x['rate_pct']:g}%" for x in r[:5]]
            return "\n".join(lines)
        if tool in ("get_findings",):
            return "\n".join("- " + f for f in d["findings"])
        if tool == "compare_tenors":
            lead = [r for r in d["rows"] if r["sber_minus_peer_pp"] >= 0]
            lose = [r for r in d["rows"] if r["sber_minus_peer_pp"] < 0]
            out = [f"At Rs {d['amount_cr']:g} Cr, Sberbank is highest at {len(lead)} of {len(d['rows'])} tenor points."]
            if lose:
                f = lose[0]
                out.append(f"First overtaken at {f['tenor']}: {f['best_peer']} pays {f['peer_pct']:g}% vs Sberbank {f['sber_pct']:g}%.")
                w = min(lose, key=lambda r: r["sber_minus_peer_pp"])
                out.append(f"Widest gap: {abs(w['sber_minus_peer_pp']):g} pp at {w['tenor']} against {w['best_peer']}.")
            return "\n".join(out)
        if tool == "size_sensitivity":
            rows = d["rows"]
            lo, hi = min(rows, key=lambda r: r["sber_pct"]), max(rows, key=lambda r: r["sber_pct"])
            return (f"At {d['tenor']}, Sberbank pays {lo['sber_pct']:g}% for Rs {lo['amount_cr']:g} Cr and {hi['sber_pct']:g}% for Rs {hi['amount_cr']:g} Cr.")
        if tool == "scorecard":
            return "Share of points where Sberbank is highest (%): " + "; ".join(
                f"{k}: " + ", ".join(f"{t} {v:g}" for t, v in row.items()) for k, row in d["sber_win_share_pct"].items())
        if tool == "data_quality":
            return "Non-current sources: " + (", ".join(d["non_current"]) or "none") + ". Sources: " + ", ".join(
                f"{s['Bank / product']} ({s['Status']}, {s['Effective date']})" for s in d["sources"])
        if tool == "recent_changes":
            return f"{d['n_changes']} rate cells changed. Biggest: " + "; ".join(
                f"{c['series']} {c['tenor_label']} {c['amt_label']}: {c['old']:g}% to {c['new']:g}%" for c in d["top"][:3] if c["old"] == c["old"] and c["new"] == c["new"])
        return "Done."

    # ---------------- plain generation tasks ----------------
    def _brief(self, messages):
        d = _load(messages[-1]["content"].split("DATA:\n", 1)[-1]) or {}
        lines = [f"- Run status: {d.get('status')}."]
        lines += [f"- {r}" for r in d.get("reasons", [])[:4]]
        lines += [f"- Warning: {w}" for w in d.get("warnings", [])[:3]]
        lines.append(f"- {d.get('n_rate_changes', 0)} rate cell(s) differ from the last published data.")
        lines.append("- All checks passed; the live dataset was replaced automatically." if d.get("status") == "published" else
                     "- Before approving: open the evidence for any healed or flagged source and confirm the rates match the bank page.")
        return "\n".join(lines)

    def _commentary(self, messages):
        d = _load(messages[-1]["content"].split("DATA:\n", 1)[-1]) or {}
        pts = d.get("key_findings", [])
        out = [f"{i}. {p}" for i, p in enumerate(pts[:5], 1)]
        if d.get("non_current_sources"):
            out.append(f"{len(out) + 1}. Caveat: non-current sources are included: " + ", ".join(d["non_current_sources"]) + ".")
        return "\n".join(out) or "No findings available."

    def _repair(self, messages):
        text = messages[-1]["content"]
        answer = text.split("ANSWER:\n", 1)[-1].split("\n\nDATA:", 1)[0]
        bad = re.search(r"UNVERIFIED:\s*(\[.*?\])", text)
        nums = [float(x) for x in json.loads(bad.group(1))] if bad else []
        keep = [ln for ln in answer.splitlines() if not any(re.search(rf"(?<![\d.]){re.escape(('%g' % n))}(?![\d])", ln) for n in nums)]
        return "\n".join(keep) or "I could not verify the figures in my first answer; please see the tables."


class ScriptedLLM:
    """Replays fixed replies in order - for tests."""
    is_offline = True

    def __init__(self, replies: List[str]):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, task=None, temperature=None, **kw):
        self.calls.append((task, messages))
        if not self.replies:
            raise RuntimeError("ScriptedLLM has no more replies")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
