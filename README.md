# Corporate Deposits Analytics — Sberbank India

Analytics dashboard + AI chatbot for the corporate FD rate comparison (Sberbank vs peer banks). Data is collected by browser agents,
validated, and swapped in safely. Everything runs locally; the only external call is Sber's own GigaChat.

## Web app (React)
`run_ui.bat` (or `python -m src.main web`) starts one local server and opens **http://localhost:8000**. The interface is a React single-page app
(`web/`) that talks to the JSON API in `src/api/web.py`; the finished build is committed in `web/dist`, so **Node.js is not needed on the laptop**.
- Dashboard: filter bar (amount, tenor, source types, peer banks), plain-English headline, 5 KPIs, 7 views, click a bar to drill into a bank, chart image export, Excel report.
- Analytics assistant: suggestion cards, chat with charts and a short explanation, "checked against the data" badge, copy, "how was this answered".
- Data operations: one-click refresh with live agent activity, review inbox with approve / reject confirmation, source health, files, activity log.
- Light and dark theme, phone/tablet layout, keyboard friendly (Esc closes panels, Enter sends).
To change the UI: `cd web && npm install && npm run build` (development with hot reload: `npm run dev` while `python -m src.main api` runs). The previous Streamlit UI remains available with `run_streamlit.bat`.

## What you get
| | |
|---|---|
| **Dashboard** | KPIs, bar / line / pie / heat-map views, filters (amount, tenor, peer banks, source type), click-through drill-down, trend history, Excel export |
| **AI chatbot** | Plain-English questions → answer from the data. Comparison / trend questions also get the best-fitting chart plus a 2–3 sentence explanation. Simple lookups get text only. Every figure is checked against tool output |
| **Automated refresh** | Supervisor + Collector agents (Playwright) read all sources, validate, stage, verify, then replace the live dataset. Old files are deleted only after that succeeds |
| **Data operations page** | Run a refresh, watch agent activity, review flagged runs, source health, file view, audit log |

## Architecture
```
Bank sources (web, JS tabs, PDF)
   └─ Ingestion & automation   src/agent (supervisor, collector), src/tools (Playwright browser, parsers), config/sources.*.yaml
        └─ Validate · stage · swap   src/domain/validation.py, src/datastore (files.py, publisher.py)
             └─ Storage              data/current (live) · data/staging · data/fd_agent.db (SQLite: runs, history, layouts, audit)
                  └─ Analytics       src/domain (analytics, charts) · src/tools/analytics_tools.py
                       └─ Experience ui/ (Streamlit) · src/api (FastAPI) · Excel report
GigaChat (mutual TLS) — src/llm/client.py — used by the agents and for explanations only
```
Folder map: `config/` settings & sources · `src/` backend · `ui/` frontend · `data/` datasets · `logs/` · `tests/` · `evals/` · `scripts/`.
Separation: frontend (`ui/`) only calls `src/service.py`; automation (`src/agent`, `src/tools`) never imports the UI; all paths come from `src/config/settings.py`
(override with `.env`), so moving to a server means changing configuration, not code.

## Safe data replacement (how files are managed)
1. A refresh writes to `data/staging/<run>/` (rates.csv, manifest with checksum, evidence).
2. `DatasetFiles.verify` reads the files back: checksum, row count, columns, dataset validation.
3. `promote` switches `data/current` ← staging with two renames; the old copy is deleted **after** the switch succeeds. Any failure rolls back; the existing data stays live.
4. The app always reads `data/current`. Older pending runs become *superseded*. Rejected/failed staging is cleaned up.
5. A compact numbers-only history (last `KEEP_RUNS`, default 60) stays in SQLite for trend charts and change comparison. Set `KEEP_RUNS=2` for minimum retention.

Policy: a **clean** run (no flags) replaces the data automatically (`AUTO_PUBLISH_CLEAN=true`). Flagged runs — first run, healed page layout, rate move above `MAX_RATE_MOVE_PP`, stale carry-forward, date mismatch — wait for a reviewer. A failed Sberbank source blocks the run.

## Run it (Windows laptop)
```
scripts\setup_windows.bat      :: venv + packages + .env
run_ui.bat                     :: http://localhost:8501
```
First start: **Data operations → Refresh data now**, approve the first run, then use the dashboard and chatbot.
Browser: the Edge already installed is used (`BROWSER_CHANNEL=msedge`); fallback is Playwright Chromium (`playwright install chromium`).

**Schedule automatic refresh** (Windows Task Scheduler, daily 07:30):
```
schtasks /create /tn "FD Rate Refresh" /tr "C:\path\to\fd_rate_agent\run_refresh_silent.bat" /sc daily /st 07:30
```
The refresh exits non-zero if the run is blocked, so the scheduler shows failures. Output goes to `logs\last_refresh.txt`.

## Connect GigaChat
Copy `.env.example` → `.env`; set `GIGACHAT_URL` and the three certificate paths (same as `config.py`). `LLM_MODE=auto` uses GigaChat when configured; otherwise a built-in rule-based
engine answers (sidebar shows which one is active). Then run `python -m evals.evaluate_agent` with `LLM_MODE=gigachat` to measure the real model on the test questions.

## Go live (real bank sites)
`.env`: `SOURCE_MODE=live` → `python -m src.main check <source_id>` to inspect each page → run a refresh: agents calibrate each layout, you approve, later runs need no LLM.
Add `actions: [{click: 'text=…'}]` in `config/sources.live.yaml` for tabs (ICICI amount tabs, SBI >₹25Cr).

## Bank coverage
`config/sources.live.yaml` lists **32 sources across 29 banks** (found by web search on 3-Nov-2026):
- First wave: Sberbank, HDFC, ICICI, SBI, RBL, Axis, PNB, Canara, Union Bank, Equitas SFB, Punjab & Sind.
- Second wave: Kotak, Bank of Baroda (up to / above Rs 10 Cr), Bank of India, Indian Bank, Yes Bank, Federal Bank, IDBI, Bandhan, AU SFB, IndusInd, Central Bank of India, UCO, Bank of Maharashtra, Indian Overseas Bank, South Indian Bank, Karur Vysya, J&K Bank, City Union Bank.
- **All of these are config only**: the pages were not opened or calibrated from the build environment (bank sites are not reachable from there). Run `python -m src.main check-all` on the bank network: it opens every source in parallel and prints OK / PROBLEM, the tables found and the date on the page. Fix the URL of any PROBLEM source (PDF names change with every revision), then refresh and approve; the Collector agent learns each layout on the first run.
- Not added: foreign banks (HSBC, Standard Chartered, DBS: retail rates only online), IDFC FIRST (live URL still missing), DCB, Dhanlaxmi, CSB, TMB, Ujjivan, Jana (no official bulk-rate page found).
- A failing **peer** source only gives a warning and its previous rates are carried forward as *stale*; a failing Sberbank source still blocks the run.
- The local snapshot mode (`sources.local.yaml`) still holds the original 9 sources from the reference workbook.

## Parallel collection
A refresh reads many banks at the same time (`COLLECT_WORKERS`, default 3):
- **One browser per worker thread** (Playwright's sync API cannot be shared between threads); one isolated context per source.
- **Shared queue + result map keyed by source id.** The dataset is assembled in config order, so the output never depends on which bank finished first (tested: parallel and sequential runs give identical data).
- **Per-website limit** (`COLLECT_PER_HOST`, default 1): two sources on the same site are never fetched together; a worker that finds a site busy takes another source.
- **LLM limit** (`COLLECT_LLM_LIMIT`): self-healing calls to GigaChat run at most 2 at a time.
- **Isolation, retry, deadline**: a crashing source only fails itself; temporary network errors are retried (`COLLECT_RETRIES`); `COLLECT_TOTAL_DEADLINE_S` stops a hung page from blocking the run.
- Measured on the 9 local pages with a simulated 2 s bank delay (`FIXTURE_DELAY_MS=2000`, `COLLECT_PER_HOST=9`): 1 worker 20.8 s, 3 workers 8.1 s, 5 workers 5.1 s, identical 1192 rates. With the default per-site limit of 1 all local pages share one host and run one by one, so the benefit appears with real banks (each on its own website). Not yet measured on real bank sites.

## Other commands
`python -m src.main refresh | ask "…" | check <id> | api | simulate-drift on|off | eval` · `run_tests.bat` · API docs at `/docs` after `run_api.bat`.

## Production path (proposed, not built)
Internal VM/container behind Sber SSO · SQLite → Sber database (change in `src/memory/store.py`) · Task Scheduler → enterprise scheduler · `data/` → approved file share · central logging.
Needs Sber IT and security review.

## Status (honest)
- ✔ 54 automated tests: parsing, layouts, validation, agent loop guards, safe replacement (incl. corrupted staging, rollback, superseded runs), chart specs, chatbot charts and explanations, full browser runs on local snapshots.
- ✔ Extraction on local snapshots matches the reference workbook cell by cell (9/9 sources).
- ✘ Not tested: real GigaChat and the real bank websites (not reachable from the build environment). Live page layouts need one-time calibration on your laptop.
- ✘ Dockerfile is untested and optional. No external Git repository was available to me, so "existing code" = the earlier build in this project, which was reused and extended.
- Data = reference workbook of 21-Oct-2026 (local snapshots). Confirm rates on the bank's page before quoting a client.
