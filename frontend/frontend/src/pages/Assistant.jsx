import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Pill, Spinner } from '../components/ui.jsx'
import KnowledgeModal from '../components/KnowledgeModal.jsx'
import { AnalysisView, HealthCard, LiveSourceCard, SelectionList } from '../components/LiveAnalysis.jsx'
import { IconAssistant, IconBook, IconDatabase, IconPlus, IconSend, IconSpark, IconRefresh, IconAlert } from '../components/icons.jsx'

const POLICY_PROMPTS = [
  'What is the volunteer background check policy?',
  'How does fraud detection decide what to flag?',
  'How are donor and volunteer matches confirmed?',
  'Who can see a child’s record?'
]
const LIVE_PROMPTS = {
  admin: ['Which needs are most urgent right now, and which donors should we select?', 'Compare all organizations and tell me who needs help first', 'Which donors have stopped giving, and which needs have no matching donor?', 'How can organizations improve their health and development?'],
  organization: ['How can our organization improve its health and development?', 'Which of our needs are most urgent and which donors fit them?', 'What is our current status?'],
  donor: ['What should I support first, based on my interests?'],
  volunteer: []
}
const suggestedFor = (role) => [...(LIVE_PROMPTS[role] || []), ...POLICY_PROMPTS].slice(0, 6)

const RETRIEVAL_LEAD = /^(Here are the most relevant passages|The answer service is temporarily unavailable)/
/** In retrieval mode the API repeats every passage in the answer text. The source cards already
 *  show them, so only the introductory sentence is displayed to avoid duplicates. */
function displayText(text, mode) {
  if (!text) return ''
  if (mode && mode.startsWith('live')) return text
  if ((mode && mode.startsWith('retrieval')) || RETRIEVAL_LEAD.test(text)) return text.split('\n\n')[0]
  return text
}

function Typing() {
  return <span className="inline-flex items-center gap-1" aria-label="Searching">{[0, 1, 2].map((i) => <span key={i} className="h-2 w-2 animate-dots rounded-full bg-teal-500" style={{ animationDelay: `${i * 0.18}s` }} />)}</span>
}

function Source({ m, index }) {
  const pct = Math.round((m.score || 0) * 100)
  const tone = { high: 'bg-green-50 text-green-700', medium: 'bg-teal-50 text-teal-700', low: 'bg-amber-50 text-amber-700' }[m.label] || 'bg-teal-50 text-teal-700'
  return (
    <div className="rounded-xl border border-line bg-bg/70 p-3.5">
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-ink"><span className="grid h-5 w-5 place-items-center rounded-md bg-sky-100 text-[11px] font-bold text-sky-700">{index + 1}</span>{m.title}</p>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${tone}`}>{m.label ? `${m.label} confidence · ` : ''}{pct}%</span>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">{m.content}</p>
      {m.source && <p className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-sky-600"><IconBook className="h-3.5 w-3.5" />Source: {m.source}</p>}
    </div>
  )
}

function Bubble({ msg, onAsk }) {
  if (msg.role === 'user') return <div className="flex justify-end"><div className="animate-pop max-w-[85%] rounded-2xl rounded-tr-md bg-gradient-to-r from-teal-600 to-sky-600 px-4 py-3 text-sm text-white shadow-card">{msg.text}</div></div>
  return (
    <div className="flex gap-3">
      <span className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-teal-500 to-sky-600 text-white shadow-card"><IconAssistant className="h-5 w-5" /></span>
      <div className="min-w-0 max-w-[92%] animate-pop">
        <div className={`rounded-2xl rounded-tl-md border p-4 shadow-card ${msg.error ? 'border-red-200 bg-red-50' : 'border-line bg-white'}`}>
          {msg.error ? <p className="text-sm text-red-700">{msg.text}</p> : (
            <>
              <p className="whitespace-pre-line text-sm leading-relaxed text-ink">{displayText(msg.text, msg.mode)}</p>
              {msg.mode === 'low_confidence' && <p role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 ring-1 ring-amber-100">Low confidence: these are only the closest passages, not a verified answer.</p>}
              {msg.confidence && msg.mode !== 'low_confidence' && msg.matches?.length > 0 && <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">Answer confidence: {msg.confidence.label} ({Math.round(msg.confidence.value * 100)}%)</p>}
              {msg.focus?.length > 0 && <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700"><IconSpark className="h-3 w-3" />Focused on {msg.focus.join(', ')}</p>}
              {msg.followUpOf && <p className="mt-2 text-[11px] text-ink-muted">Understood as a follow-up to: “{msg.followUpOf}”</p>}
              <AnalysisView analysis={msg.analysis} />
              {msg.records?.length > 0 && <div className="mt-4 space-y-2.5"><p className="text-xs font-semibold text-ink-muted">Live records found</p>{msg.records.map((r, i) => <LiveSourceCard key={i} s={r} />)}</div>}
              {msg.liveSources?.length > 0 && <div className="mt-4 space-y-2.5"><p className="text-xs font-semibold text-ink-muted">Live data used</p>{msg.liveSources.map((s, i) => <LiveSourceCard key={i} s={s} />)}</div>}
              {msg.matches?.length > 0 && <div className="mt-4 space-y-2.5"><p className="text-xs font-semibold text-ink-muted">Sources used</p>{msg.matches.map((m, i) => <Source key={m.id ?? i} m={m} index={i} />)}</div>}
            </>
          )}
        </div>
        {!msg.error && msg.followUps?.length > 0 && <div className="mt-2 flex flex-wrap gap-2 px-1">{msg.followUps.map((q) => <button key={q} type="button" onClick={() => onAsk(q)} className="rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 transition hover:bg-teal-100">{q}</button>)}</div>}
        {!msg.error && <p className="mt-1.5 flex items-center gap-1.5 px-1 text-[11px] text-ink-muted"><IconSpark className="h-3 w-3 text-amber-500" />{msg.mode === 'retrieval_only' ? 'Retrieval mode: showing the most relevant passages from the knowledge base.' : msg.mode === 'live_analysis' ? 'Real-time analysis computed from the database just now.' : 'Grounded answer generated from the sources above.'}</p>}
      </div>
    </div>
  )
}

export default function Assistant() {
  const { user } = useAuth()
  const toast = useToast()
  const status = useAsync(() => api.assistantStatus().catch(() => null), [])
  const hasInsights = user.role !== 'volunteer'
  const insights = useAsync(() => (hasInsights ? api.assistantInsights() : Promise.resolve(null)), [hasInsights])
  const [showLive, setShowLive] = useState(true)
  // Real-time refresh: re-read the database every minute while the page is open.
  useEffect(() => {
    if (!hasInsights) return undefined
    const t = setInterval(() => insights.reload({ silent: true }), 60000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasInsights])
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const endRef = useRef(null)
  const lastUserRef = useRef(null)
  const inputRef = useRef(null)

  // Restore this account's earlier conversation from the database (assistant_messages table).
  useEffect(() => {
    api.assistantHistory().then((rows) => {
      const ordered = [...(rows || [])].reverse().slice(-6)
      setMessages(ordered.flatMap((h) => [
        { role: 'user', text: h.question },
        { role: 'assistant', text: h.answer, matches: (h.sources || []).filter((x) => !x.live), liveSources: (h.sources || []).filter((x) => x.live), mode: String(h.answer).startsWith('Live data as of') ? 'live_analysis' : 'retrieval_only' }
      ]))
    }).catch(() => {})
  }, [])
  useEffect(() => {
    const last = messages[messages.length - 1]
    if (!asking && last?.role === 'assistant' && lastUserRef.current) lastUserRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    else endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, asking])

  const ask = async (text) => {
    const q = (text ?? question).trim()
    if (!q || asking) return
    setMessages((m) => [...m, { role: 'user', text: q }]); setQuestion(''); setAsking(true)
    try {
      const res = await api.askAssistant(q)
      setMessages((m) => [...m, { role: 'assistant', text: res.answer, matches: res.matches, confidence: res.confidence, liveSources: res.live_sources, records: res.records, followUps: res.follow_ups, focus: res.focus, followUpOf: res.follow_up_of, analysis: res.analysis, mode: res.answer_mode }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', error: true, text: e.message }])
    } finally { setAsking(false); inputRef.current?.focus() }
  }
  const reindex = async () => {
    setReindexing(true)
    try { const r = await api.reindexKnowledge(); toast.success(`${r.embedded} entr${r.embedded === 1 ? 'y' : 'ies'} indexed.`); status.reload({ silent: true }) }
    catch (e) { toast.error(e.message) } finally { setReindexing(false) }
  }

  const s = status.data
  const gaps = useAsync(() => (user.role === 'admin' ? api.knowledgeGaps().catch(() => []) : Promise.resolve([])), [user.role])
  const [seeding, setSeeding] = useState(false)
  const loadGuide = async () => {
    setSeeding(true)
    try {
      const r = await api.seedKnowledge()
      toast.success(`CareBridge guide loaded: ${r.added} added, ${r.updated} updated${r.dense_available ? '' : '. Meaning-based search is off until the embedding model is installed; keyword search works.'}`)
      status.reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setSeeding(false) }
  }
  const empty = messages.length === 0
  return (
    <Layout title="AI assistant">
      <div className="relative mb-5 overflow-hidden rounded-3xl bg-gradient-to-r from-sky-700 via-teal-600 to-teal-500 p-6 text-white shadow-lift">
        <div className="dot-grid absolute inset-0 opacity-40" /><div className="absolute -right-8 -top-10 h-48 w-48 animate-blob bg-white/10" />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-white/15 backdrop-blur"><IconAssistant className="h-7 w-7" /></span>
            <div><h1 className="font-display text-2xl font-semibold">CareBridge AI Assistant</h1><p className="mt-1 max-w-xl text-sm text-white/85">Ask about policies, or name an organization, donor or need category for a live analysis. Every answer shows the sources it used, and follow-ups like “and for Little Stars?” work too.</p></div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {s && <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 font-semibold backdrop-blur"><IconDatabase className="h-3.5 w-3.5" />{s.embedded_entries}/{s.knowledge_entries} entries searchable</span>}
            {(user.role === 'admin' || user.role === 'organization') && <button onClick={() => setAddOpen(true)} className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 font-bold text-teal-700 transition hover:bg-teal-50"><IconPlus className="h-3.5 w-3.5" />Add knowledge</button>}
            {user.role === 'admin' && s && <button onClick={loadGuide} disabled={seeding} className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5 font-bold backdrop-blur transition hover:bg-white/25 disabled:opacity-60"><IconBook className="h-3.5 w-3.5" />{seeding ? 'Loading…' : s.guide_entries_loaded < s.guide_entries_available ? `Load CareBridge guide (${s.guide_entries_available} entries)` : 'Refresh CareBridge guide'}</button>}
            {user.role === 'admin' && s && s.needs_indexing > 0 && <button onClick={reindex} disabled={reindexing} className="inline-flex items-center gap-1.5 rounded-full bg-amber-300 px-3 py-1.5 font-bold text-amber-900 transition hover:bg-amber-200 disabled:opacity-60">{reindexing ? <Spinner className="h-3.5 w-3.5" /> : <IconRefresh className="h-3.5 w-3.5" />}Index {s.needs_indexing} new</button>}
          </div>
        </div>
      </div>

      {user.role === 'admin' && gaps.data?.length > 0 && (
        <div className="card mb-5 border-amber-200 p-4">
          <p className="flex items-center gap-2 font-display text-base font-semibold text-ink"><IconAlert className="h-4 w-4 text-amber-600" />Questions the assistant could not answer ({gaps.data.length})</p>
          <p className="mt-1 text-xs text-ink-muted">Each one is a gap in the knowledge base. Add an entry that answers it and the assistant will improve.</p>
          <ul className="mt-3 space-y-1.5">{gaps.data.slice(0, 5).map((g) => <li key={g.question} className="flex items-center justify-between gap-3 rounded-lg bg-bg px-3 py-2 text-sm"><span className="min-w-0 truncate text-ink">{g.question}</span><span className="shrink-0 text-xs text-ink-muted">asked {g.times}×</span></li>)}</ul>
          <button onClick={() => setAddOpen(true)} className="mt-3 rounded-full bg-teal-50 px-3 py-1.5 text-xs font-bold text-teal-700 hover:bg-teal-100">Add a knowledge entry</button>
        </div>
      )}

      {hasInsights && (
        <div className="card mb-5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 font-display text-base font-semibold text-ink"><span className="relative flex h-2.5 w-2.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" /></span>Live from your database
              {insights.data?.generated_at && <span className="text-xs font-normal text-ink-muted">updated {insights.data.generated_at.slice(11, 16)} UTC</span>}</p>
            <div className="flex gap-2"><button onClick={() => insights.reload({ silent: true })} className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-3 py-1.5 text-xs font-bold text-teal-700 hover:bg-teal-100"><IconRefresh className="h-3.5 w-3.5" />Refresh</button>
              <button onClick={() => setShowLive((v) => !v)} className="rounded-full bg-bg px-3 py-1.5 text-xs font-bold text-ink-muted hover:text-teal-700" aria-expanded={showLive}>{showLive ? 'Hide' : 'Show'}</button></div>
          </div>
          {showLive && (insights.error ? <p className="mt-3 flex items-center gap-2 text-sm text-red-600"><IconAlert className="h-4 w-4" />{insights.error}</p> : insights.loading && !insights.data ? <p className="mt-3 text-sm text-ink-muted">Reading the latest data…</p> : insights.data && (
            <div className="mt-4 space-y-4">
              {insights.data.snapshot && <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[['Open needs', insights.data.snapshot.open_needs], ['Urgent', insights.data.snapshot.urgent_open], ['Organizations', insights.data.snapshot.organizations], ['Donors', insights.data.snapshot.donors]].filter(([, v]) => v != null).map(([k, v]) => <div key={k} className="rounded-xl bg-teal-50/60 p-3 text-center"><p className="font-display text-xl font-bold text-teal-700">{v}</p><p className="text-[11px] text-ink-muted">{k}</p></div>)}</div>}
              <div className="grid gap-4 lg:grid-cols-2">
                {insights.data.health?.length > 0 && <div className="space-y-2.5"><p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">{user.role === 'admin' ? 'Organizations, lowest health first' : 'Your organization'}</p>{insights.data.health.slice(0, user.role === 'admin' ? 3 : 1).map((h) => <HealthCard key={h.organization_id} h={h} compact />)}</div>}
                <SelectionList items={insights.data.selection?.slice(0, 3)} title={user.role === 'donor' ? 'Needs that match your interests' : 'Needs and donors to act on first'} />
              </div>
              {!insights.data.health?.length && !insights.data.selection?.length && <p className="text-sm text-ink-muted">No open needs or organizations to analyse yet.</p>}
            </div>))}
        </div>
      )}

      <div className="card flex h-[calc(100vh-19rem)] min-h-[26rem] flex-col overflow-hidden">
        <div className="flex-1 space-y-5 overflow-y-auto bg-gradient-to-b from-teal-50/40 to-white p-4 sm:p-6">
          {!empty && (
            <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-white/80 p-3 ring-1 ring-line">
              <span className="text-sm font-semibold text-ink">How can I help today?</span>
              {suggestedFor(user.role).slice(0, 2).map((q) => <button key={q} onClick={() => ask(q)} className="rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 transition hover:bg-teal-100">{q}</button>)}
            </div>
          )}
          {empty && !asking && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <span className="grid h-16 w-16 place-items-center rounded-3xl bg-gradient-to-br from-teal-50 to-sky-100 text-teal-600"><IconAssistant className="h-8 w-8" /></span>
              <p className="mt-4 font-display text-lg font-semibold text-ink">How can I help today?</p>
              <p className="mt-1 max-w-md text-sm text-ink-muted">Try one of these, or type your own question.</p>
              {s && s.knowledge_entries === 0 && <p className="mt-3 max-w-md rounded-xl bg-amber-50 p-3 text-xs text-amber-800">The knowledge base is empty. An administrator can add entries (see <strong>Settings → Knowledge base</strong>).</p>}
              <div className="mt-5 grid w-full max-w-xl gap-2.5 sm:grid-cols-2">
                {suggestedFor(user.role).map((q) => <button key={q} onClick={() => ask(q)} className="rounded-xl border border-line bg-white p-3.5 text-left text-[13px] font-medium text-ink-muted shadow-card transition hover:-translate-y-0.5 hover:border-teal-300 hover:text-teal-700 hover:shadow-lift">{q}</button>)}
              </div>
            </div>
          )}
          {messages.map((m, i) => {
            const isLastUser = m.role === 'user' && !messages.slice(i + 1).some((x) => x.role === 'user')
            return <div key={i} ref={isLastUser ? lastUserRef : null} className="scroll-mt-2"><Bubble msg={m} onAsk={ask} /></div>
          })}
          {asking && (
            <div className="flex gap-3"><span className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-teal-500 to-sky-600 text-white"><IconAssistant className="h-5 w-5" /></span>
              <div className="flex items-center gap-3 rounded-2xl rounded-tl-md border border-line bg-white px-4 py-3.5 text-sm text-ink-muted shadow-card"><Typing />Searching the knowledge base…</div></div>
          )}
          <div ref={endRef} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); ask() }} className="flex items-center gap-2 border-t border-line bg-white p-3">
          <input ref={inputRef} className="field" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={4000} placeholder="Ask a question about CareBridge…" aria-label="Your question" />
          <button type="submit" disabled={asking || !question.trim()} className="btn-primary h-[42px] shrink-0 px-5">{asking ? <Spinner /> : <IconSend className="h-4 w-4" />}<span>Send</span></button>
        </form>
      </div>
      <KnowledgeModal open={addOpen} onClose={() => setAddOpen(false)} onSaved={() => status.reload({ silent: true })} />
      <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><Pill tone="gray">{s?.mode === 'grounded_generation' ? 'LLM-grounded mode' : 'Retrieval + live analysis'}</Pill>Suggestions only. Review the cited passages and use your own judgment.</p>
    </Layout>
  )
}
