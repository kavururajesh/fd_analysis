import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import Chart from '../components/Chart.jsx'
import Icon from '../components/Icon.jsx'
import { Empty, Md, Pill, useToast } from '../components/ui.jsx'

const ICONS = ['layers', 'target', 'trend', 'shield']
const SUB = ['Chart and short explanation', 'A quick text answer', 'See how size changes the rate', 'Where Sberbank leads']

function Message({ m, theme }) {
  const [steps, setSteps] = useState(false)
  const toast = useToast()
  if (m.role === 'user') return <div className="msg user"><div className="bubble">{m.text}</div></div>
  const copy = () => navigator.clipboard?.writeText(m.text).then(() => toast('Answer copied'))
  return (
    <div className="msg bot">
      <div className="avatar"><Icon name="sparkle" size={18} /></div>
      <div className="bubble-wrap">
        <div className="bubble"><Md text={m.text} /></div>
        {m.chart && (
          <div className="chart-card">
            <div className="ttl">{m.chart.title}</div>
            <Chart spec={m.chart} theme={theme} height={m.chart.kind === 'bar' ? undefined : 360} title={m.chart.title} saveName="assistant_chart" />
            {m.note && <div className="note"><Icon name="sparkle" size={17} /><div><b>What this shows: </b>{m.note}</div></div>}
          </div>)}
        <div className="msg-foot">
          {m.grounded ? <Pill kind="ok" icon="shield">Checked against the data</Pill> : <Pill kind="warn" icon="alert">Please double-check figures: {(m.unverified || []).join(', ')}</Pill>}
          <button className="btn ghost sm" onClick={copy}><Icon name="copy" size={15} />Copy</button>
          {m.steps?.length > 0 && <button className="btn ghost sm" onClick={() => setSteps(!steps)}>{steps ? 'Hide' : 'How was this answered?'}</button>}
        </div>
        {steps && <div className="steps">{m.steps.join('\n')}</div>}
      </div>
    </div>
  )
}

export default function Assistant({ meta, theme, go }) {
  const [chat, setChat] = useState(() => { try { return JSON.parse(sessionStorage.getItem('fd.chat') || '[]') } catch { return [] } })
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null), box = useRef(null)
  useEffect(() => { try { sessionStorage.setItem('fd.chat', JSON.stringify(chat.slice(-30))) } catch { /* ignore */ } if (chat.length || busy) end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [chat, busy])
  useEffect(() => { if (box.current) { box.current.style.height = 'auto'; box.current.style.height = Math.min(140, box.current.scrollHeight) + 'px' } }, [text])

  if (!meta.has_data) return <div className="content"><Empty icon="chat" title="The assistant needs data first" action={<button className="btn primary" onClick={() => go('operations')}><Icon name="refresh" size={16} />Go to Data operations</button>}>Run the first data refresh and approve it. Then you can ask questions here.</Empty></div>

  const send = async (q) => {
    const question = (q ?? text).trim()
    if (!question || busy) return
    setText(''); setBusy(true); setChat((c) => [...c, { role: 'user', text: question }])
    try {
      const a = await api.chat(question)
      setChat((c) => [...c, { role: 'bot', ...a }])
    } catch (e) {
      setChat((c) => [...c, { role: 'bot', text: `Sorry, I could not answer that. ${e.message}`, grounded: true }])
    } finally { setBusy(false); box.current?.focus() }
  }
  const clear = async () => { setChat([]); try { await api.chatReset() } catch { /* ignore */ } }

  return (
    <div className="chat-shell page-in">
      <div className="chat-scroll"><div className="chat-col">
        {chat.length === 0 && (
          <div className="welcome">
            <div className="orb"><Icon name="sparkle" /></div>
            <h2>What would you like to know?</h2>
            <p>Ask about Sberbank's deposit rates against other banks in plain English. Comparisons and trends come with a chart and a short explanation.</p>
            <div className="suggest">{meta.suggestions.map((s, i) => (
              <button key={s} className="sg" onClick={() => send(s)}><span className="ic"><Icon name={ICONS[i % 4]} size={18} /></span><span><b>{s}</b><span>{SUB[i % 4]}</span></span></button>))}</div>
          </div>)}
        {chat.map((m, i) => <Message key={i} m={m} theme={theme} />)}
        {busy && <div className="msg bot"><div className="avatar"><Icon name="sparkle" size={18} /></div><div className="bubble"><span className="typing"><i /><i /><i /></span> <span className="hint">Looking at the data…</span></div></div>}
        <div ref={end} />
      </div></div>
      <div className="composer"><div className="composer-in">
        {chat.length > 0 && <div className="quick-row">{meta.suggestions.map((s) => <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>)}</div>}
        <div className="composer-box">
          <textarea ref={box} rows={1} value={text} placeholder="Ask about Sberbank vs peer deposit rates…" aria-label="Your question" onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
          {chat.length > 0 && <button className="btn ghost icon-only" onClick={clear} title="Clear conversation" aria-label="Clear conversation"><Icon name="trash" /></button>}
          <button className="send" onClick={() => send()} disabled={!text.trim() || busy} aria-label="Send"><Icon name="send" size={19} /></button>
        </div>
        <div className="tiny">Answers use only the current dataset (updated {meta.updated ? meta.updated.slice(0, 16).replace('T', ' ') : '–'}) · Enter to send, Shift+Enter for a new line</div>
      </div></div>
    </div>
  )
}
