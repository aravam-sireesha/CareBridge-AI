import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Pill, Spinner } from '../components/ui.jsx'
import KnowledgeModal from '../components/KnowledgeModal.jsx'
import { HealthCard, SelectionList } from '../components/LiveAnalysis.jsx'
import { IconAssistant, IconBook, IconDatabase, IconPlus, IconRefresh, IconAlert } from '../components/icons.jsx'

export default function KnowledgeCenter() {
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
  const [reindexing, setReindexing] = useState(false)
  const [addOpen, setAddOpen] = useState(false)

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
  return (
    <Layout title="Knowledge & insights">
      <div className="relative mb-5 overflow-hidden rounded-3xl bg-gradient-to-r from-sky-700 via-teal-600 to-teal-500 p-6 text-white shadow-lift">
        <div className="dot-grid absolute inset-0 opacity-40" /><div className="absolute -right-8 -top-10 h-48 w-48 animate-blob bg-white/10" />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-white/15 backdrop-blur"><IconAssistant className="h-7 w-7" /></span>
            <div><h1 className="font-display text-2xl font-semibold">Knowledge &amp; live insights</h1><p className="mt-1 max-w-xl text-sm text-white/85">Manage what the assistant knows and see live organization, need and donor insights. To ask questions, use the AI assistant.</p></div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Link to="/assistant" className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 font-bold text-teal-700 transition hover:bg-teal-50"><IconAssistant className="h-3.5 w-3.5" />Open AI assistant</Link>
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

      <KnowledgeModal open={addOpen} onClose={() => setAddOpen(false)} onSaved={() => status.reload({ silent: true })} />
      <p className="mt-3 flex items-center gap-2 text-xs text-ink-muted"><Pill tone="gray">{s?.mode === 'grounded_generation' ? 'LLM-grounded mode' : 'Retrieval + live analysis'}</Pill>Suggestions only. Review the cited passages and use your own judgment.</p>
    </Layout>
  )
}
