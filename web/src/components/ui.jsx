import { createPortal } from 'react-dom'
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import Chart from './Chart.jsx'

export const Pill = ({ kind = 'grey', children, icon }) => <span className={`pill ${kind}`}>{icon && <Icon name={icon} size={13} />}{children}</span>

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, label]) => (
        <button key={k} role="tab" aria-selected={value === k} className={`tab ${value === k ? 'on' : ''}`} onClick={() => onChange(k)}>{label}</button>
      ))}
    </div>
  )
}

export function CountUp({ value, decimals = 2, suffix = '', prefix = '' }) {
  const [v, setV] = useState(value)
  const prev = useRef(value)
  useEffect(() => {
    if (value === null || value === undefined || prev.current === null || prev.current === undefined || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setV(value); prev.current = value; return }
    const from = prev.current, to = value, t0 = performance.now()
    let raf
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / 450), e = 1 - Math.pow(1 - k, 3)
      setV(from + (to - from) * e)
      if (k < 1) raf = requestAnimationFrame(tick); else prev.current = to
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  if (v === null || v === undefined) return <>–</>
  return <>{prefix}{v.toFixed(decimals)}{suffix}</>
}

export function Kpi({ label, tip, children, sub, tone, accent }) {
  return (
    <div className={`kpi ${tone || ''} ${accent ? 'accent' : ''}`}>
      <div className="lbl">{label}{tip && <span title={tip} style={{ display: 'inline-flex', cursor: 'help', opacity: .7 }}><Icon name="info" size={14} /></span>}</div>
      <div className="val">{children}</div>
      <div className="sub">{sub}</div>
    </div>
  )
}

export function Skeleton({ h = 120, style }) { return <div className="skeleton" style={{ height: h, ...style }} /> }

export function Empty({ icon = 'database', title, children, action }) {
  return (
    <div className="empty card">
      <div className="ico"><Icon name={icon} /></div>
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  )
}

/** Very small markdown: **bold**, `code`, "- " bullets, blank-line paragraphs. */
export function Md({ text }) {
  const inline = (s) => s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => p.startsWith('**') ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith('`') ? <code key={i}>{p.slice(1, -1)}</code> : p)
  const blocks = []
  let list = []
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = [] } }
  ;(text || '').split('\n').forEach((line) => {
    const m = line.match(/^\s*[-*•]\s+(.*)/)
    if (m) list.push(m[1]); else { flush(); if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>) }
  })
  flush()
  return <>{blocks}</>
}

/** A chart in a titled card with a plain-English "What this shows" note. */
export function ChartCard({ spec, title, subtitle, theme, onPoint, height, hint, note }) {
  if (!spec) return <div className="card card-pad"><Skeleton h={300} /></div>
  const facts = note ? [note] : spec.facts || []
  return (
    <div className="card">
      <div className="card-head"><div><h3>{title || spec.title}</h3>{(subtitle || hint) && <p>{subtitle || hint}</p>}</div></div>
      <Chart spec={spec} theme={theme} onPoint={onPoint} height={height} title={title || spec.title} saveName={(title || spec.title || 'chart').replace(/[^\w]+/g, '_')} />
      {facts.length > 0 && (
        <div className="note"><Icon name="sparkle" size={17} /><ul>{facts.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
      )}
    </div>
  )
}

/* ---------- toasts ---------- */
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastHost({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((text, kind = 'ok') => {
    const id = Math.random()
    setItems((p) => [...p, { id, text, kind }])
    setTimeout(() => setItems((p) => p.filter((t) => t.id !== id)), 4200)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind === 'bad' ? 'bad' : ''}`}><Icon name={t.kind === 'bad' ? 'alert' : 'check'} />{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  )
}

export function Modal({ title, children, onClose, actions }) {
  useEffect(() => { const k = (e) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <div className="hint" style={{ fontSize: 14.5 }}>{children}</div>
        <div className="row">{actions}</div>
      </div>
    </>, document.body)
}

export function Drawer({ title, subtitle, onClose, children }) {
  useEffect(() => { const k = (e) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head">
          <div style={{ flex: 1 }}><h2 style={{ fontSize: 18 }}>{title}</h2>{subtitle && <div className="hint">{subtitle}</div>}</div>
          <button className="btn ghost icon-only" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>, document.body)
}

/** Sortable table. cols: [{key,label,num,render}] */
export function DataTable({ cols, rows, onRow, rowClass, max = 400, empty = 'Nothing to show.' }) {
  const [sort, setSort] = useState(null)
  let data = rows || []
  if (sort) data = [...data].sort((a, b) => { const x = a[sort.k], y = b[sort.k]; const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? '')); return sort.dir * r })
  if (!data.length) return <div className="hint" style={{ padding: 18 }}>{empty}</div>
  return (
    <div className="table-wrap">
      <table className="t">
        <thead><tr>{cols.map((c) => (
          <th key={c.key} className={`sortable ${c.num ? 'num' : ''}`} onClick={() => setSort((s) => (s && s.k === c.key ? { k: c.key, dir: -s.dir } : { k: c.key, dir: 1 }))}>
            {c.label}{sort && sort.k === c.key ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}
          </th>))}</tr></thead>
        <tbody>
          {data.slice(0, max).map((r, i) => (
            <tr key={i} className={`${rowClass ? rowClass(r) : ''} ${onRow ? 'click' : ''}`} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => <td key={c.key} className={c.num ? 'num' : ''}>{c.render ? c.render(r[c.key], r) : r[c.key] ?? '–'}</td>)}
            </tr>))}
        </tbody>
      </table>
      {data.length > max && <div className="hint" style={{ padding: 10 }}>Showing the first {max} of {data.length} rows.</div>}
    </div>
  )
}
