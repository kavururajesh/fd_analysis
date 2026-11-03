import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import Icon from '../components/Icon.jsx'
import { DataTable, Empty, Md, Modal, Pill, Skeleton, Tabs, useToast } from '../components/ui.jsx'
import { fmtDate, statusKind, statusLabel, useQuery } from '../util.js'

const KIND_LABEL = { start: 'started', tool: 'reading', observation: 'result', thought: 'thinking', final: 'done', error: 'problem', warn: 'warning' }

function Activity({ job }) {
  const end = useRef(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [job.events.length])
  const state = job.state === 'running' ? ['info', 'Running…'] : job.state === 'failed' ? ['bad', 'Failed'] : ['ok', 'Finished']
  return (
    <div className="card mt">
      <div className="card-head"><div><h3>Live agent activity</h3><p>What the data agents are doing right now.</p></div><div className="actions"><Pill kind={state[0]}>{job.state === 'running' && <Icon name="refresh" size={13} className="spin" />}{state[1]}</Pill></div></div>
      <div className="timeline" style={{ marginTop: 10 }}>
        {job.events.length === 0 && <div className="hint">Starting up…</div>}
        {job.events.map((e, i) => <div className="ev" key={i}><div><div className="ag">{e.agent}</div><div className="kind">{KIND_LABEL[e.kind] || e.kind}</div></div><div>{e.text}</div></div>)}
        <div ref={end} />
      </div>
      {job.error && <div className="callout bad" style={{ margin: '0 22px 20px' }}><Icon name="alert" /><div>{job.error}</div></div>}
    </div>
  )
}

function RunDetail({ id, liveId, onDecided }) {
  const toast = useToast()
  const { data: r, loading, reload } = useQuery(() => api.run(id), [id])
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  if (!r) return <Skeleton h={300} />
  const act = async (kind) => {
    setBusy(true)
    try { await (kind === 'approve' ? api.approve(id) : api.reject(id)); toast(kind === 'approve' ? 'Published. The dashboard now uses this data.' : 'Refresh rejected. The live data is unchanged.'); setConfirm(null); onDecided(); reload() }
    catch (e) { toast(e.message, 'bad'); setConfirm(null) } finally { setBusy(false) }
  }
  return (
    <div className="grid" style={{ opacity: loading ? .7 : 1 }}>
      <div className="card card-pad">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><h3>Refresh {r.run_id}</h3><Pill kind={statusKind(r.status)}>{r.run_id === liveId ? 'Live now' : statusLabel(r.status)}</Pill><span className="hint">{fmtDate(r.created)}</span></div>
        {r.status === 'pending_review' && <div className="callout" style={{ marginTop: 14 }}><Icon name="alert" /><div><b>This refresh needs a decision.</b> The live data stays unchanged until you approve it.</div></div>}
        {r.status === 'blocked' && <div className="callout bad" style={{ marginTop: 14 }}><Icon name="alert" /><div><b>This refresh cannot go live.</b> Fix the source or its page layout and refresh again.</div></div>}
        {r.reasons.length > 0 && <><h4 style={{ margin: '16px 0 6px' }}>Why it was flagged</h4><ul style={{ margin: 0, paddingLeft: 20 }}>{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
        {r.brief && <div className="finding" style={{ marginTop: 14, display: 'block' }}><b>Review brief</b><div style={{ marginTop: 6 }}><Md text={r.brief} /></div></div>}
        {r.status === 'pending_review' && <div style={{ display: 'flex', gap: 10, marginTop: 18 }}><button className="btn primary" onClick={() => setConfirm('approve')}><Icon name="check" size={16} />Approve and publish</button><button className="btn danger" onClick={() => setConfirm('reject')}>Reject</button></div>}
      </div>
      <div className="card"><div className="card-head"><div><h3>Sources read in this refresh</h3><p>What the agents saw, with evidence.</p></div></div>
        <div style={{ padding: 18, display: 'grid', gap: 12 }}>{r.sources.map((s) => (
          <div className="src" key={s.id}>
            <div className="top"><b>{s.id}</b><Pill kind={s.ok ? 'ok' : 'bad'} icon={s.ok ? 'check' : 'alert'}>{s.ok ? 'Read' : 'Failed'}</Pill><Pill>{s.method}</Pill><span className="hint">{s.rates} rates{s.effective ? ` · effective ${s.effective}` : ''}</span></div>
            {[...s.errors, ...s.warnings].map((x, i) => <div key={i} className="hint" style={{ color: s.errors.includes(x) ? 'var(--bad)' : 'var(--warn)' }}>• {x}</div>)}
            <div className="hint" style={{ wordBreak: 'break-all' }}>{s.url} {s.retrieved && `· retrieved ${s.retrieved}`} {s.sha && `· sha256 ${s.sha}…`}</div>
            {s.image && <details><summary className="hint" style={{ cursor: 'pointer' }}>Show what the browser saw</summary><img loading="lazy" alt={`Screenshot of ${s.id}`} src={`/api/ops/evidence/${r.run_id}/${s.file}`} /></details>}
            {s.spec && <details><summary className="hint" style={{ cursor: 'pointer' }}>Table layout proposed by the agent (trusted only after approval)</summary><pre className="steps">{JSON.stringify(s.spec, null, 2)}</pre></details>}
          </div>))}</div></div>
      {r.changes.length > 0 && <div className="card"><div className="card-head"><div><h3>Changes versus the previous data</h3><p>{r.changes.length} rate changes</p></div></div><div style={{ padding: 14 }}>
        <DataTable rows={r.changes} cols={[{ key: 'series', label: 'Bank' }, { key: 'amt_label', label: 'Amount' }, { key: 'tenor_label', label: 'Tenor' }, { key: 'old', label: 'Before', num: true }, { key: 'new', label: 'Now', num: true }, { key: 'change_pp', label: 'Change (pp)', num: true, render: (v) => <span className={v > 0 ? 'pos' : 'neg'}>{v > 0 ? '+' : ''}{v}</span> }, { key: 'kind', label: 'Type' }]} /></div></div>}
      {confirm && <Modal title={confirm === 'approve' ? 'Publish this refresh?' : 'Reject this refresh?'} onClose={() => setConfirm(null)}
        actions={<><button className="btn" onClick={() => setConfirm(null)}>Cancel</button><button className={`btn ${confirm === 'approve' ? 'primary' : 'danger solid'}`} disabled={busy} onClick={() => act(confirm)}>{confirm === 'approve' ? 'Approve and publish' : 'Reject'}</button></>}>
        {confirm === 'approve' ? 'The dashboard and assistant will switch to this data. The old dataset is deleted only after the switch succeeds.' : 'The staged files are removed. The current live data is not affected.'}
      </Modal>}
    </div>
  )
}

function ActivityLog({ runs }) {
  const [id, setId] = useState(runs[0]?.run_id)
  const { data } = useQuery(() => (id ? api.traces(id) : Promise.resolve([])), [id])
  return (
    <div className="grid">
      <div className="card"><div className="card-head"><div><h3>Refresh history</h3></div></div><div style={{ padding: 14 }}>
        <DataTable rows={runs} cols={[{ key: 'run_id', label: 'Run' }, { key: 'created', label: 'Started', render: fmtDate }, { key: 'status', label: 'Status', render: (v) => <Pill kind={statusKind(v)}>{statusLabel(v)}</Pill> }, { key: 'mode', label: 'Mode' }, { key: 'decided_by', label: 'Decided by' }]} onRow={(r) => setId(r.run_id)} /></div></div>
      <div className="card"><div className="card-head"><div><h3>Agent log</h3><p>Run {id}</p></div></div><div style={{ padding: 14 }}>
        <DataTable rows={data || []} max={300} cols={[{ key: 'agent', label: 'Agent' }, { key: 'kind', label: 'Step' }, { key: 'text', label: 'Detail' }]} empty="No log for this run." /></div></div>
    </div>
  )
}

export default function Operations({ meta, reloadMeta, go }) {
  const toast = useToast()
  const { data: s, reload } = useQuery(() => api.summary(), [meta.run_id])
  const [tab, setTab] = useState('review')
  const [job, setJob] = useState(null)
  const [sel, setSel] = useState(null)
  const polling = useRef(null)

  const start = async () => {
    try {
      const { job_id } = await api.refresh()
      setJob({ id: job_id, state: 'running', events: [], next: 0 })
      let next = 0
      clearInterval(polling.current)
      polling.current = setInterval(async () => {
        try {
          const j = await api.job(job_id, next); next = j.next
          setJob((p) => ({ ...j, events: [...(p?.events || []), ...j.events] }))
          if (j.state !== 'running') { clearInterval(polling.current); reload(); reloadMeta(); if (j.run_id) setSel(j.run_id); toast(j.state === 'failed' ? 'The refresh failed' : j.status === 'pending_review' ? 'Refresh finished. It needs your review.' : j.status === 'blocked' ? 'Refresh finished but cannot go live' : 'Refresh finished. New data is live.', j.state === 'failed' ? 'bad' : 'ok') }
        } catch { /* transient */ }
      }, 1000)
    } catch (e) { toast(e.message, 'bad') }
  }
  useEffect(() => () => clearInterval(polling.current), [])
  useEffect(() => { if (s && !sel && s.runs.length) setSel((s.runs.find((r) => r.status === 'pending_review') || s.runs[0]).run_id) }, [s, sel])
  const running = job?.state === 'running' || s?.running
  const man = s?.manifest
  const waiting = (s?.runs || []).filter((r) => r.status === 'pending_review')

  return (
    <div className="page-in">
      <div className="card status-hero">
        <div className="big">
          <div className="ico"><Icon name={man ? 'shield' : 'database'} /></div>
          <div>
            <h2>{man ? 'Your data is up to date' : 'No data yet'}</h2>
            <p className="hint">{man ? `Live dataset: ${man.rows.toLocaleString()} rates, verified before use.` : 'Run the first refresh to collect and verify the rates.'}</p>
          </div>
        </div>
        {man && <div className="mini-kpis"><div><div className="lbl">Last updated</div><div className="val">{fmtDate(man.created)}</div></div><div><div className="lbl">Sources read</div><div className="val">{s.sources_ok} of {s.sources_total}</div></div><div><div className="lbl">Storage</div><div className="val">{s.storage_kb.toLocaleString()} KB</div></div></div>}
        <button className="btn primary" onClick={start} disabled={running}><Icon name="refresh" size={17} className={running ? 'spin' : ''} />{running ? 'Refreshing…' : 'Refresh data now'}</button>
      </div>
      <p className="hint" style={{ margin: '10px 4px 0' }}>The data agents read every configured source, check the numbers and replace the live dataset only when everything passes. Unusual results wait here for a reviewer.</p>

      {waiting.length > 0 && <div className="callout mt"><Icon name="alert" /><div><b>{waiting.length} refresh{waiting.length > 1 ? 'es need' : ' needs'} your review.</b> Open the Review tab to approve or reject.</div></div>}
      {job && <Activity job={job} />}

      <div className="mt"><Tabs tabs={[['review', 'Review'], ['sources', 'Source health'], ['files', 'Files'], ['log', 'Activity log']]} value={tab} onChange={setTab} /></div>
      {!s ? <Skeleton h={260} /> : (<>
        {tab === 'review' && (s.runs.length === 0 ? <Empty icon="refresh" title="No refresh has run yet" action={<button className="btn primary" onClick={start} disabled={running}><Icon name="play" size={15} />Run the first refresh</button>}>The first refresh collects every source. You will be asked to approve it before it goes live.</Empty> : (
          <div className="split">
            <div className="runlist">{s.runs.slice(0, 15).map((r) => <button key={r.run_id} className={`run ${sel === r.run_id ? 'on' : ''}`} onClick={() => setSel(r.run_id)}><span className="id">{r.run_id}</span><span className="meta"><span>{fmtDate(r.created)}</span><Pill kind={statusKind(r.status)}>{r.run_id === meta.run_id ? 'Live now' : statusLabel(r.status)}</Pill></span></button>)}</div>
            {sel && <RunDetail id={sel} liveId={meta.run_id} onDecided={() => { reload(); reloadMeta() }} />}
          </div>))}
        {tab === 'sources' && <div className="card"><div className="card-head"><div><h3>Source health</h3><p>Result of the latest refresh for each source. Mode: {s.mode === 'local' ? 'saved page snapshots' : 'live bank websites'}.</p></div></div><div style={{ padding: 14 }}>
          <DataTable rows={s.sources} empty="No refresh yet." cols={[{ key: 'id', label: 'Source' }, { key: 'ok', label: 'Status', render: (v) => <Pill kind={v ? 'ok' : 'bad'} icon={v ? 'check' : 'alert'}>{v ? 'Read' : 'Failed'}</Pill> }, { key: 'method', label: 'Method' }, { key: 'rates', label: 'Rates', num: true }, { key: 'effective', label: 'Effective date' }, { key: 'notes', label: 'Notes' }]} /></div></div>}
        {tab === 'files' && <div className="grid">
          <div className="card"><div className="card-head"><div><h3>How a safe update works</h3><p>The app never reads half-loaded data.</p></div></div>
            <div className="swap">{[['Stage', 'New data is written to a separate staging folder.'], ['Verify', 'Checksum, row count and validation rules are checked.'], ['Swap', 'The staging folder becomes the live folder in one step.'], ['Clean up', 'The old dataset is deleted only after the swap succeeded.']].map(([t, d], i) => <div className="s" key={t}><div className="n">{i + 1}</div><b>{t}</b><span>{d}</span></div>)}</div></div>
          <div className="card"><div className="card-head"><div><h3>Dataset files</h3></div></div><div style={{ padding: 14 }}><DataTable rows={s.files} empty="No files yet." cols={[{ key: 'location', label: 'Location', render: (v) => <Pill kind={v === 'current' ? 'ok' : 'grey'}>{v}</Pill> }, { key: 'file', label: 'File' }, { key: 'kb', label: 'Size (KB)', num: true }]} /></div></div></div>}
        {tab === 'log' && (s.runs.length ? <ActivityLog runs={s.runs} /> : <Empty icon="clock" title="No activity yet">Agent activity appears here after the first refresh.</Empty>)}
      </>)}
    </div>
  )
}
