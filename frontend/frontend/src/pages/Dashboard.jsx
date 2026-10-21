import React from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { AreaChart, Donut, HBars } from '../components/Charts.jsx'
import { PageHeader, StatCard, Section, Skeleton, ErrorState, EmptyState, formatMoney, formatDate } from '../components/ui.jsx'
import { IconChildren, IconNeeds, IconDonations, IconPeople, IconAlert, IconShield, IconHand, IconAssistant, IconChart, IconBuilding, IconArrowRight, IconBriefcase } from '../components/icons.jsx'

const URGENCY_COLORS = { critical: '#B13F35', high: '#DC567D', medium: '#D98B1C', low: '#2F9E63', unspecified: '#9BB3B0' }

function QuickLink({ to, icon: Icon, title, text, tone }) {
  return (
    <Link to={to} className="card card-hover group flex items-start gap-3.5 p-4">
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white shadow-card ${tone}`}><Icon className="h-5 w-5" /></span>
      <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-ink">{title}</span><span className="block text-xs text-ink-muted">{text}</span></span>
      <IconArrowRight className="mt-1 h-4 w-4 text-ink-muted transition group-hover:translate-x-1 group-hover:text-teal-600" />
    </Link>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const { data, loading, error, reload } = useAsync(() => api.dashboard(), [])
  const role = user.role
  const t = data?.totals
  const pending = data?.pending_reviews
  const greeting = new Date().getHours() < 12 ? 'Good morning' : new Date().getHours() < 18 ? 'Good afternoon' : 'Good evening'

  const subtitle = {
    admin: 'Platform-wide overview and the AI suggestions waiting for your decision.',
    organization: 'Your children, needs, donations and the AI suggestions for your organization.',
    donor: 'Verified needs you can support and the donations you have made.',
    volunteer: 'Verified needs where your time and skills can make a difference.'
  }[role]

  const stats = []
  if (data) {
    if (role === 'admin' || role === 'organization') stats.push({ label: 'Children', value: t.children, icon: IconChildren, tone: 'teal', hint: 'Registered profiles' })
    stats.push({ label: 'Open needs', value: t.open_needs, icon: IconNeeds, tone: 'sky', hint: `${t.total_needs} needs in total` })
    if (role !== 'volunteer') stats.push({ label: role === 'donor' ? 'My donations' : 'Donations', value: t.donations, icon: IconDonations, tone: 'rose', hint: formatMoney(t.donation_amount) + ' given' })
    if (role === 'admin' || role === 'organization') stats.push({ label: 'Donors & volunteers', value: (t.donors ?? 0) + (t.volunteers ?? 0), icon: IconPeople, tone: 'violet', hint: `${t.donors} donors · ${t.volunteers} volunteers` })
    if (role === 'admin') stats.push({ label: 'Organizations', value: t.organizations, icon: IconBuilding, tone: 'amber', hint: `${t.verified_organizations} verified` })
  }

  const urgencySegments = Object.entries(data?.needs_by_urgency || {}).map(([label, value]) => ({ label, value, color: URGENCY_COLORS[label] || '#9BB3B0' }))
  const monthly = (data?.donations_by_month || []).map((m) => ({ label: m.month.slice(5) + '/' + m.month.slice(2, 4), value: m.amount }))
  const hasDonations = monthly.some((m) => m.value > 0)

  return (
    <Layout title="Dashboard">
      <PageHeader icon={IconChart} title={`${greeting}, ${user.name}!`} subtitle={subtitle}
        actions={<Link to="/assistant" className="btn bg-white/95 text-teal-700 hover:bg-white"><IconAssistant className="h-4 w-4" /> Ask the AI assistant</Link>} />

      {error ? <ErrorState message={error} onRetry={reload} /> : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {loading ? Array.from({ length: 4 }).map((_, i) => <div key={i} className="card p-5"><Skeleton className="mb-3 h-3 w-1/3" /><Skeleton className="h-8 w-1/2" /></div>)
              : stats.map((s) => <StatCard key={s.label} {...s} />)}
          </div>

          {(role === 'admin' || role === 'organization') && !loading && (
            <Section title="Waiting for your decision" className="mt-8">
              <div className="grid gap-4 md:grid-cols-3">
                <QuickLink to="/ai/needs-alerts" icon={IconAlert} tone="from-amber-400 to-amber-600" title={`${pending.need_alerts} need alerts`} text="Urgent, waiting or large needs" />
                <QuickLink to="/ai/matching" icon={IconHand} tone="from-teal-400 to-teal-600" title={`${pending.matches} suggested matches`} text="Donors and volunteers to confirm" />
                {role === 'admin' ? <QuickLink to="/ai/fraud" icon={IconShield} tone="from-rose-400 to-rose-600" title={`${pending.fraud_flags} fraud flags`} text="Unusual donations to review" />
                  : <QuickLink to="/ai/career" icon={IconBriefcase} tone="from-violet-400 to-violet-600" title="Career guidance" text="Recommendations for your children" />}
              </div>
            </Section>
          )}

          <div className="mt-8 grid gap-6 lg:grid-cols-5">
            <div className="card p-5 lg:col-span-3">
              <h2 className="font-display text-base font-semibold">Donations, last 6 months</h2>
              <p className="mb-3 text-xs text-ink-muted">Amount received per month</p>
              {loading ? <Skeleton className="h-44 w-full" /> : hasDonations ? <AreaChart data={monthly} format={formatMoney} />
                : <EmptyState icon={IconDonations} title="No donations yet" text="Recorded donations will appear here as a monthly trend." action={role !== 'volunteer' && <Link to="/donations" className="btn-soft">Record a donation</Link>} />}
            </div>
            <div className="card p-5 lg:col-span-2">
              <h2 className="font-display text-base font-semibold">Needs by urgency</h2>
              <p className="mb-4 text-xs text-ink-muted">How urgent the current needs are</p>
              {loading ? <Skeleton className="h-36 w-full" /> : urgencySegments.length ? <Donut segments={urgencySegments} />
                : <EmptyState icon={IconNeeds} title="No needs yet" text="Add a need to see its urgency here." />}
            </div>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="card p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="font-display text-base font-semibold">Recent needs</h2><Link to="/needs" className="text-sm font-semibold text-sky-600 hover:underline">View all</Link></div>
              {loading ? <Skeleton className="h-32 w-full" /> : data.recent_needs.length ? (
                <ul className="divide-y divide-line">
                  {data.recent_needs.map((n) => (
                    <li key={n.id} className="flex items-center justify-between gap-3 py-3">
                      <div><p className="text-sm font-semibold text-ink">{n.category || 'Uncategorised'}</p><p className="text-xs text-ink-muted">Qty {n.quantity ?? '–'} · {formatDate(n.created_at)}</p></div>
                      <div className="flex gap-2"><StatusBadge status={n.urgency} /><StatusBadge status={n.status} /></div>
                    </li>
                  ))}
                </ul>
              ) : <p className="py-6 text-center text-sm text-ink-muted">No needs to show yet.</p>}
            </div>
            <div className="card p-5">
              <h2 className="font-display text-base font-semibold">Needs by category</h2>
              <p className="mb-4 text-xs text-ink-muted">What is needed most</p>
              {loading ? <Skeleton className="h-32 w-full" /> : data.needs_by_category.length ? <HBars items={data.needs_by_category} />
                : <p className="py-6 text-center text-sm text-ink-muted">Categories appear once needs are added.</p>}
            </div>
          </div>

          {role === 'admin' && data && (
            <div className="card mt-6 flex flex-wrap items-center justify-between gap-3 p-5">
              <div><h2 className="font-display text-base font-semibold">AI assistant knowledge base</h2>
                <p className="text-sm text-ink-muted">{data.knowledge.embedded} of {data.knowledge.entries} entries are searchable.</p></div>
              <Link to="/settings?tab=system" className="btn-soft">Check system health</Link>
            </div>
          )}
        </>
      )}
    </Layout>
  )
}
