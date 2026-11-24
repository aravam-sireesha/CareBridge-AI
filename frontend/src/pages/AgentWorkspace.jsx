import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, downloadFile, streamPost } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import Layout from '../components/Layout.jsx'
import BotAvatar from '../components/ai/BotAvatar.jsx'
import Markdown from '../components/ai/Markdown.jsx'
import { IconAlertTri, IconArrowUp, IconClock, IconDownload, IconPlay, IconShieldCheck, IconWrench } from '../components/ai/icons.jsx'
import { IconCheck, IconX } from '../components/icons.jsx'

const KIND = { knowledge: 'Retrieve', ml: 'Predict', python: 'Calculate', optimization: 'Optimize' }
const STATUS_TEXT = { awaiting_approval: 'Waiting for your approval', running: 'Running', completed: 'Completed', failed: 'Failed', rejected: 'Rejected' }
const STATUS_TONE = { awaiting_approval: 'warn', running: '', completed: 'ok', failed: 'bad', rejected: '' }
const ms = (n) => (n == null ? '' : n < 950 ? `${n} ms` : `${(n / 1000).toFixed(1)} s`)
const when = (v) => { if (!v) return ''; const d = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(v) ? v : `${v}Z`); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

function StepRow({ step, exec }) {
  const st = exec?.status || (step.allowed === false ? 'denied' : 'pending')
  const cls = st === 'ok' ? 'is-ok' : st === 'running' ? 'is-running' : st === 'error' || st === 'denied' || st === 'skipped' ? 'is-error' : ''
  const icon = st === 'ok' ? <IconCheck className="h-4 w-4" /> : st === 'running' ? <IconClock className="ai-spin h-4 w-4" /> : st === 'error' || st === 'denied' || st === 'skipped' ? <IconX className="h-4 w-4" /> : step.index + 1
  return (
    <li className={`ai-step ${cls}`}>
      <span className="ai-step-dot" aria-hidden="true">{icon}</span>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
          <span className="font-mono text-[13px]">{step.tool}</span>
          <span className="ai-badge">{KIND[step.kind] || step.kind}</span>
          {step.requires_approval && <span className="ai-badge warn" title="This tool can only create proposals for the review queue. A person approves each one there.">Creates proposals</span>}
          {step.admin_only && <span className="ai-badge" title="Only administrators can run this tool.">Admin only</span>}
          {exec?.ms != null && <span className="ai-faint text-xs font-normal">{ms(exec.ms)}{exec.attempts > 1 ? ' · retried once' : ''}</span>}
        </p>
        {step.why && <p className="ai-muted mt-0.5 text-[13px]">{step.why}</p>}
        {step.allowed === false && !exec && <p className="mt-1 text-xs" style={{ color: 'var(--ai-bad)' }}>Your role cannot run this tool. It will be skipped.</p>}
        {exec?.summary && <p className="mt-1.5 text-[13px] leading-relaxed" role="status">{exec.summary}</p>}
        {exec?.error && !exec?.summary && <p className="mt-1.5 text-[13px]" style={{ color: 'var(--ai-bad)' }}>{exec.error}</p>}
      </div>
    </li>
  )
}

export default function AgentWorkspace() {
  const { user } = useAuth()
  const toast = useToast()
  const [goal, setGoal] = useState('')
  const [examples, setExamples] = useState([])
  const [run, setRun] = useState(null)               // the run being shown
  const [exec, setExec] = useState({})               // live per-step progress, keyed by step index
  const [result, setResult] = useState(null)         // {text, validation, proposals} once finished
  const [busy, setBusy] = useState(null)             // 'planning' | 'running' | null
  const [error, setError] = useState(null)
  const [allowProposals, setAllowProposals] = useState(false)
  const [history, setHistory] = useState([])
  const alive = useRef(true)

  const loadHistory = useCallback(() => api.agentRuns().then((r) => alive.current && setHistory(r || [])).catch(() => {}), [])
  useEffect(() => { alive.current = true; api.agentExamples().then((r) => alive.current && setExamples(r.examples || [])).catch(() => {}); loadHistory(); return () => { alive.current = false } }, [loadHistory])

  const reset = () => { setRun(null); setExec({}); setResult(null); setError(null); setAllowProposals(false) }

  const plan = async (g) => {
    const value = (g ?? goal).trim()
    if (value.length < 3 || busy) return
    reset(); setBusy('planning')
    try {
      const r = await api.agentPlan(value)
      setRun(r)
      if (!r.plan.length) setResult({ text: r.answer, validation: null, proposals: [] })
      loadHistory()
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  const approve = async () => {
    if (!run || busy) return
    setBusy('running'); setError(null); setExec({}); setResult(null)
    setRun((r) => ({ ...r, status: 'running' }))
    try {
      await streamPost(`/agent/runs/${run.id}/approve`, { create_proposals: allowProposals }, {
        onEvent: (name, d) => {
          if (name === 'step_start') setExec((e) => ({ ...e, [d.index]: { status: 'running' } }))
          else if (name === 'step_done') setExec((e) => ({ ...e, [d.index]: d }))
          else if (name === 'answer') setResult({ text: d.text, validation: d.validation, proposals: d.proposals || [] })
          else if (name === 'done') setRun((r) => ({ ...r, status: d.status, duration_ms: d.duration_ms }))
          else if (name === 'error') { setError(d.message); setRun((r) => ({ ...r, status: 'failed' })) }
        }
      })
    } catch (e) { setError(e.message); setRun((r) => ({ ...r, status: 'failed' })) } finally { setBusy(null); loadHistory() }
  }

  const reject = async () => {
    try { const r = await api.agentReject(run.id); setRun(r); loadHistory() } catch (e) { toast.error(e.message) }
  }

  const open = async (id) => {
    if (busy) return
    try {
      const r = await api.agentGetRun(id)
      setError(r.error || null); setAllowProposals(false)
      setRun(r)
      setExec(Object.fromEntries((r.steps || []).map((s) => [s.index, { status: s.status, ms: s.ms, attempts: s.attempts, error: s.error }])))
      setResult(r.answer ? { text: r.answer, validation: r.validation, proposals: [] } : null)
    } catch (e) { toast.error(e.message) }
  }

  const report = async () => { try { await downloadFile(`/agent/runs/${run.id}/report`, `carebridge-agent-run-${run.id}.md`) } catch (e) { toast.error(e.message) } }

  const canCreate = run?.status === 'awaiting_approval' && run.plan.some((s) => s.requires_approval && s.allowed) && user.role === 'admin'
  const v = result?.validation
  const planSteps = run?.plan || []
  const finished = run && (run.status === 'completed' || run.status === 'failed')

  return (
    <Layout title="AI agent">
      <div className="ai-root">
        <div className="ai-panel p-4 sm:p-6">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
            <div className="min-w-0">
              <div className="flex items-center gap-4">
                <BotAvatar size={40} />
                <div>
                  <h1 className="font-display text-lg font-semibold sm:text-xl">AI agent workspace</h1>
                  <p className="ai-muted text-sm">Describe a goal. The agent proposes a plan, <strong>you approve it</strong>, then it runs each step and verifies the result.</p>
                </div>
              </div>

              <form className="ai-card mt-5 p-3" onSubmit={(e) => { e.preventDefault(); plan() }}>
                <label htmlFor="agent-goal" className="ai-sr">Goal for the AI agent</label>
                <textarea id="agent-goal" className="ai-field" rows={2} maxLength={1000} value={goal} disabled={!!busy} placeholder="For example: analyse food and medicine shortages and tell me which needs to fund first" onChange={(e) => setGoal(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); plan() } }} />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="ai-chip-row max-w-full" aria-label="Example goals">
                    {examples.slice(0, 4).map((ex) => <button key={ex} type="button" className="ai-chip !whitespace-nowrap !py-1.5 !text-xs" disabled={!!busy} onClick={() => { setGoal(ex); plan(ex) }}>{ex.length > 46 ? `${ex.slice(0, 44)}…` : ex}</button>)}
                  </div>
                  <button type="submit" className="ai-primary" disabled={!!busy || goal.trim().length < 3}>{busy === 'planning' ? 'Planning…' : <>Propose a plan <IconArrowUp className="h-4 w-4" /></>}</button>
                </div>
              </form>

              {error && <p className="ai-note mt-4 flex items-start gap-2" style={{ background: 'var(--ai-bad-bg)', color: 'var(--ai-bad)' }} role="alert"><IconAlertTri className="mt-0.5 h-4 w-4 shrink-0" />{error}</p>}

              {run && (
                <section className="mt-6" aria-label="Plan and progress">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h2 className="font-display text-base font-semibold">{run.status === 'awaiting_approval' ? 'Proposed plan' : 'Plan and progress'}</h2>
                    <span className={`ai-badge ${STATUS_TONE[run.status] || ''}`} role="status">{STATUS_TEXT[run.status] || run.status}{run.duration_ms ? ` · ${ms(run.duration_ms)}` : ''}</span>
                  </div>
                  <p className="ai-muted mb-3 text-sm">Goal: {run.goal}</p>
                  {planSteps.length > 0 && <ol className="ai-steps" aria-label="Steps">{planSteps.map((s) => <StepRow key={s.index} step={s} exec={exec[s.index]} />)}</ol>}

                  {run.status === 'awaiting_approval' && planSteps.length > 0 && (
                    <div className="ai-card mt-4 p-4">
                      <p className="flex items-center gap-2 text-sm font-semibold"><IconShieldCheck className="ai-accent h-4 w-4" />Nothing has run yet</p>
                      <p className="ai-muted mt-1 text-[13px]">Approving runs the {planSteps.filter((s) => s.allowed).length} step(s) above. They only read data, calculate, or create <em>proposals</em>. Nothing is delivered, spent or approved automatically.</p>
                      {canCreate && (
                        <label className="mt-3 flex cursor-pointer items-start gap-2 text-[13px]">
                          <input type="checkbox" className="mt-0.5" checked={allowProposals} onChange={(e) => setAllowProposals(e.target.checked)} />
                          <span>Also add the resulting proposals to the review queue, where an administrator approves each one.</span>
                        </label>
                      )}
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button type="button" className="ai-primary" onClick={approve} disabled={!!busy}><IconPlay className="h-3.5 w-3.5" />Approve and run</button>
                        <button type="button" className="ai-ghost" onClick={reject} disabled={!!busy}>Reject plan</button>
                      </div>
                    </div>
                  )}

                  {result && (
                    <div className="ai-card mt-4 p-4" aria-label="Result">
                      <h3 className="mb-2 font-display text-sm font-semibold">Result</h3>
                      <Markdown text={result.text} />
                      {v && (
                        <div className="mt-3 flex flex-wrap gap-2" aria-label="Verification">
                          <span className={`ai-badge ${v.numbers_ok ? 'ok' : 'warn'}`}>{v.numbers_ok ? 'Every number traced to a tool result' : `Unverified numbers: ${(v.ungrounded || []).join(', ')}`}</span>
                          <span className={`ai-badge ${v.constraints_ok ? 'ok' : 'bad'}`}>{v.constraints_ok ? 'Constraints respected' : 'Constraint violations found'}</span>
                          {v.steps_failed > 0 && <span className="ai-badge warn">{v.steps_failed} step(s) did not complete</span>}
                        </div>
                      )}
                      {(v?.warnings || []).map((w) => <p key={w} className="ai-note mt-2">{w}</p>)}
                      {result.proposals?.length > 0 && <p className="ai-note mt-2" style={{ background: 'var(--ai-accent-soft)', color: 'var(--ai-accent)' }}>{result.proposals.length} proposal(s) were added to the <Link className="font-semibold underline" to="/admin/review">review queue</Link>. An administrator decides on each one.</p>}
                      {finished && <div className="mt-3"><button type="button" className="ai-ghost" onClick={report}><IconDownload className="h-4 w-4" />Download report</button></div>}
                    </div>
                  )}
                </section>
              )}

              {!run && !busy && <p className="ai-muted mt-8 flex items-center justify-center gap-2 text-center text-sm"><IconWrench className="h-4 w-4" />Tools: knowledge retrieval, live data, forecasts, predictions, anomaly checks, exact calculations, optimisation.</p>}
            </div>

            <aside aria-label="Run history" className="min-w-0">
              <h2 className="mb-2 font-display text-sm font-semibold">Recent runs</h2>
              <div className="space-y-2">
                {history.length === 0 && <p className="ai-faint text-xs">Runs you plan appear here, with their audit trail.</p>}
                {history.slice(0, 12).map((h) => (
                  <button key={h.id} type="button" className="ai-card block w-full p-3 text-left transition hover:-translate-y-0.5" aria-current={run?.id === h.id} onClick={() => open(h.id)} disabled={!!busy}>
                    <span className="line-clamp-2 text-[13px] font-medium">{h.goal}</span>
                    <span className="mt-1.5 flex items-center justify-between gap-2"><span className={`ai-badge ${STATUS_TONE[h.status] || ''}`}>{STATUS_TEXT[h.status] || h.status}</span><span className="ai-faint text-[11px]">{when(h.created_at)}</span></span>
                  </button>
                ))}
              </div>
            </aside>
          </div>
        </div>
      </div>
    </Layout>
  )
}
