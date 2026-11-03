async function call(url, opts) {
  let r
  try { r = await fetch(url, opts) } catch { throw new Error('Cannot reach the local server. Is the application still running?') }
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : msg } catch { /* ignore */ }
    const e = new Error(msg); e.status = r.status; throw e
  }
  return r.json()
}
const qs = (o) => Object.entries(o).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
const post = (url, body) => call(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })

export const api = {
  meta: () => call('/api/meta'),
  dashboard: (p) => call('/api/dashboard?' + qs(p)),
  bank: (p) => call('/api/bank?' + qs(p)),
  chat: (question) => post('/api/chat', { question }),
  chatReset: () => call('/api/chat', { method: 'DELETE' }),
  summary: () => call('/api/ops/summary'),
  refresh: () => post('/api/ops/refresh'),
  job: (id, since) => call(`/api/ops/jobs/${id}?since=${since}`),
  run: (id) => call(`/api/ops/runs/${id}`),
  traces: (id) => call(`/api/ops/runs/${id}/traces`),
  approve: (id) => post(`/api/ops/runs/${id}/approve`),
  reject: (id) => post(`/api/ops/runs/${id}/reject`),
  reportUrl: (amount) => `/api/report?amount=${amount}`,
}
