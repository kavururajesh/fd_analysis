import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'

let plotlyPromise
const loadPlotly = () => (plotlyPromise ||= import('plotly.js-cartesian-dist-min').then((m) => m.default || m))

const PEERS = ['#2F6FED', '#F59E0B', '#8B5CF6', '#06B6D4', '#EF4444', '#14B8A6', '#EC4899', '#84CC16', '#F97316', '#6366F1', '#64748B', '#0EA5E9', '#A855F7', '#10B981']
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()

function build(spec, c) {
  const traces = []
  let layout = {}
  let height = 380
  const sber = (n) => n === spec.highlight || n === 'Sberbank corporate'
  const hoverFmt = spec.unit === '%' ? '%{y:.2f}%' : '%{y:.2f}'
  if (spec.kind === 'line') {
    let i = 0
    spec.series.forEach((s) => {
      const hl = sber(s.name)
      traces.push({ type: 'scatter', mode: 'lines+markers', x: spec.x, y: s.values, name: s.name, connectgaps: false,
        line: { color: hl ? c.brand : PEERS[i++ % PEERS.length], width: hl ? 5 : 2.2, dash: /\(/.test(s.name) ? 'dot' : 'solid', shape: 'linear' },
        marker: { size: hl ? 9 : 5 }, hovertemplate: `%{x}: ${hoverFmt}<extra>${s.name}</extra>`, opacity: hl ? 1 : 0.9 })
    })
    layout = { xaxis: { type: 'category', title: { text: spec.x_title }, automargin: true }, yaxis: { title: { text: spec.y_title }, ticksuffix: '%', rangemode: 'normal' }, hovermode: 'closest', legend: { orientation: 'h', y: -0.28 } }
    height = 420
  } else if (spec.kind === 'bar') {
    const s = spec.series[0]
    traces.push({ type: 'bar', orientation: 'h', x: s.values, y: spec.x, marker: { color: spec.x.map((n) => (sber(n) ? c.brand : c.bar)), line: { width: 0 } },
      text: s.values.map((v) => `${v.toFixed(2)}%`), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{x:.2f}%<extra></extra>' })
    layout = { yaxis: { autorange: 'reversed', automargin: true }, xaxis: { range: [0, Math.max(1, ...s.values) * 1.16], ticksuffix: '%' }, bargap: 0.28 }
    height = Math.max(260, 60 + 38 * spec.x.length)
  } else if (spec.kind === 'bar_line') {
    spec.series.forEach((s) => {
      if (s.type === 'bar') traces.push({ type: 'bar', x: spec.x, y: s.values, name: s.name, marker: { color: c.brand }, text: s.values.map((v) => (v == null ? '' : `${v.toFixed(2)}%`)), textposition: 'outside', cliponaxis: false })
      else traces.push({ type: 'scatter', mode: 'lines+markers', x: spec.x, y: s.values, name: s.name, text: s.labels, line: { color: PEERS[0], width: 3 }, hovertemplate: '%{text}: %{y:.2f}%<extra></extra>' })
    })
    layout = { xaxis: { type: 'category', title: { text: spec.x_title } }, yaxis: { title: { text: spec.y_title }, ticksuffix: '%' }, legend: { orientation: 'h', y: -0.25 }, bargap: 0.3 }
  } else if (spec.kind === 'pie') {
    const s = spec.series[0]
    const total = s.values.reduce((a, b) => a + b, 0) || 1
    let k = 1
    const fixed = { 'Joint highest': '#7CC79A', 'Peer higher': '#E5646A' }
    const colors = spec.x.map((n) => (/^Sberbank/.test(n) ? c.brand : fixed[n] || PEERS[k++ % PEERS.length]))
    traces.push({ type: 'pie', labels: spec.x, values: s.values, hole: 0.58, sort: false, text: s.values.map((v) => (v / total >= 0.05 ? `${Math.round((v / total) * 100)}%` : '')), textinfo: 'text', textposition: 'inside', insidetextorientation: 'horizontal', textfont: { size: 13, color: '#fff' },
      marker: { colors, line: { color: c.surface, width: 2 } },
      hovertemplate: '%{label}: %{value} (%{percent})<extra></extra>' })
    layout = { showlegend: true, legend: { orientation: 'v', x: 1.02, y: 0.5, font: { size: 12 } }, margin: { l: 10, r: 10, t: 10, b: 10 } }
    height = 300
  } else if (spec.kind === 'heatmap') {
    const z = spec.series.map((s) => s.values)
    const m = Math.max(1, ...z.flat().filter((v) => v != null).map(Math.abs))
    traces.push({ type: 'heatmap', z, x: spec.x, y: spec.series.map((s) => s.name), zmin: -m, zmax: m, xgap: 2, ygap: 2,
      text: z.map((r) => r.map((v) => (v == null ? '' : (v > 0 ? '+' : '') + v.toFixed(2)))), texttemplate: '%{text}', textfont: { size: 12 },
      colorscale: [[0, '#E5646A'], [0.5, c.surface], [1, c.brand]], colorbar: { title: { text: 'pp' }, thickness: 12, len: 0.8 }, hovertemplate: '%{y}, %{x}: %{z:+.2f} pp<extra></extra>' })
    layout = { yaxis: { autorange: 'reversed', type: 'category', automargin: true }, xaxis: { type: 'category', side: 'top' }, margin: { t: 40 } }
    height = 400
  }
  const base = {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', autosize: true,
    font: { family: 'Segoe UI, system-ui, sans-serif', size: 13, color: c.text },
    margin: { l: 56, r: 24, t: 16, b: 56 }, hoverlabel: { font: { family: 'Segoe UI, system-ui, sans-serif' } },
    xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid, ...(layout.xaxis || {}) },
    yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid, ...(layout.yaxis || {}) },
  }
  return { traces, layout: { ...base, ...layout, xaxis: base.xaxis, yaxis: base.yaxis, margin: layout.margin || base.margin }, height }
}

export default function Chart({ spec, theme, onPoint, height: forced, title, saveName = 'chart' }) {
  const ref = useRef(null)
  const [ready, setReady] = useState(false)
  const plotted = useRef(false)

  useEffect(() => {
    let dead = false
    loadPlotly().then((Plotly) => {
      if (dead || !ref.current || !spec) return
      const c = { brand: css('--brand'), text: css('--text'), grid: css('--border'), surface: css('--surface'), bar: css('--chart-bar') || '#8FA39A' }
      const { traces, layout, height } = build(spec, c)
      const h = forced || height
      ref.current.style.height = h + 'px'
      Plotly.react(ref.current, traces, { ...layout, height: h }, { displayModeBar: false, responsive: true })
      if (!plotted.current) {
        plotted.current = true
        ref.current.on('plotly_click', (ev) => {
          const p = ev.points && ev.points[0]
          if (p && ref.current._onPoint) ref.current._onPoint(spec.kind === 'bar' ? p.y : p.x, p)
        })
      }
      ref.current._onPoint = onPoint
      setReady(true)
    })
    return () => { dead = true }
  }, [spec, theme, forced, onPoint])

  useEffect(() => () => { const el = ref.current; if (el) loadPlotly().then((P) => P.purge(el)) }, [])

  const save = () => loadPlotly().then((P) => P.downloadImage(ref.current, { format: 'png', filename: saveName, width: 1400, height: 760, scale: 2 }))
  return (
    <div style={{ position: 'relative' }}>
      {!ready && <div className="skeleton" style={{ height: forced || 320, margin: '12px 8px' }} />}
      <div ref={ref} className="chart" style={{ cursor: onPoint ? 'pointer' : 'default', visibility: ready ? 'visible' : 'hidden', position: ready ? 'static' : 'absolute' }} role="img" aria-label={title || spec?.title} />
      {ready && (
        <button className="btn ghost sm" style={{ position: 'absolute', top: 2, right: 6 }} onClick={save} title="Save chart as image" aria-label="Save chart as image"><Icon name="image" size={16} /></button>
      )}
    </div>
  )
}
