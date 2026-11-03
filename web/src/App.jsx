import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Icon from './components/Icon.jsx'
import { Empty, Skeleton, ToastHost } from './components/ui.jsx'
import Assistant from './pages/Assistant.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Operations from './pages/Operations.jsx'
import { fmtDate, useQuery, useStored } from './util.js'

const NAV = [['dashboard', 'Dashboard', 'grid', 'Rates, trends and comparisons'], ['assistant', 'Analytics assistant', 'chat', 'Ask questions in plain English'], ['operations', 'Data operations', 'database', 'Refresh and review data']]
const route = () => (location.hash.replace(/^#\/?/, '').split('/')[0] || 'dashboard')

export default function App() {
  const [page, setPage] = useState(route())
  const [theme, setTheme] = useStored('fd.theme', window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  const { data: meta, error, reload } = useQuery(() => api.meta(), [])
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { const h = () => setPage(route()); window.addEventListener('hashchange', h); return () => window.removeEventListener('hashchange', h) }, [])
  const go = useCallback((p) => { location.hash = '#/' + p; window.scrollTo(0, 0) }, [])
  useEffect(() => { if (meta && page === 'dashboard' && !meta.has_data) go('operations') }, [meta && meta.has_data]) // eslint-disable-line

  if (error && !meta) return <div style={{ padding: 40 }}><Empty icon="alert" title="Cannot reach the application" action={<button className="btn primary" onClick={reload}>Try again</button>}>{error.message}</Empty></div>
  if (!meta) return <div style={{ padding: 40 }}><Skeleton h={500} /></div>

  const cur = NAV.find((n) => n[0] === page) || NAV[0]
  const Page = { dashboard: Dashboard, assistant: Assistant, operations: Operations }[cur[0]]
  return (
    <ToastHost>
      <div className="app">
        <aside className="sidebar" aria-label="Main navigation">
          <div className="brand"><div className="logo">S</div><div><b>Sberbank India</b><span>Corporate Deposits Analytics</span></div></div>
          <div className="nav-label">Workspace</div>
          <nav className="nav">{NAV.map(([k, label, icon]) => (
            <a key={k} href={`#/${k}`} className={cur[0] === k ? 'active' : ''} aria-current={cur[0] === k ? 'page' : undefined}><Icon name={icon} />{label}{k === 'operations' && meta.pending_review > 0 && <span className="badge" title="Refreshes waiting for review">{meta.pending_review}</span>}</a>))}</nav>
          <div className="side-foot">
            <div className="row"><span className={`dot ${meta.llm_offline ? 'amber' : ''}`} /><span>{meta.llm_offline ? 'Rule-based answers' : 'GigaChat connected'}</span></div>
            <div className="row"><Icon name="database" size={15} /><span>{meta.source_mode === 'local' ? 'Saved page snapshots' : 'Live bank websites'}</span></div>
            <div className="row"><Icon name="shield" size={15} /><span>Runs on this computer</span></div>
          </div>
        </aside>
        <div className="main">
          <header className="topbar">
            <div className="grow"><h1>{cur[0] === 'dashboard' ? 'Corporate Fixed Deposit Benchmark' : cur[1]}</h1>
              <div className="sub">{meta.has_data ? <>Sberbank rates as of <b>{meta.as_of || '–'}</b> · dataset updated {fmtDate(meta.updated)} · {meta.banks} sources</> : cur[3]}</div></div>
            {meta.has_data && <a className="btn hide-sm" href={api.reportUrl(JSON.parse(localStorage.getItem('fd.filters.v2') || '{"amount":10}').amount || 10)} download><Icon name="download" size={16} />Excel report</a>}
            <button className="btn ghost icon-only" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} title="Switch theme"><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button>
          </header>
          <main className={cur[0] === 'assistant' ? '' : 'content'}>
            <Page meta={meta} theme={theme} go={go} reloadMeta={reload} />
          </main>
        </div>
        <nav className="mobile-nav" aria-label="Main navigation">{NAV.map(([k, label, icon]) => <a key={k} href={`#/${k}`} className={cur[0] === k ? 'active' : ''}><Icon name={icon} />{label.split(' ')[0]}</a>)}</nav>
      </div>
    </ToastHost>
  )
}
