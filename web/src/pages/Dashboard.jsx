import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import Icon from '../components/Icon.jsx'
import { ChartCard, CountUp, DataTable, Drawer, Empty, Kpi, Pill, Skeleton, Tabs, useToast } from '../components/ui.jsx'
import { bankOf, pct, signed, statusLabel, statusKind, useDebounced, useQuery, useStored } from '../util.js'

const AMOUNTS = [1, 3, 5, 10, 25, 50, 100]
const TABS = [['overview', 'Overview'], ['compare', 'Compare banks'], ['curves', 'Rate curves'], ['size', 'Deposit size'], ['coverage', 'Coverage'], ['trends', 'Trends'], ['explorer', 'Bank explorer']]

function Filters({ meta, f, set }) {
  const [amt, setAmt] = useState(String(f.amount))
  const [open, setOpen] = useState(false)
  const [shut, setShut] = useState(() => window.innerWidth < 900)
  const pop = useRef(null)
  useEffect(() => setAmt(String(f.amount)), [f.amount])
  useEffect(() => {
    const h = (e) => pop.current && !pop.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h)
  }, [])
  const commit = (v) => { const n = Math.min(1000, Math.max(0.1, parseFloat(v))); if (!isNaN(n)) set({ amount: n }); else setAmt(String(f.amount)) }
  const step = (d) => commit((f.amount + d * (f.amount >= 10 ? 5 : f.amount >= 3 ? 1 : 0.5)).toFixed(1))
  const inGrid = meta.tenors.some((t) => t.days === f.days)
  const peers = meta.peers, chosen = f.banks === null ? peers : f.banks
  const toggleBank = (b) => set({ banks: chosen.includes(b) ? chosen.filter((x) => x !== b) : [...chosen, b] })
  return (
    <div className={`filters ${shut ? 'collapsed' : ''}`} role="search" aria-label="Dashboard filters">
      <button className="btn filters-toggle" onClick={() => setShut(!shut)} aria-expanded={!shut}><span><Icon name="filter" size={16} /> Filters · ₹{f.amount} Cr · {meta.tenors.find((t) => t.days === f.days)?.label || `${f.days}d`}</span><Icon name="down" size={15} /></button>
      <div className="field">
        <label htmlFor="amt">Deposit amount (₹ crore)</label>
        <div className="stepper">
          <button onClick={() => step(-1)} aria-label="Decrease amount">−</button>
          <input id="amt" inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} onBlur={(e) => commit(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && commit(e.target.value)} />
          <button onClick={() => step(1)} aria-label="Increase amount">+</button>
        </div>
        <div className="quick">{AMOUNTS.map((a) => <button key={a} className={`chip ${f.amount === a ? 'on' : ''}`} onClick={() => set({ amount: a })}>{a}</button>)}</div>
      </div>
      <div className="field">
        <label htmlFor="ten">Tenor</label>
        <select id="ten" value={inGrid ? f.days : 'custom'} onChange={(e) => e.target.value !== 'custom' && set({ days: +e.target.value })} style={{ minWidth: 150 }}>
          {meta.tenors.map((t) => <option key={t.days} value={t.days}>{t.label}</option>)}
          {!inGrid && <option value="custom">{f.days} days</option>}
        </select>
        <input aria-label="Custom tenor in days" placeholder="Other: days + Enter" style={{ padding: '4px 10px', fontSize: 12.5, width: 150 }}
          onKeyDown={(e) => { if (e.key === 'Enter' && +e.target.value >= 7) { set({ days: Math.round(+e.target.value) }); e.target.value = '' } }} />
      </div>
      <div className="field">
        <span className="lbl">Source types</span>
        <div className="quick">
          {meta.statuses.map((s) => (
            <button key={s} className={`chip ${f.statuses.includes(s) ? 'on' : ''}`} disabled={s === 'current'} title={meta.status_help[s]}
              onClick={() => set({ statuses: f.statuses.includes(s) ? f.statuses.filter((x) => x !== s) : [...f.statuses, s] })}>
              {f.statuses.includes(s) && <Icon name="check" size={13} />}{statusLabel(s)}
            </button>))}
        </div>
      </div>
      <div className="field pop-wrap" ref={pop}>
        <span className="lbl">Peer banks</span>
        <button className="btn" onClick={() => setOpen(!open)} aria-expanded={open}><Icon name="bank" size={16} />{chosen.length === peers.length ? 'All banks' : `${chosen.length} of ${peers.length} banks`}<Icon name="down" size={15} /></button>
        <button className="linkbtn" style={{ textAlign: 'left', padding: 0 }} onClick={() => set({ amount: 10, days: 90, statuses: meta.default_statuses, banks: null })}>Reset all filters</button>
        {open && (
          <div className="pop">
            <div className="pop-head"><b>Peer banks</b><span><button className="linkbtn" onClick={() => set({ banks: null })}>All</button><button className="linkbtn" onClick={() => set({ banks: [] })}>None</button></span></div>
            <div className="pop-list">{peers.map((b) => <label key={b} className="check"><input type="checkbox" checked={chosen.includes(b)} onChange={() => toggleBank(b)} />{b}</label>)}</div>
          </div>)}
      </div>
    </div>
  )
}

function Headline({ d }) {
  const k = d.kpis
  if (k.sber_rate === null) return <div className="headline behind"><div className="ico"><Icon name="info" /></div><div>Sberbank has no published rate for ₹{d.amount} Cr at {d.tenor_label}. Try another amount or tenor.</div></div>
  const ahead = k.gap !== null && k.gap >= 0
  return (
    <div className={`headline ${k.gap !== null && !ahead ? 'behind' : ''}`}>
      <div className="ico"><Icon name={ahead || k.gap === null ? 'trend' : 'target'} /></div>
      <div>
        At <b>₹{d.amount} Cr for {d.tenor_label}</b>, Sberbank pays <b>{pct(k.sber_rate)}</b> and ranks <b>{k.rank} of {k.ranked}</b> banks.
        {k.gap !== null && <> {ahead ? <>It is <b>{Math.abs(k.gap).toFixed(2)} pp ahead</b> of</> : <>It is <b>{Math.abs(k.gap).toFixed(2)} pp behind</b></>} the best peer ({k.best_peer}, {pct(k.best_peer_rate)}).</>}
      </div>
    </div>
  )
}

function Kpis({ d }) {
  const k = d.kpis
  return (
    <div className="kpis">
      <Kpi accent label="Sberbank rate" tip="Sberbank's rate for the selected amount and tenor." sub={`₹${d.amount} Cr · ${d.tenor_label}`}><CountUp value={k.sber_rate} suffix="%" /></Kpi>
      <Kpi label="Best peer" tip="Highest rate among the selected peer banks." sub={k.best_peer || 'no peer rate'}><CountUp value={k.best_peer_rate} suffix="%" /></Kpi>
      <Kpi label="Gap to best peer" tip="Sberbank minus the best peer, in percentage points (pp)." tone={k.gap === null ? '' : k.gap >= 0 ? 'up' : 'down'} sub={k.gap === null ? '' : k.gap >= 0 ? 'Sberbank ahead' : 'Sberbank behind'}>
        {k.gap === null ? '–' : <><CountUp value={k.gap} />{' pp'}</>}
      </Kpi>
      <Kpi label="Sberbank rank" tip="1 = highest rate among all banks shown." sub="1 = highest rate">{k.rank ? `${k.rank} of ${k.ranked}` : '–'}</Kpi>
      <Kpi label="Tenors led" tip="Tenor points where Sberbank pays the highest or joint-highest rate at this amount." sub={`at ₹${d.amount} Cr`}>{k.points ? `${k.led} of ${k.points}` : '–'}</Kpi>
    </div>
  )
}

function Scorecard({ sc }) {
  const col = (v) => `color-mix(in srgb, var(--brand) ${Math.round(v * 0.85)}%, var(--surface))`
  return (
    <div className="table-wrap" style={{ padding: '0 22px 20px' }}>
      <table className="t heat"><thead><tr><th>Deposit size</th>{sc.cols.map((c) => <th key={c} style={{ textAlign: 'center' }}>{c}</th>)}</tr></thead>
        <tbody>{sc.rows.map((r, i) => <tr key={r}><td style={{ fontWeight: 650 }}>{r}</td>{sc.values[i].map((v, j) => <td key={j} className="cell" style={{ background: v == null ? 'transparent' : col(v), color: v > 55 ? '#fff' : 'var(--text)' }}>{v == null ? '–' : `${v.toFixed(0)}%`}</td>)}</tr>)}</tbody></table>
    </div>
  )
}

function BankPanel({ name, amount, statuses, theme }) {
  const { data, loading, error } = useQuery(() => api.bank({ name, amount, statuses: statuses.join(',') }), [name, amount, statuses.join(',')])
  if (error && !data) return <div className="callout bad"><Icon name="alert" /><div>{error.message}</div></div>
  if (!data) return <Skeleton h={360} />
  const heat = (v) => (v == null ? 'transparent' : `color-mix(in srgb, var(--brand) ${Math.round(((v - 4) / 4) * 70 + 10)}%, var(--surface))`)
  return (
    <>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Pill kind={statusKind(data.status)}>{statusLabel(data.status)}</Pill><Pill icon="clock">Effective {data.effective}</Pill><Pill icon="database">{data.rates} published rates</Pill>
        {loading && <Pill>Updating…</Pill>}
      </div>
      <ChartCard spec={data.curve} theme={theme} title={`${name} vs Sberbank at ₹${amount} Cr`} />
      <div className="card">
        <div className="card-head"><div><h3>Published rate grid</h3><p>Interest rate (% p.a.) by tenor (rows) and deposit slab (columns).</p></div></div>
        <div className="table-wrap" style={{ padding: 18 }}>
          <table className="t heat"><thead><tr><th>Tenor</th>{data.cols.map((c) => <th key={c} style={{ textAlign: 'center' }}>{c}</th>)}</tr></thead>
            <tbody>{data.rows.map((r, i) => <tr key={r}><td style={{ fontWeight: 650, whiteSpace: 'nowrap' }}>{r}</td>{data.values[i].map((v, j) => <td key={j} className="cell" style={{ background: heat(v) }}>{v == null ? '–' : v.toFixed(2)}</td>)}</tr>)}</tbody></table>
        </div>
      </div>
    </>
  )
}

export default function Dashboard({ meta, theme, go }) {
  const toast = useToast()
  const [f, setF] = useStored('fd.filters.v2', { amount: 10, days: 90, statuses: null, banks: null })
  const [tab, setTab] = useStored('fd.tab', 'overview')
  const [drill, setDrill] = useState(null)
  const [explorer, setExplorer] = useState(null)
  const filt = { ...f, statuses: f.statuses || meta.default_statuses }
  const set = (p) => setF({ ...f, ...p })
  const dAmount = useDebounced(filt.amount, 250)
  const key = JSON.stringify([dAmount, filt.days, filt.statuses, filt.banks, meta.run_id])
  const { data: d, loading, error, reload } = useQuery(() => api.dashboard({ amount: dAmount, days: filt.days, statuses: filt.statuses.join(','), banks: filt.banks === null ? undefined : filt.banks.join(',') || '-' }), [key])
  const names = useMemo(() => meta.peers, [meta.peers])
  useEffect(() => { if (!explorer && names.length) setExplorer(names[0]) }, [names, explorer])

  const types = d && { ...d.charts.source_types, x: d.charts.source_types.x.map(statusLabel) }
  const pick = (label) => { setDrill(bankOf(label)) }
  if (error && !d) return <Empty icon="alert" title="The dashboard could not load" action={<button className="btn primary" onClick={reload}>Try again</button>}>{error.message}</Empty>

  return (
    <div className="page-in">
      <Filters meta={meta} f={filt} set={set} />
      {!d ? <><div className="kpis">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} h={104} />)}</div><Skeleton h={380} /></> : (
        <div style={{ opacity: loading ? .72 : 1, transition: 'opacity .2s' }}>
          <Headline d={d} />
          <Kpis d={d} />
          <Tabs tabs={TABS} value={tab} onChange={setTab} />

          {tab === 'overview' && (
            <div className="grid g-main">
              <div className="card"><div className="card-head"><div><h3>Key findings at ₹{d.amount} Cr</h3><p>Written from the numbers, so every statement can be checked.</p></div></div>
                <div className="findings">{d.findings.map((t, i) => <div className="finding" key={i}><span className="n">{i + 1}</span><span>{t}</span></div>)}</div></div>
              <div className="grid">
                <div className="card"><div className="card-head"><div><h3>Where Sberbank is #1</h3><p>Share of amount × tenor cases where Sberbank pays the most.</p></div></div><div style={{ height: 14 }} /><Scorecard sc={d.scorecard} /></div>
                <ChartCard spec={d.charts.lead_share} theme={theme} />
              </div>
            </div>)}

          {tab === 'compare' && (
            <div className="grid">
              <ChartCard spec={d.charts.ranking} theme={theme} onPoint={pick} hint="Click any bar to see that bank's full rate grid." />
              <div className="card"><div className="card-head"><div><h3>All banks, ranked</h3><p>Quote only “Official” sources to clients.</p></div></div>
                <div style={{ padding: 14 }}><DataTable rows={d.table} rowClass={(r) => (r.name === meta.sber ? 'sber' : '')} onRow={(r) => pick(r.name)} empty="No rates for this amount and tenor."
                  cols={[{ key: 'rank', label: 'Rank' }, { key: 'name', label: 'Bank / product' }, { key: 'rate', label: 'Rate', num: true, render: (v) => pct(v) },
                    { key: 'vs_sber_pp', label: 'vs Sberbank', num: true, render: (v, r) => (r.name === meta.sber ? '–' : <span className={v > 0 ? 'neg' : 'pos'}>{signed(v)} pp</span>) },
                    { key: 'status', label: 'Source', render: (v) => <Pill kind={statusKind(v)}>{statusLabel(v)}</Pill> }, { key: 'effective', label: 'Effective' }, { key: 'amt_label', label: 'Amount slab' }, { key: 'tenor_label', label: 'Tenor slab' }]} /></div></div>
            </div>)}

          {tab === 'curves' && <div className="grid"><ChartCard spec={d.charts.curve} theme={theme} hint="Each line is a bank. Sberbank is the thick green line." /><ChartCard spec={d.charts.heatmap} theme={theme} hint="Green = Sberbank ahead of the best peer, red = behind." /></div>}
          {tab === 'size' && <ChartCard spec={d.charts.size} theme={theme} hint={`Sberbank's rate by deposit size at ${d.tenor_label}, against the best peer.`} />}
          {tab === 'coverage' && (
            <div className="grid">
              <div className="grid g2"><ChartCard spec={d.charts.coverage} theme={theme} /><ChartCard spec={types} theme={theme} /></div>
              <div className="card"><div className="card-head"><div><h3>Sources in this view</h3><p>Where each bank's rates come from and how recent they are.</p></div></div><div style={{ padding: 14 }}>
                <DataTable rows={d.sources} cols={[{ key: 'Bank / product', label: 'Bank / product' }, { key: 'Status', label: 'Source', render: (v) => <Pill kind={statusKind(v)}>{statusLabel(v)}</Pill> }, { key: 'Effective date', label: 'Effective' }, { key: 'Rates', label: 'Rates', num: true }, { key: 'Min %', label: 'Min %', num: true }, { key: 'Max %', label: 'Max %', num: true }]} /></div></div>
            </div>)}
          {tab === 'trends' && (
            <div className="grid">
              <ChartCard spec={d.charts.history} theme={theme} />
              <div className="card"><div className="card-head"><div><h3>Rate changes since the previous update</h3><p>{d.changes.total ? `${d.changes.total} changes` : 'Nothing has changed.'}</p></div></div><div style={{ padding: 14 }}>
                <DataTable rows={d.changes.rows} empty="No rate changes since the previous update." cols={[{ key: 'series', label: 'Bank' }, { key: 'amt_label', label: 'Amount' }, { key: 'tenor_label', label: 'Tenor' }, { key: 'old', label: 'Before', num: true, render: (v) => pct(v) }, { key: 'new', label: 'Now', num: true, render: (v) => pct(v) },
                  { key: 'change_pp', label: 'Change', num: true, render: (v) => <span className={v > 0 ? 'pos' : 'neg'}>{signed(v)} pp</span> }, { key: 'kind', label: 'Type', render: (v) => <Pill kind={v === 'changed' ? 'info' : 'grey'}>{v}</Pill> }]} /></div></div>
            </div>)}
          {tab === 'explorer' && (
            <div className="grid">
              <div className="card card-pad"><div className="field" style={{ maxWidth: 360 }}><label htmlFor="bk">Choose a bank</label><select id="bk" value={explorer || ''} onChange={(e) => setExplorer(e.target.value)}>{names.map((n) => <option key={n}>{n}</option>)}</select></div></div>
              {explorer && <BankPanel name={explorer} amount={dAmount} statuses={filt.statuses} theme={theme} />}
            </div>)}
        </div>)}

      {drill && (
        <Drawer title={drill} subtitle={`Compared with Sberbank at ₹${dAmount} Cr`} onClose={() => setDrill(null)}>
          <BankPanel name={drill} amount={dAmount} statuses={filt.statuses} theme={theme} />
          <button className="btn" onClick={() => { setExplorer(drill); setTab('explorer'); setDrill(null); toast(`Opened ${drill} in Bank explorer`) }}><Icon name="arrow" size={16} />Open in Bank explorer</button>
        </Drawer>)}
    </div>
  )
}
