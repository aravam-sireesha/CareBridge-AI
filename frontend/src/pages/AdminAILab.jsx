import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { ScoreBar } from '../components/AdminParts.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, Field, PageHeader, Pill, Tabs } from '../components/ui.jsx'
import { IconAssistant, IconCheck, IconSpark } from '../components/icons.jsx'

const AGENT_TONE = { retriever: 'sky', analyst: 'violet', optimizer: 'amber' }
const STATUS_TONE = { ok: 'green', error: 'red', denied: 'gray' }
const EXAMPLES = ['How many wrong passwords lock an account?', 'Forecast books demand next month and the risk of a shortage', 'Will need 5 be fulfilled in time?', 'Allocate the books and food fairly across the needs', 'Match donors to the open needs', 'Show suspicious donations', 'What is the average donation?']
const pct = (x) => `${Math.round((x || 0) * 100)}%`

function Check({ ok, label }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold ${ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>{ok ? '✓' : '✕'} {label}</span>
}

function AgentTab() {
  const toast = useToast()
  const [question, setQuestion] = useState('')
  const [propose, setPropose] = useState(false)
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState(null)
  const go = async (q = question) => {
    if (!q.trim()) return
    setBusy(true)
    try { setRun(await api.agentRun(q.trim(), propose)) } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const v = run?.validation
  return (
    <div className="space-y-5">
      <div className="card p-4">
        <Field label="Ask the AI agent" hint="It chooses the tools: retrieval for knowledge, ML for predictions, Python for exact numbers, optimisation for constrained decisions.">
          <textarea className="field" rows={2} aria-label="Ask the AI agent" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Allocate the books fairly across the needs" />
        </Field>
        <div className="mt-3 flex flex-wrap gap-2">{EXAMPLES.map((q) => <button key={q} type="button" onClick={() => { setQuestion(q); go(q) }} className="rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 hover:bg-teal-100">{q}</button>)}</div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-ink-muted"><input type="checkbox" checked={propose} onChange={(e) => setPropose(e.target.checked)} />Add optimiser plans to the review queue as proposals</label>
          <Button loading={busy} disabled={!question.trim()} onClick={() => go()}><IconSpark className="h-4 w-4" /> Run agent</Button>
        </div>
      </div>
      {run && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-xs"><Pill tone="teal">route: {run.route.route}</Pill>{run.route.routes.length > 1 && <Pill tone="gray">+ {run.route.routes.slice(1).join(', ')}</Pill>}<Pill tone="gray">planned by {run.planned_by || 'rules'}</Pill><Pill tone="gray">explained by {run.mode}</Pill><span className="text-ink-muted">{run.duration_ms} ms</span></div>
          <div className="card p-5"><p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Answer</p><p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-ink">{run.answer}</p>
            {run.citations.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{run.citations.map((c) => <span key={c.n} className="rounded-full bg-sky-50 px-2.5 py-1 text-[11px] font-semibold text-sky-700">[{c.n}] {c.title}</span>)}</div>}
            {v && <div className="mt-4 flex flex-wrap gap-2"><Check ok={v.schema_ok} label="structured outputs valid" /><Check ok={v.rag_ok} label="citations supported" /><Check ok={v.constraints_ok} label="constraints respected" /><Check ok={v.numbers_ok} label="numbers come from tools" /></div>}
            {v?.warnings?.map((w) => <p key={w} role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{w}</p>)}
            {run.requires_approval && <p role="status" className="mt-3 rounded-xl bg-violet-50 p-3 text-sm text-violet-800">This is a <strong>proposal</strong>, not an action. A person must approve it.{run.proposals.length > 0 ? <> {run.proposals.length} item(s) are waiting in the <Link to="/admin/review" className="font-semibold underline">review queue</Link>.</> : ' Tick the box above to add it to the review queue.'}</p>}
          </div>
          <div><p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">What the agent did</p>
            <ol className="space-y-2">{run.steps.map((s, i) => (
              <li key={i} className="card p-3.5"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-ink"><span className="mr-2 rounded-md bg-bg px-1.5 py-0.5 text-[11px]">{i + 1}</span>{s.tool}</p><div className="flex items-center gap-1.5"><Pill tone={AGENT_TONE[s.agent]}>{s.agent}</Pill><Pill tone={STATUS_TONE[s.status]}>{s.status}</Pill><span className="text-[11px] text-ink-muted">{s.ms} ms</span></div></div>
                <p className="mt-1 text-xs text-ink-muted">{s.why}</p>{s.error && <p className="mt-1 text-xs text-red-600">{s.error}</p>}
                {s.output && <details className="mt-2"><summary className="cursor-pointer text-xs font-semibold text-sky-600">Show the structured result</summary><pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-bg p-3 text-[11px]">{JSON.stringify(s.output, null, 2)}</pre></details>}
              </li>))}</ol></div>
        </div>
      )}
    </div>
  )
}

function ModelsTab() {
  const toast = useToast()
  const status = useAsync(() => api.aiModels(), [])
  const forecast = useAsync(() => api.aiForecast().catch(() => []), [])
  const anomalies = useAsync(() => api.aiAnomalies().catch(() => null), [])
  const segments = useAsync(() => api.aiSegments().catch(() => null), [])
  const [needId, setNeedId] = useState('')
  const [pred, setPred] = useState(null)
  const [busy, setBusy] = useState(false)
  const train = async () => { setBusy(true); try { const r = await api.aiTrain(); toast[r.trained ? 'success' : 'info'](r.trained ? `Trained: ${r.selected}` : r.reason); status.reload({ silent: true }) } catch (e) { toast.error(e.message) } finally { setBusy(false) } }
  const predict = async () => { try { setPred(await api.aiPredict(needId)) } catch (e) { toast.error(e.message) } }
  const s = status.data
  return (
    <div className="space-y-6">
      {status.error ? <ErrorState message={status.error} /> : status.loading ? <CardSkeleton rows={1} /> : (
        <div className="card p-5"><p className="font-display text-base font-semibold text-ink">Prediction problem</p><p className="text-sm text-ink-muted">{s.problem}</p>
          <div className="mt-3 flex flex-wrap items-center gap-3"><Pill tone={s.trained ? 'green' : 'amber'}>{s.trained ? `model in use: ${s.meta.selected}` : 'baseline in use'}</Pill><span className="text-xs text-ink-muted">{s.real_labelled_needs} real labelled needs (needs {s.min_rows}, with {s.min_per_class} of each outcome)</span><Button variant="ghost" loading={busy} onClick={train}>Train on real data</Button></div>
          <p className="mt-2 text-xs text-ink-muted">{s.note}</p>
          <div className="mt-4 flex flex-wrap items-end gap-3"><Field label="Predict for need number"><input className="field w-32" type="number" min={1} value={needId} onChange={(e) => setNeedId(e.target.value)} aria-label="Need number" /></Field><Button disabled={!needId} onClick={predict}>Predict</Button></div>
          {pred && <div className="mt-3 rounded-xl bg-teal-50/60 p-3 text-sm"><p><strong>{pct(pred.probability)}</strong> chance of fulfilment within 14 days ({pred.risk} risk). Model: {pred.model}.</p>{pred.factors.length > 0 && <p className="mt-1 text-xs text-ink-muted">Main factors: {pred.factors.map((f) => `${f.feature.replace(/_/g, ' ')} (${f.effect >= 0 ? '+' : ''}${Math.round(100 * f.effect)} pts)`).join(', ')}</p>}</div>}
        </div>)}
      <div><p className="mb-2 font-display text-base font-semibold text-ink">Demand forecast (backtested)</p>
        {(forecast.data || []).length === 0 ? <p className="card p-4 text-sm text-ink-muted">Not enough need history to forecast yet.</p> : (
          <div className="card overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-2.5">Category</th><th className="px-4 py-2.5">Method</th><th className="px-4 py-2.5 text-right">Next month</th><th className="px-4 py-2.5 text-right">Beats naive by</th></tr></thead>
            <tbody>{forecast.data.map((f) => <tr key={f.category} className="border-b border-line last:border-0"><td className="px-4 py-2.5 font-semibold capitalize text-ink">{f.category}</td><td className="px-4 py-2.5 text-ink-muted">{f.method}{!f.confident && ' (rough)'}</td><td className="px-4 py-2.5 text-right">{f.forecast}</td><td className="px-4 py-2.5 text-right text-ink-muted">{f.skill_vs_naive != null ? pct(f.skill_vs_naive) : '–'}</td></tr>)}</tbody></table></div>)}</div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-4"><p className="mb-2 text-sm font-semibold text-ink">Unusual donations (Isolation Forest)</p>{(anomalies.data?.donations || []).length === 0 ? <p className="text-xs text-ink-muted">Nothing unusual.</p> : <ul className="space-y-2">{anomalies.data.donations.slice(0, 5).map((d) => <li key={d.donation_id} className="text-xs"><div className="flex justify-between text-ink"><span>Donation {d.donation_id} · amount {d.amount}</span><span className="font-semibold">{d.anomaly_score}</span></div><ScoreBar label="Anomaly score" value={d.anomaly_score} tone="rose" /></li>)}</ul>}</div>
        <div className="card p-4"><p className="mb-2 text-sm font-semibold text-ink">Donor segments (K-Means)</p>{!segments.data || !segments.data.segments?.length ? <p className="text-xs text-ink-muted">{segments.data?.note || 'Not enough donors.'}</p> : <ul className="space-y-1.5">{segments.data.segments.map((g) => <li key={g.segment} className="flex justify-between text-xs"><span className="font-semibold text-ink">{g.name}</span><span className="text-ink-muted">{g.donors} donor(s) · median {g.median_gifts} gift(s)</span></li>)}</ul>}</div>
      </div>
    </div>
  )
}

function OptimizeCard({ kind }) {
  const toast = useToast()
  const [fairness, setFairness] = useState('maxmin')
  const [urgent, setUrgent] = useState(true)
  const [orgCap, setOrgCap] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const isAlloc = kind === 'allocation'
  const run = async (create) => {
    setBusy(true)
    try {
      const body = isAlloc ? { fairness, urgent_first: urgent, org_cap: orgCap ? Number(orgCap) : null, create_proposals: create } : { create_proposals: create }
      const r = await (isAlloc ? api.aiOptimizeAllocation(body) : api.aiOptimizeMatching(body))
      setRes(r)
      if (create) toast.success(`${r.proposals_created.length} proposal(s) added to the review queue.`)
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const m = res?.metrics, b = res?.baseline
  return (
    <div className="card p-5">
      <p className="font-display text-base font-semibold text-ink">{isAlloc ? 'Resource allocation (LP / MILP)' : 'Donor matching (MILP)'}</p>
      <p className="mt-1 text-xs text-ink-muted">{isAlloc ? 'Respects stock, demand, urgency and fairness. Compared with a greedy plan.' : 'Respects donor capacity, covers every need and organization where possible.'}</p>
      {isAlloc && <div className="mt-3 grid gap-3 sm:grid-cols-3"><Field label="Fairness"><select className="field" value={fairness} onChange={(e) => setFairness(e.target.value)} aria-label="Fairness"><option value="maxmin">Max-min (lift the worst-served)</option><option value="floor">Floor (80% of best minimum)</option><option value="none">None (utility only)</option></select></Field>
        <Field label="Max share per organization"><input className="field" type="number" step="0.05" min="0.05" max="1" placeholder="no cap" value={orgCap} onChange={(e) => setOrgCap(e.target.value)} aria-label="Organization cap" /></Field>
        <label className="flex items-end gap-2 pb-2 text-sm text-ink-muted"><input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />Critical needs first</label></div>}
      <div className="mt-3 flex gap-2"><Button loading={busy} onClick={() => run(false)}>Run (preview)</Button>{res && <Button variant="ghost" loading={busy} onClick={() => run(true)}>Add as proposals</Button>}</div>
      {res && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            {(isAlloc ? [['Units allocated', m.units_allocated, b.units_allocated], ['Unmet units', m.unmet_units, b.unmet_units], ['Worst-served coverage', pct(m.min_coverage), pct(b.min_coverage)], ['Fairness index (Jain)', m.jain, b.jain]]
              : [['Needs covered', `${m.needs_covered} of ${m.needs_total}`, `${b.needs_covered}`], ['Organizations covered', `${m.orgs_covered}`, `${b.orgs_covered}`], ['Total fit', m.total_fit, b.total_fit], ['Busiest donor load', m.max_donor_load, '–']]).map(([k, a, g]) => (
              <div key={k} className="rounded-xl bg-teal-50/60 p-3"><p className="text-[11px] text-ink-muted">{k}</p><p className="font-display text-lg font-bold text-teal-700">{a}</p><p className="text-[11px] text-ink-muted">greedy: {g}</p></div>))}
          </div>
          {res.violations.length === 0 ? <Check ok label="every constraint verified independently" /> : <Check ok={false} label={res.violations.join('; ')} />}
          {res.notes.length > 0 && <p className="text-xs text-ink-muted">{res.notes.join(' · ')}</p>}
          <p role="status" className="rounded-xl bg-violet-50 p-3 text-xs text-violet-800">Proposal only. Nothing is approved or delivered until a person decides in the <Link to="/admin/review" className="font-semibold underline">review queue</Link>.{res.proposals_created.length > 0 && ` ${res.proposals_created.length} added.`}</p>
          <ul className="max-h-48 divide-y divide-line overflow-auto rounded-xl border border-line text-xs">{(isAlloc ? res.allocations : res.assignments).slice(0, 30).map((a, i) => <li key={i} className="flex justify-between px-3 py-1.5">{isAlloc ? <><span>Resource {a.supply_id} → need {a.demand_id}</span><span className="font-semibold">{a.units} units</span></> : <><span>Donor {a.donor_id} → need {a.need_id}</span><span className="font-semibold">fit {pct(a.fit)}</span></>}</li>)}</ul>
        </div>)}
    </div>
  )
}

function QualityTab() {
  const toast = useToast()
  const dq = useAsync(() => api.aiDataQuality(), [])
  const [busy, setBusy] = useState(false)
  const repair = async (code) => { setBusy(true); try { await api.aiRepair([code]); toast.success('Repaired.'); dq.reload({ silent: true }) } catch (e) { toast.error(e.message) } finally { setBusy(false) } }
  if (dq.error) return <ErrorState message={dq.error} onRetry={dq.reload} />
  if (dq.loading && !dq.data) return <CardSkeleton rows={2} />
  const d = dq.data
  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4"><div className="flex items-center gap-2"><Check ok={d.ok} label={d.ok ? 'no errors' : `${d.errors} error(s)`} /><span className="text-xs text-ink-muted">{d.warnings} warning(s) · {Object.entries(d.tables).map(([k, v]) => `${v} ${k}`).join(' · ')}</span></div><Button variant="ghost" onClick={() => dq.reload({ silent: true })}>Check again</Button></div>
      {d.issues.length === 0 ? <EmptyState icon={IconCheck} title="Everything checks out" text="Relationships, inventory and calculation rules are consistent." /> : d.issues.map((i) => (
        <div key={i.code} className="card p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><Pill tone={i.severity === 'error' ? 'red' : 'amber'} className="mb-1 capitalize">{i.severity} · {i.category}</Pill><p className="text-sm font-semibold text-ink">{i.title} <span className="font-normal text-ink-muted">({i.count})</span></p></div>{i.auto_fixable && <Button variant="soft" className="px-3 py-1.5 text-xs" loading={busy} onClick={() => repair(i.code)}>Repair automatically</Button>}</div>
          <ul className="mt-2 space-y-1">{i.examples.map((e, k) => <li key={k} className="text-xs text-ink-muted">• {e}</li>)}</ul><p className="mt-2 text-xs text-teal-700">{i.hint}</p></div>))}
    </div>
  )
}

function ReportTab() {
  const rep = useAsync(() => api.aiReport(), [])
  if (rep.loading && !rep.data) return <CardSkeleton rows={2} />
  const r = rep.data
  if (!r?.available) return <EmptyState icon={IconAssistant} title="No benchmark report yet" text={r?.hint || 'Run: python scripts/run_ai_pipeline.py'} />
  const m = r.phase3_need_model
  return (
    <div className="space-y-5">
      <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{r.dataset_note}</p>
      <div className="card overflow-x-auto p-1"><p className="px-3 pt-3 text-sm font-semibold text-ink">Need fulfilment models ({m.data})</p><table className="mt-2 w-full min-w-[560px] text-sm"><thead><tr className="border-b border-line text-left text-xs font-semibold text-ink-muted"><th className="px-3 py-2">Model</th><th className="px-3 py-2 text-right">CV AUC</th><th className="px-3 py-2 text-right">Held-out AUC</th><th className="px-3 py-2 text-right">Calibration error</th></tr></thead>
        <tbody>{m.table.map((t) => <tr key={t.model} className={`border-b border-line last:border-0 ${t.model === m.selected ? 'bg-teal-50/60 font-semibold' : ''}`}><td className="px-3 py-2">{t.model}{t.model === m.selected && ' ✓'}</td><td className="px-3 py-2 text-right">{t.cv_auc_mean}</td><td className="px-3 py-2 text-right">{t.test_roc_auc}</td><td className="px-3 py-2 text-right">{t.test_ece}</td></tr>)}</tbody></table>
        <p className="px-3 pb-3 text-xs text-ink-muted">Best possible on this data: {m.oracle_test_auc}. Selected model must beat the baseline with a significant paired difference.</p></div>
      <div className="card p-4"><p className="mb-2 text-sm font-semibold text-ink">Retrieval accuracy (top 3)</p>{Object.entries(r.phase2_rag).map(([set, methods]) => <p key={set} className="text-xs text-ink-muted"><strong className="text-ink">{set}:</strong> {Object.entries(methods).map(([k, v]) => `${k} ${pct(v.recall_at_3)}`).join(' · ')}</p>)}</div>
    </div>
  )
}

export default function AdminAILab() {
  const [tab, setTab] = useState('agent')
  return (
    <Layout title="AI Lab">
      <PageHeader icon={IconAssistant} tone="violet" title="AI Lab" subtitle="RAG retrieves knowledge, ML predicts, Python calculates, optimisers decide under constraints, and the language model only explains. People approve every consequential decision." />
      <Tabs tabs={[{ key: 'agent', label: 'AI agent' }, { key: 'models', label: 'Predictions & forecasts' }, { key: 'optimize', label: 'Optimisation' }, { key: 'quality', label: 'Data quality' }, { key: 'report', label: 'Benchmark report' }]} value={tab} onChange={setTab} />
      {tab === 'agent' && <AgentTab />}
      {tab === 'models' && <ModelsTab />}
      {tab === 'optimize' && <div className="grid gap-5 lg:grid-cols-2"><OptimizeCard kind="allocation" /><OptimizeCard kind="matching" /></div>}
      {tab === 'quality' && <QualityTab />}
      {tab === 'report' && <ReportTab />}
    </Layout>
  )
}
