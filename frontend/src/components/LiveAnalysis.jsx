import React from 'react'
import { Pill } from './ui.jsx'
import { LevelPill, Reasons, ScoreBar } from './AdminParts.jsx'
import { IconBuilding, IconDatabase, IconDonations, IconSpark } from './icons.jsx'

const money = (n) => Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })

const gradeTone = (g) => ({ Thriving: 'green', Healthy: 'teal', 'Needs attention': 'amber', 'At risk': 'red' }[g] || 'gray')
const gradeStroke = (g) => ({ Thriving: 'stroke-green-500', Healthy: 'stroke-teal-500', 'Needs attention': 'stroke-amber-500', 'At risk': 'stroke-red-500' }[g] || 'stroke-teal-500')
const priorityTone = { high: 'red', medium: 'amber', low: 'sky' }

export function ScoreRing({ score, grade, size = 84 }) {
  const r = 34, c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} viewBox="0 0 84 84" role="img" aria-label={`Health score ${score} out of 100`}>
      <circle cx="42" cy="42" r={r} fill="none" strokeWidth="9" className="stroke-line" />
      <circle cx="42" cy="42" r={r} fill="none" strokeWidth="9" strokeLinecap="round" strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 42 42)" className={gradeStroke(grade)} />
      <text x="42" y="47" textAnchor="middle" fontSize="20" fontWeight="700" className="fill-ink font-display">{score}</text>
    </svg>
  )
}

export function HealthCard({ h, compact = false }) {
  const recs = compact ? h.recommendations.slice(0, 3) : h.recommendations
  const m = h.metrics
  return (
    <div className="card p-4">
      <div className="flex items-center gap-4">
        <ScoreRing score={h.score} grade={h.grade} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink"><IconBuilding className="h-4 w-4 text-teal-600" />{h.name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2"><Pill tone={gradeTone(h.grade)}>{h.grade}</Pill><span className="text-xs text-ink-muted">{m.open_needs} open · {m.urgent_open} urgent · {m.donations_30d} gift(s) in 30 days</span></div>
        </div>
      </div>
      <p className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Suggestions for healthy development</p>
      <ul className="space-y-2">{recs.map((r, i) => (
        <li key={i} className="flex gap-2.5 rounded-xl bg-bg/70 p-2.5">
          <Pill tone={priorityTone[r.priority]} className="h-fit capitalize">{r.priority}</Pill>
          <div><p className="text-[13px] font-semibold text-ink">{r.title}</p><p className="text-xs leading-relaxed text-ink-muted">{r.detail}</p></div>
        </li>))}</ul>
    </div>
  )
}

export function SelectionList({ items, title = 'Needs to act on first' }) {
  if (!items?.length) return null
  return (
    <div>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">{title}</p>
      <div className="space-y-2.5">{items.map((s, i) => (
        <div key={`${s.need_id}-${i}`} className="card p-3.5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0"><p className="text-sm font-semibold text-ink"><span className="mr-2 rounded-md bg-sky-100 px-1.5 py-0.5 text-[11px] font-bold text-sky-700">{i + 1}</span>{s.category || `Need ${s.need_id}`}</p><p className="mt-0.5 text-xs text-ink-muted">{s.organization || 'Organization'}{s.organization_health != null ? ` · health ${s.organization_health}/100` : ''} · qty {s.quantity ?? '–'}</p></div>
            <LevelPill level={s.priority_level} />
          </div>
          <div className="mt-2"><ScoreBar label="Selection score (urgency + organization data)" value={s.selection_score} tone="rose" /></div>
          <Reasons items={s.reasons} />
          {s.donors?.length > 0 && (
            <div className="mt-3 rounded-xl bg-teal-50/60 p-2.5">
              <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-teal-700"><IconDonations className="h-3.5 w-3.5" />Best-fit donors</p>
              <ul className="space-y-1.5">{s.donors.map((d) => <li key={d.donor_id} className="flex items-center justify-between gap-3 text-xs"><span className="min-w-0 truncate font-medium text-ink">{d.label}</span><span className="shrink-0 font-semibold text-teal-700">fit {Math.round(d.fit_score * 100)}%</span></li>)}</ul>
            </div>
          )}
        </div>))}</div>
    </div>
  )
}

export function DonorInsights({ di }) {
  if (!di) return null
  const stat = [['Donors', di.total], ['Active (90 days)', di.active_90d], ['Lapsed', di.lapsed_count], ['Never given', di.never_given]]
  return (
    <div className="card p-4">
      <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><IconDonations className="h-4 w-4 text-rose-500" />Donor analytics</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{stat.map(([k, v]) => <div key={k} className="rounded-xl bg-teal-50/60 p-2.5 text-center"><p className="font-display text-lg font-bold text-teal-700">{v}</p><p className="text-[11px] text-ink-muted">{k}</p></div>)}</div>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {di.top_donors.length > 0 && <div><p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Top donors</p><ul className="space-y-1">{di.top_donors.map((r) => <li key={r.donor_id} className="flex justify-between gap-3 text-xs"><span className="truncate text-ink">{r.label}</span><span className="shrink-0 font-semibold text-teal-700">{money(r.total)}</span></li>)}</ul></div>}
        {di.lapsed.length > 0 && <div><p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Lapsed, worth contacting</p><ul className="space-y-1">{di.lapsed.map((r) => <li key={r.donor_id} className="flex justify-between gap-3 text-xs"><span className="truncate text-ink">{r.label}</span><span className="shrink-0 text-ink-muted">{r.days_since_last} days ago</span></li>)}</ul></div>}
      </div>
      {di.interest_gaps.length > 0 && <div className="mt-3 rounded-xl bg-amber-50 p-3"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-amber-700">Needs with no matching donor</p><ul className="space-y-1">{di.interest_gaps.map((g, i) => <li key={i} className="text-xs text-ink-muted"><strong className="text-ink">{g.category}</strong> · {g.urgency}{g.organization ? ` · ${g.organization}` : ''} · {g.matching_donors} matching donor(s)</li>)}</ul><p className="mt-1.5 text-[11px] text-ink-muted">Invite donors who care about these causes, or add their interests to donor records.</p></div>}
    </div>
  )
}

export function DonorProfile({ p }) {
  const tone = { active: 'green', lapsed: 'amber', new: 'sky' }[p.status] || 'gray'
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="flex items-center gap-2 text-sm font-semibold text-ink"><IconDonations className="h-4 w-4 text-rose-500" />{p.label}</p><Pill tone={tone} className="capitalize">{p.status}</Pill></div>
      <p className="mt-1 text-xs text-ink-muted">{p.preferences || 'No interests recorded'}{p.location ? ` · ${p.location}` : ''}</p>
      <p className="mt-2 text-xs text-ink-muted"><strong className="text-ink">{p.gifts}</strong> gift(s) · <strong className="text-ink">{money(p.total_given)}</strong> given{p.days_since_last != null ? ` · last ${p.days_since_last} days ago` : ''}{p.categories_given.length ? ` · gave to ${p.categories_given.join(', ')}` : ''}</p>
      {p.best_needs.length > 0 && <div className="mt-2.5 rounded-xl bg-teal-50/60 p-2.5"><p className="mb-1 text-[11px] font-semibold text-teal-700">Best open needs for this donor</p><ul className="space-y-1">{p.best_needs.map((b) => <li key={b.need_id} className="flex justify-between gap-3 text-xs"><span className="truncate text-ink">{b.category}{b.organization ? ` · ${b.organization}` : ''}</span><span className="shrink-0 font-semibold text-teal-700">fit {Math.round(b.fit_score * 100)}%</span></li>)}</ul></div>}
    </div>
  )
}

export function AnalysisView({ analysis }) {
  if (!analysis) return null
  return (
    <div className="mt-4 space-y-4">
      {analysis.health?.length > 0 && (
        <div><p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Organization health</p>
          <div className="space-y-2.5">{analysis.health.slice(0, 4).map((h) => <HealthCard key={h.organization_id} h={h} compact />)}</div></div>
      )}
      {analysis.donor_profiles?.map((p) => <DonorProfile key={p.donor_id} p={p} />)}
      <DonorInsights di={analysis.donor_insights} />
      <SelectionList items={analysis.selection} />
    </div>
  )
}

export function LiveSourceCard({ s }) {
  const record = !!s.kind
  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50/50 p-3">
      <div className="flex items-start justify-between gap-3"><p className="flex items-center gap-2 text-sm font-semibold text-ink"><IconDatabase className="h-4 w-4 text-teal-600" />{s.title}</p><span className="shrink-0 rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-bold text-green-700">{record ? 'LIVE RECORD' : 'LIVE'}</span></div>
      <p className="mt-1.5 text-xs text-ink-muted">{s.content}</p>
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-sky-600"><IconSpark className="h-3 w-3" />Source: {s.source}</p>
    </div>
  )
}
