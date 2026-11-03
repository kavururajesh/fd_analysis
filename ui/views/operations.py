"""Data operations: refresh, live agent activity, review of flagged runs, source health, file management, audit."""
import pathlib
import threading

import pandas as pd
import streamlit as st

from src.config import settings as S
from src.domain import analytics as an
from src.domain.validation import diff_runs
from ui import theme as T


def start_refresh(svc):
    job = dict(events=[], done=False, error=None, ctx=None)

    def work():
        try:
            job["ctx"] = svc.refresh(callback=lambda e: job["events"].append(dict(agent=e.agent, kind=e.kind, text=e.text)))
        except Exception as e:
            job["error"] = str(e)
        finally:
            job["done"] = True
    threading.Thread(target=work, daemon=True).start()
    st.session_state["job"] = job


def is_running():
    j = st.session_state.get("job")
    return bool(j and not j["done"])


def _size(p: pathlib.Path):
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def render(svc):
    store, files = svc.store, svc.files
    running = is_running()

    top = st.columns([1, 1, 3])
    if top[0].button("Refresh data now", disabled=running, width="stretch"):
        start_refresh(svc)
        st.rerun()
    st.caption("The data agents read every configured source, validate the numbers and replace the live dataset when everything checks out. "
               "Flagged results wait here for a reviewer.")

    @st.fragment(run_every=1.0 if running else None)
    def live():
        j = st.session_state.get("job")
        if not j:
            return
        state = "running…" if not j["done"] else ("failed: " + j["error"] if j["error"] else "finished")
        st.markdown(f"**Agent activity** — {state}")
        if j["events"]:
            st.markdown(T.trace_html(j["events"]), unsafe_allow_html=True)
        if j["done"] and st.session_state.get("job_seen") is not j:
            st.session_state["job_seen"] = j
            st.rerun()
    live()

    man = files.manifest()
    c1, c2, c3, c4 = st.columns(4)
    T.kpi(c1, "Live dataset", f"{man['rows']:,} rates" if man else "none", f"run {man['run_id']}" if man else "run the first refresh")
    T.kpi(c2, "Last updated", (man["created"][5:16].replace("T", ", ") if man else "–"), "dataset written & verified")
    ok = sum(1 for s in (man or {}).get("sources", []) if s.get("ok"))
    T.kpi(c3, "Sources read", f"{ok} of {len((man or {}).get('sources', []))}" if man else "–", "in the live dataset")
    T.kpi(c4, "Storage used", f"{(_size(files.current) + _size(files.staging)) / 1024:,.0f} KB", "data/current + data/staging")
    st.write("")

    runs = store.list_runs(15)
    waiting = runs[runs.status.isin(["pending_review"])] if not runs.empty else runs
    if len(waiting):
        st.warning(f"{len(waiting)} refresh(es) need review before they replace the live data.")
    tabs = st.tabs(["Review", "Source health", "Files", "Audit"])

    with tabs[0]:
        if runs.empty:
            st.info("No refresh has run yet.")
        else:
            chosen = st.selectbox("Refresh run", runs.run_id.tolist(), format_func=lambda r: f"{r}  ·  {runs.set_index('run_id').loc[r, 'status'].replace('_', ' ')}")
            review_panel(svc, store.get_run(chosen))

    with tabs[1]:
        latest = store.get_run(runs.iloc[0].run_id) if not runs.empty else None
        if latest:
            rows = []
            for s in latest["sources"]:
                d = s["detail"] or {}
                rows.append({"Source": s["source_id"], "Status": "✔ read" if s["ok"] else "✖ failed", "Method": s["method"].replace("_", " "),
                             "Rates": (d.get("metrics") or {}).get("rows", 0), "Effective date": d.get("effective", ""),
                             "Notes": "; ".join((d.get("errors") or []) + (d.get("warnings") or []))[:140]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with tabs[2]:
        st.markdown("##### Dataset files")
        st.caption("New data is written to `data/staging`, verified (checksum, row count, validation) and only then swapped in as `data/current`. "
                   "The previous files are deleted after the swap succeeds. If anything fails, the existing data stays live.")
        rows = [dict(Location="current", File=str(p.relative_to(files.current)), **{"Size (KB)": round(p.stat().st_size / 1024, 1)}) for p in sorted(files.current.rglob("*")) if p.is_file()] if files.current.exists() else []
        rows += [dict(Location="staging", File=str(p.relative_to(files.staging)), **{"Size (KB)": round(p.stat().st_size / 1024, 1)}) for p in sorted(files.staging.rglob("*")) if p.is_file()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch") if rows else st.info("No files yet.")
        if man:
            st.json({k: man[k] for k in ("run_id", "created", "rows", "sha256")}, expanded=False)

    with tabs[3]:
        st.dataframe(store.list_runs(30), hide_index=True, width="stretch")
        specs = store.list_specs(30)
        st.markdown("##### Table layouts (approved / waiting)")
        st.dataframe(specs.assign(approved=specs.approved.map({1: "approved", 0: "waiting"})), hide_index=True, width="stretch")
        if not runs.empty:
            rid = st.selectbox("Agent log of run", runs.run_id.tolist(), key="trace_run")
            st.dataframe(store.get_traces(rid), hide_index=True, width="stretch", height=320)


def review_panel(svc, run):
    store, files = svc.store, svc.files
    rid = run["run_id"]
    kind = {"pending_review": "warn", "blocked": "bad", "published": "ok", "rejected": "grey", "superseded": "grey"}.get(run["status"], "grey")
    label = {"published": "live", "pending_review": "needs review"}.get(run["status"], run["status"].replace("_", " "))
    st.markdown(f"**Run {rid}** " + T.pill(label, kind), unsafe_allow_html=True)
    for r in run["reasons"] or []:
        st.markdown(f"- {r}")
    if run.get("brief"):
        with st.container(border=True):
            st.markdown("**Review brief**")
            st.markdown(run["brief"])
    with st.expander("Evidence (what the agent saw)"):
        for s in run["sources"]:
            ev = (s["detail"] or {}).get("evidence") or {}
            st.markdown(f"**{s['source_id']}** — {ev.get('url', '')}  \nretrieved {ev.get('retrieved_at', '')} · sha256 `{str(ev.get('sha256', ''))[:16]}…`")
            name = pathlib.Path(ev.get("screenshot") or ev.get("file") or "").name
            path = files.find_evidence(rid, name) if name else None
            if path and path.suffix == ".png":
                st.image(str(path), width=700)
            elif path:
                st.caption(f"saved file: {path.name}")
            spec = (s["detail"] or {}).get("spec")
            if spec and s["method"] not in ("spec_yaml", "spec_memory"):
                st.caption("Table layout proposed by the agent (trusted only after approval):")
                st.json(spec, expanded=False)
    if run["status"] in ("pending_review", "published"):
        staged = store.load_rates(rid)
        ids = store.published_ids()
        base = store.load_rates(ids[1]) if run["status"] == "published" and len(ids) > 1 else (store.load_rates(ids[0]) if ids and run["status"] != "published" else None)
        with st.expander("Changes versus the previous data"):
            d = diff_runs(staged, base)
            st.dataframe(d.head(200), hide_index=True, width="stretch") if len(d) else st.info("No differences.")
    if run["status"] == "pending_review":
        a, b, _ = st.columns([1, 1, 4])
        if a.button("Approve & publish", key="ap" + rid):
            try:
                svc.approve(rid)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if b.button("Reject", key="rj" + rid):
            svc.reject(rid)
            st.rerun()
    elif run["status"] == "blocked":
        st.error("This refresh cannot go live. Fix the source or its layout and refresh again.")
