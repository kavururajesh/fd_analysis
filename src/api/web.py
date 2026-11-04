"""JSON API for the React web app (web/). All numbers come from src/domain; this layer only shapes them for the browser.
   GET  /api/meta             app state: data present, as-of date, language engine, filter options
   GET  /api/dashboard        every dashboard widget for one filter combination
   GET  /api/bank             rate curve + published rate grid for one bank
   POST /api/chat             ask the analytics assistant        DELETE /api/chat  reset the conversation
   GET  /api/ops/summary      live dataset + sources + runs waiting for review
   POST /api/ops/refresh      start the data agents (poll /api/ops/jobs/{id})
   GET  /api/ops/runs/{id}    one refresh with reasons, evidence, changes;  POST .../approve | .../reject
"""
import threading
import uuid
from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.api.routes import svc
from src.config import settings as S
from src.domain import analytics as an
from src.domain import charts as C
from src.domain.parsing import fmt_day
from src.domain.validation import diff_runs
from src.utils.helpers import clean

router = APIRouter(prefix="/api")
jobs: Dict[str, dict] = {}

STATUS_HELP = {"current": "Official corporate rates", "proxy": "Large-deposit table, not corporate-only",
               "default_table": "Default amount tab only", "stale": "Older sheet, not refreshed"}


def _records(df: pd.DataFrame, limit: Optional[int] = None):
    if df is None or df.empty:
        return []
    return clean(df.head(limit).to_dict("records") if limit else df.to_dict("records"))


def _need_data(run_id=None):
    rid, df, prev = svc.data(run_id)
    if df is None or df.empty:
        raise HTTPException(404, "no published data")
    return rid, df, prev


def _statuses(df, raw: Optional[str]) -> List[str]:
    present = [s for s in S.STATUSES if s in set(df.status)]
    picked = [s for s in (raw or "").split(",") if s in present] if raw is not None else [s for s in S.DEFAULT_STATUSES if s in present]
    return list(dict.fromkeys(["current"] + picked))


# ---------------------------------------------------------------- app state
@router.get("/meta")
def meta():
    rid, df, _ = svc.data()
    man = svc.files.manifest() or {}
    out = dict(has_data=df is not None, llm=svc.llm_label, llm_offline=bool(svc.llm.is_offline),
               source_mode=S.SOURCE_MODE, run_id=rid, updated=man.get("created", ""),
               suggestions=["Compare Sberbank with other banks at 10 cr across tenors", "What is the best rate for 10 cr for 90 days?",
                            "Show how deposit size changes the rate at 90 days", "What share of tenors does Sberbank lead at 5 cr?"],
               status_help=STATUS_HELP, sber=S.SBER, tenors=[dict(days=d, label=fmt_day(d)) for d in S.TENOR_GRID],
               as_of="", peers=[], statuses=[], default_statuses=[], rows=0, banks=0)   # always present, so the first start (no data yet) renders
    if df is not None:
        sber = df[df.series == S.SBER]
        out.update(as_of=str(sber.effective.iloc[0]) if len(sber) else "",
                   peers=sorted(set(df.series) - {S.SBER}),
                   statuses=[s for s in S.STATUSES if s in set(df.status)],
                   default_statuses=[s for s in S.DEFAULT_STATUSES if s in set(df.status)],
                   rows=int(len(df)), banks=int(df.series.nunique()))
    waiting = svc.store.list_runs(15)
    out["pending_review"] = int((waiting.status == "pending_review").sum()) if not waiting.empty else 0
    return out


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard")
def dashboard(amount: float = 10.0, days: int = 90, statuses: Optional[str] = None, banks: Optional[str] = None):
    rid, df, prev = _need_data()
    st = _statuses(df, statuses)
    peers = sorted(set(df.series) - {S.SBER})
    chosen = [b for b in banks.split(",") if b in peers] if banks else peers
    view = df[df.series.isin([S.SBER] + chosen)]

    here = an.rates_at(view, amount, days, st)
    sber_row, peers_here = here[here.name == S.SBER], here[here.name != S.SBER]
    kpis = dict(sber_rate=None, best_peer_rate=None, best_peer=None, gap=None, rank=None, ranked=len(here), led=None, points=None)
    if len(sber_row):
        kpis.update(sber_rate=float(sber_row.rate.iloc[0]), rank=int(sber_row["rank"].iloc[0]))
    if len(peers_here):
        best = peers_here.iloc[0]
        kpis.update(best_peer_rate=float(best.rate), best_peer=best["name"])
        if len(sber_row):
            kpis["gap"] = round(float(sber_row.rate.iloc[0] - best.rate), 2)
    comp = an.comparison(view, [amount], S.TENOR_GRID, st).dropna(subset=["gap"])
    if len(comp):
        kpis.update(led=int((comp.gap >= 0).sum()), points=int(len(comp)))

    hist_spec = C.history(svc.store.history(), amount, days, st)
    d = diff_runs(df, prev)
    cnt = view.groupby("series").size().sort_values(ascending=False)
    mix = view.drop_duplicates(["series", "status"]).groupby("status").size()
    pie = lambda title, idx, vals: dict(kind="pie", title=title, x=list(idx), series=[dict(name="n", values=[int(v) for v in vals])], unit="", facts=[], highlight=S.SBER)

    return clean(dict(
        run_id=rid, amount=amount, days=days, tenor_label=fmt_day(days), statuses=st, banks=chosen, kpis=kpis,
        findings=an.key_findings(view, amount, st),
        scorecard=dict(rows=list(an.scorecard(view, st).index), cols=list(an.scorecard(view, st).columns), values=an.scorecard(view, st).values.tolist()),
        charts=dict(lead_share=C.lead_share(view, amount, st), ranking=C.bank_ranking(view, amount, days, st),
                    curve=C.rate_curve(view, amount, st), heatmap=C.gap_heatmap(view, st), size=C.deposit_size(view, days, st),
                    history=hist_spec, coverage=pie("Rate points collected by bank", cnt.index, cnt.values),
                    source_types=pie("Sources by type", mix.index, mix.values)),
        table=_records(here),
        sources=_records(an.source_status(view)),
        changes=dict(total=int(len(d)), rows=_records(d, 200)),
    ))


@router.get("/bank")
def bank(name: str, amount: float = 10.0, statuses: Optional[str] = None):
    _, df, _ = _need_data()
    st = _statuses(df, statuses)
    peer = df[df.series == name]
    if peer.empty:
        raise HTTPException(404, "unknown bank")
    view = df[df.series.isin([S.SBER, name])]
    grid = peer.pivot_table(index="tenor_label", columns="amt_label", values="rate", aggfunc="max", sort=False)
    return clean(dict(name=name, curve=C.rate_curve(view, amount, st, banks=[S.SBER, name]), status=str(peer.status.iloc[0]),
                      effective=str(peer.effective.iloc[0]), rates=int(len(peer)), cols=list(grid.columns), rows=list(grid.index),
                      values=[[None if pd.isna(v) else float(v) for v in r] for r in grid.values]))


@router.get("/report")
def report(amount: float = 10.0):
    _need_data()
    return Response(svc.report_bytes(amount), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=FD_Benchmark_Report.xlsx"})


# ---------------------------------------------------------------- assistant
class ChatIn(BaseModel):
    question: str


@router.post("/chat")
def chat(body: ChatIn):
    q = body.question.strip()
    if not q:
        raise HTTPException(422, "empty question")
    a = svc.ask(q)
    return clean(dict(text=a.text, grounded=a.grounded, unverified=a.unverified, steps=a.steps, chart=a.chart, note=a.chart_note, status=a.status))


@router.delete("/chat")
def chat_reset():
    svc.memory.clear()
    return dict(ok=True)


# ---------------------------------------------------------------- data operations
def _size(p):
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


@router.get("/ops/summary")
def ops_summary():
    files, store = svc.files, svc.store
    man = files.manifest()
    runs = store.list_runs(30)
    latest = store.get_run(runs.iloc[0].run_id) if not runs.empty else None
    sources = []
    for s in (latest or {}).get("sources", []):
        dd = s["detail"] or {}
        sources.append(dict(id=s["source_id"], ok=bool(s["ok"]), method=s["method"].replace("_", " "), rates=(dd.get("metrics") or {}).get("rows", 0),
                            effective=dd.get("effective", ""), notes="; ".join((dd.get("errors") or []) + (dd.get("warnings") or []))[:200]))
    live = [f for f in sorted(files.current.rglob("*")) if f.is_file()] if files.current.exists() else []
    return clean(dict(
        manifest=man and {k: man.get(k) for k in ("run_id", "created", "rows", "sha256")},
        sources_ok=sum(1 for s in (man or {}).get("sources", []) if s.get("ok")), sources_total=len((man or {}).get("sources", [])),
        storage_kb=round((_size(files.current) + _size(files.staging)) / 1024),
        runs=_records(runs), sources=sources, mode=S.SOURCE_MODE, llm=svc.llm_label,
        files=[dict(location="current", file=str(p.relative_to(files.current)), kb=round(p.stat().st_size / 1024, 1)) for p in live]
              + [dict(location="staging", file=str(p.relative_to(files.staging)), kb=round(p.stat().st_size / 1024, 1))
                 for p in (sorted(files.staging.rglob("*")) if files.staging.exists() else []) if p.is_file()],
        running=any(j["state"] == "running" for j in jobs.values())))


@router.post("/ops/refresh")
def ops_refresh():
    if any(j["state"] == "running" for j in jobs.values()):
        raise HTTPException(409, "a refresh is already running")
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = dict(id=job_id, state="running", events=[], run_id=None, status=None, reasons=[], error=None)

    def work():
        try:
            ctx = svc.refresh(callback=lambda e: jobs[job_id]["events"].append(dict(agent=e.agent, kind=e.kind, text=str(e.text)[:400])))
            jobs[job_id].update(state="done", run_id=ctx.run_id, status=ctx.status, reasons=list(ctx.reasons or []))
        except Exception as e:
            jobs[job_id].update(state="failed", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return dict(job_id=job_id)


@router.get("/ops/jobs/{job_id}")
def ops_job(job_id: str, since: int = 0):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return clean(dict(j, events=j["events"][since:], next=len(j["events"])))


@router.get("/ops/runs/{run_id}")
def ops_run(run_id: str):
    store, files = svc.store, svc.files
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    sources = []
    for s in run["sources"]:
        dd = s["detail"] or {}
        ev = dd.get("evidence") or {}
        name = (ev.get("screenshot") or ev.get("file") or "").replace("\\", "/").split("/")[-1]
        path = files.find_evidence(run_id, name) if name else None
        sources.append(dict(id=s["source_id"], ok=bool(s["ok"]), method=s["method"].replace("_", " "), rates=(dd.get("metrics") or {}).get("rows", 0),
                            effective=dd.get("effective", ""), errors=dd.get("errors") or [], warnings=dd.get("warnings") or [],
                            url=ev.get("url", ""), retrieved=ev.get("retrieved_at", ""), sha=str(ev.get("sha256", ""))[:16],
                            image=bool(path and path.suffix == ".png"), file=name if path else "",
                            spec=dd.get("spec") if s["method"] not in ("spec_yaml", "spec_memory") else None))
    changes = []
    if run["status"] in ("pending_review", "published"):
        ids = store.published_ids()
        staged = store.load_rates(run_id)
        base = store.load_rates(ids[1]) if run["status"] == "published" and len(ids) > 1 else (store.load_rates(ids[0]) if ids and run["status"] != "published" else None)
        changes = _records(diff_runs(staged, base), 200)
    return clean(dict(run_id=run_id, status=run["status"], created=run["created"], reasons=run["reasons"] or [], brief=run.get("brief") or "",
                      decided_by=run.get("decided_by"), sources=sources, changes=changes))


@router.get("/ops/evidence/{run_id}/{name}")
def ops_evidence(run_id: str, name: str):
    path = svc.files.find_evidence(run_id, name)
    if not path:
        raise HTTPException(404, "no such evidence")
    return FileResponse(path)


@router.get("/ops/runs/{run_id}/traces")
def ops_traces(run_id: str):
    return _records(svc.store.get_traces(run_id))


class Decision(BaseModel):
    by: str = "reviewer"


@router.post("/ops/runs/{run_id}/approve")
def ops_approve(run_id: str, body: Decision = Decision()):
    try:
        svc.approve(run_id, body.by)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return dict(run_id=run_id, status="published")


@router.post("/ops/runs/{run_id}/reject")
def ops_reject(run_id: str, body: Decision = Decision()):
    try:
        svc.reject(run_id, body.by)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return dict(run_id=run_id, status="rejected")
