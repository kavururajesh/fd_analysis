import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetch with keep-previous-data so filters never blank the screen. */
export function useQuery(fn, deps) {
  const [s, set] = useState({ data: null, loading: true, error: null })
  const seq = useRef(0)
  const run = useCallback(() => {
    const id = ++seq.current
    set((p) => ({ ...p, loading: true, error: null }))
    fn().then((data) => id === seq.current && set({ data, loading: false, error: null }))
      .catch((error) => id === seq.current && set((p) => ({ data: error.status === 404 ? null : p.data, loading: false, error })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { ...s, reload: run }
}

export function useDebounced(value, ms = 350) {
  const [v, set] = useState(value)
  useEffect(() => { const t = setTimeout(() => set(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export function useStored(key, initial) {
  const [v, set] = useState(() => { try { const s = localStorage.getItem(key); return s ? JSON.parse(s) : initial } catch { return initial } })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* storage may be blocked */ } }, [key, v])
  return [v, set]
}

export const pct = (v, d = 2) => (v === null || v === undefined ? '–' : `${v.toFixed(d)}%`)
export const signed = (v, d = 2) => (v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(d)}`)
export const fmtDate = (iso) => {
  if (!iso) return '–'
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso)
  return isNaN(d) ? iso : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', ...(iso.length > 10 ? { hour: '2-digit', minute: '2-digit' } : {}) })
}
export const bankOf = (label) => label.replace(/ \((proxy|default_table|stale)\)$/, '')
export const statusLabel = (s) => ({ pending_review: 'Needs review', published: 'Published', blocked: 'Blocked', rejected: 'Rejected', superseded: 'Replaced', current: 'Official', proxy: 'Large-deposit table', default_table: 'Default tab only', stale: 'Older sheet' }[s] || s.replace(/_/g, ' '))
export const statusKind = (s) => ({ pending_review: 'warn', published: 'ok', blocked: 'bad', rejected: 'grey', superseded: 'grey', current: 'ok', proxy: 'info', default_table: 'warn', stale: 'warn' }[s] || 'grey')
