import React from 'react'
import { Link } from 'react-router-dom'
import {
  IconArrowRight, IconAssistant, IconBook, IconBriefcase, IconBuilding, IconChart, IconCheck, IconChildren, IconDatabase,
  IconDonations, IconHand, IconPeople, IconSettings, IconShield, IconSpark
} from './icons.jsx'

const ICONS = {
  children: IconChildren, organizations: IconBuilding, donors: IconDonations, volunteers: IconPeople, resources: IconDatabase,
  predict: IconChart, fraud: IconShield, matching: IconPeople, career: IconBriefcase, assistant: IconAssistant, review: IconCheck,
  connect: IconHand, allocate: IconDatabase, guidance: IconBook, coordinate: IconBuilding, timely: IconChildren,
  efficient: IconSettings, trust: IconShield, impact: IconDonations
}
const PERCENT = new Set(['timely', 'efficient', 'trust'])

// Full class names so Tailwind keeps them.
const STYLE = {
  input: { n: 1, box: 'border-teal-200 bg-teal-50/60', num: 'bg-teal-700', title: 'text-teal-800', icon: 'text-teal-600', badge: 'bg-teal-100 text-teal-700' },
  processing: { n: 2, box: 'border-violet-200 bg-violet-50', num: 'bg-violet-600', title: 'text-violet-800', icon: 'text-violet-600', badge: 'bg-violet-100 text-violet-700' },
  decision: { n: 3, box: 'border-sky-200 bg-sky-50', num: 'bg-sky-600', title: 'text-sky-800', icon: 'text-sky-600', badge: 'bg-sky-100 text-sky-700' },
  action: { n: 4, box: 'border-green-200 bg-green-50', num: 'bg-green-700', title: 'text-green-800', icon: 'text-green-600', badge: 'bg-green-100 text-green-700' },
  outcomes: { n: 5, box: 'border-amber-200 bg-amber-50', num: 'bg-amber-700', title: 'text-amber-800', icon: 'text-amber-600', badge: 'bg-amber-100 text-amber-700' }
}

/** The same five stages as the project workflow: public description, no numbers. */
export const STATIC_STAGES = [
  { key: 'input', title: 'Data Input', items: [
    { key: 'children', label: 'Children', detail: 'Needs & profile' }, { key: 'organizations', label: 'Organizations', detail: 'Programs & resources' },
    { key: 'donors', label: 'Donors', detail: 'Interests & support' }, { key: 'volunteers', label: 'Volunteers', detail: 'Skills & availability' },
    { key: 'resources', label: 'Resources', detail: 'Materials & services' }] },
  { key: 'processing', title: 'AI Processing & Analysis', items: [
    { key: 'predict', label: 'Predictive need analysis', detail: 'Find future needs' }, { key: 'fraud', label: 'Fraud / anomaly detection', detail: 'Identify suspicious requests' },
    { key: 'matching', label: 'Donor & volunteer matching', detail: 'Skills + interests + availability + location' }, { key: 'career', label: 'Career guidance', detail: 'Personalized learning & career paths' }] },
  { key: 'decision', title: 'Decision & Collaboration', items: [
    { key: 'assistant', label: 'AI Assistant (RAG-based)', detail: 'Relevant information from the knowledge base' }, { key: 'review', label: 'Administrator', detail: 'Reviews & approves' }] },
  { key: 'action', title: 'Action & Support', items: [
    { key: 'connect', label: 'Connect donors & volunteers', detail: 'For specific needs' }, { key: 'allocate', label: 'Allocate resources', detail: 'Books, food, health, etc.' },
    { key: 'guidance', label: 'Provide guidance', detail: 'Education & career' }, { key: 'coordinate', label: 'Coordinate with organizations', detail: 'Track & manage' }] },
  { key: 'outcomes', title: 'Better Outcomes', items: [
    { key: 'timely', label: 'Timely support for children' }, { key: 'efficient', label: 'Efficient resource utilization' },
    { key: 'trust', label: 'Transparency & trust' }, { key: 'impact', label: 'Stronger social impact' }] }
]

function Item({ item, style }) {
  const Icon = ICONS[item.key] || IconSpark
  const hasCount = item.count !== undefined && item.count !== null
  const inner = (
    <div className="flex items-center gap-3 rounded-xl bg-white p-2.5 ring-1 ring-line transition group-hover:ring-teal-300">
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-bg ${style.icon}`}><Icon className="h-5 w-5" /></span>
      <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold leading-tight text-ink">{item.label}</span>{item.detail && <span className="block text-[11px] leading-snug text-ink-muted">{item.detail}</span>}</span>
      {hasCount && <span className={`shrink-0 rounded-full px-2.5 py-1 font-display text-sm font-bold ${style.badge}`} aria-label={`${item.label}: ${item.count}${PERCENT.has(item.key) ? ' percent' : ''}`}>{item.count}{PERCENT.has(item.key) ? '%' : ''}</span>}
    </div>
  )
  return item.to ? <Link to={item.to} className="group block">{inner}</Link> : <div className="group">{inner}</div>
}

/** Five-stage pipeline. Pass live `stages` from /admin/workflow, or leave empty for the public description. */
export default function WorkflowBoard({ stages = STATIC_STAGES }) {
  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr_auto_1fr]" aria-label="CareBridge AI end to end workflow">
      {stages.map((stage, i) => {
        const s = STYLE[stage.key]
        return (
          <React.Fragment key={stage.key}>
            <section className={`rounded-2xl border p-3 ${s.box}`} aria-label={`Stage ${s.n}: ${stage.title}`}>
              <h3 className={`mb-3 flex items-center gap-2 font-display text-sm font-bold ${s.title}`}><span className={`grid h-6 w-6 place-items-center rounded-full text-xs text-white ${s.num}`}>{s.n}</span>{stage.title}</h3>
              <div className="space-y-2">{stage.items.map((it) => <Item key={it.key} item={it} style={s} />)}</div>
            </section>
            {i < stages.length - 1 && <div className="hidden items-center text-ink-muted/60 lg:flex" aria-hidden="true"><IconArrowRight className="h-6 w-6" /></div>}
          </React.Fragment>
        )
      })}
    </div>
  )
}
