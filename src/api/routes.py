"""FastAPI layer (optional - the UI calls the service directly). Run: python -m src.main api"""
import threading
import uuid
from typing import Dict

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import Response

from src.api.schemas import AskRequest, AskResponse, DecisionRequest
from src.config import settings as S
from src.domain import analytics as A
from src.service import FDService
from src.utils.helpers import clean

router = APIRouter()
svc = FDService()
jobs: Dict[str, dict] = {}


@router.get("/health")
def health():
    return dict(status="ok", llm=svc.llm_label, source_mode=S.SOURCE_MODE, published_runs=len(svc.store.published_ids()))


@router.post("/refresh")
def refresh():
    """Start a refresh in the background. Poll GET /jobs/{id}."""
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = dict(state="running", events=[], run_id=None, error=None)

    def work():
        try:
            ctx = svc.refresh(callback=lambda e: jobs[job_id]["events"].append(f"[{e.agent}] {e.kind}: {e.text[:200]}"))
            jobs[job_id].update(state="done", run_id=ctx.run_id, status=ctx.status, reasons=ctx.reasons)
        except Exception as e:
            jobs[job_id].update(state="failed", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return dict(job_id=job_id)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "unknown job")
    return jobs[job_id]


@router.get("/runs")
def runs():
    return svc.store.list_runs(30).to_dict("records")


@router.get("/runs/{run_id}")
def run(run_id: str):
    r = svc.store.get_run(run_id)
    if not r:
        raise HTTPException(404, "unknown run")
    return clean(r)


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, body: DecisionRequest = DecisionRequest()):
    try:
        svc.approve(run_id, body.by)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return dict(run_id=run_id, status="published")


@router.post("/runs/{run_id}/reject")
def reject(run_id: str, body: DecisionRequest = DecisionRequest()):
    try:
        svc.reject(run_id, body.by)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return dict(run_id=run_id, status="rejected")


@router.get("/rates")
def rates(amount_cr: float, days: int):
    _, df, _ = svc.data()
    if df is None:
        raise HTTPException(404, "no published data")
    return A.rates_at(df, amount_cr, days).to_dict("records")


@router.get("/findings")
def findings(amount_cr: float = 10):
    _, df, _ = svc.data()
    if df is None:
        raise HTTPException(404, "no published data")
    return dict(amount_cr=amount_cr, findings=A.key_findings(df, amount_cr))


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    a = svc.ask(req.question, req.run_id, req.include_stale)
    return AskResponse(answer=a.text, grounded=a.grounded, unverified=a.unverified, status=a.status)


@router.get("/report")
def report(amount_cr: float = 10):
    data = svc.report_bytes(amount_cr)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=FD_benchmark.xlsx"})


def create_app() -> FastAPI:
    app = FastAPI(title="Corporate Deposits Analytics", version="1.0")
    app.include_router(router)
    from src.api.web import router as web_router                 # JSON endpoints for the React app
    app.include_router(web_router)
    dist = S.ROOT / "web" / "dist"                               # built React app (no Node needed on the laptop)
    if (dist / "index.html").exists():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (dist / path).resolve()
            return FileResponse(f if path and f.is_file() and dist in f.parents else dist / "index.html")
    return app
