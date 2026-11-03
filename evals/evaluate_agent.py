"""Agent evaluation: (1) data agents extract the local snapshots exactly, (2) the analyst answers the cases in cases.yaml correctly and grounded.
Uses LLM_MODE from .env (offline engine; set LLM_MODE=gigachat to evaluate the real model)."""
import sys
import tempfile
from pathlib import Path

import yaml

from evals.evaluate_extraction import evaluate
from src.memory.store import Store
from src.service import FDService


def main():
    with tempfile.TemporaryDirectory() as d:
        svc = FDService(Store(Path(d) / "eval.db"))
        print("LLM:", svc.llm_label)
        ctx = svc.refresh()
        rows = evaluate(ctx.df)
        ext_ok = sum(r["exact"] for r in rows)
        print(f"extraction: {ext_ok}/{len(rows)} sources exact | run status {ctx.status} | healed: {[k for k, v in ctx.results.items() if v.healed]}")
        svc.approve(ctx.run_id)
        cases = yaml.safe_load((Path(__file__).parent / "cases.yaml").read_text(encoding="utf-8"))
        passed = 0
        for c in cases:
            a = svc.ask(c["q"])
            missing = [m for m in c["must_contain"] if m.lower() not in a.text.lower()]
            ok = not missing and (a.grounded or not c.get("grounded", True))
            passed += ok
            print(f"{'PASS' if ok else 'FAIL'}  {c['q']}" + ("" if ok else f"\n      missing={missing} grounded={a.grounded} unverified={a.unverified}\n      answer={a.text[:200]!r}"))
        print(f"analyst: {passed}/{len(cases)} cases passed")
        return 0 if ext_ok == len(rows) and passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
