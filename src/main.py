"""Command line: python -m src.main <command>
  ui              start the dashboard (Streamlit)
  web             start the web app (React) at http://localhost:8000
  api             start the REST API (same server)
  refresh         run the data agents once (prints the live trace)
  approve RUN_ID  approve a staged run
  ask "question"  ask the analyst
  check SOURCE_ID open one source and show its tables (use before enabling a live source)
  serve-fixtures  serve the local bank-page snapshots
  simulate-drift on|off  testing aid: change the layout of the local Sberbank snapshot
  eval            run the offline evaluations"""
import subprocess
import sys

from src.config import settings as S


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "ui":
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(S.ROOT / "ui" / "app.py"), *rest])
    if cmd in ("web", "api"):
        import uvicorn
        from src.api.routes import create_app
        if cmd == "web":
            import threading, webbrowser
            threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
        uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="warning")
        return 0
    if cmd == "serve-fixtures":
        from src.localsite import fixture_server
        import threading
        print(fixture_server.start(), "- Ctrl+C to stop")
        threading.Event().wait()
    if cmd == "simulate-drift":
        from src.localsite import fixture_server
        fixture_server.set_drift(bool(rest) and rest[0] == "on")
        print("layout change", "ON" if fixture_server.drift_enabled() else "OFF")
        return 0
    if cmd == "eval":
        from evals import evaluate_agent, evaluate_extraction  # noqa
        return subprocess.call([sys.executable, "-m", "evals.evaluate_agent"])
    from src.service import FDService
    svc = FDService()
    if cmd == "refresh":
        print("LLM:", svc.llm_label, "| mode:", S.SOURCE_MODE)
        ctx = svc.refresh(callback=lambda e: print(f"[{e.agent}] {e.kind}: {e.text[:200]}"))
        print(f"\nRun {ctx.run_id}: {ctx.status}\n{ctx.brief}")
        return 2 if ctx.status == "blocked" else 0                  # non-zero exit lets a scheduler flag a failed refresh
    if cmd == "approve" and rest:
        svc.approve(rest[0])
        print("published", rest[0])
        return 0
    if cmd == "ask" and rest:
        a = svc.ask(" ".join(rest))
        print(a.text, "\n\n[grounded]" if a.grounded else f"\n\n[UNVERIFIED figures: {a.unverified}]")
        return 0
    if cmd == "check" and rest:
        from src.domain.layout import preview, suggest_layout
        from src.tools.acquire import SourceSession
        from src.tools.browser import BrowserManager
        src = next((s for s in svc.sources() if s.id == rest[0]), None)
        if not src:
            sys.exit(f"unknown source id. Available: {[s.id for s in svc.sources()]}")
        b = BrowserManager()
        try:
            sess = SourceSession(src, b)
            print(sess.open())
            for i, t in enumerate(sess.tables):
                s = suggest_layout(t)
                print(f"\n--- table {i} shape={t.shape} suggested={'yes (score ' + str(s['_score']) + ')' if s else 'no'}")
                for row in preview(t, 4, 6):
                    print("   ", row)
            sess.close()
        finally:
            b.close()
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
