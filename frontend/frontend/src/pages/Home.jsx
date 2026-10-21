import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Logo from '../components/Logo.jsx'
import { ThemeToggle } from '../components/ProfileMenu.jsx'
import WorkflowBoard from '../components/WorkflowBoard.jsx'
import '../landing.css'
import { Button, Pill } from '../components/ui.jsx'
import {
  IconArrowRight, IconBook, IconBuilding, IconCheck, IconDonations, IconHand, IconLock, IconMail, IconMenu, IconNeeds, IconPeople, IconShield, IconSpark, IconX
} from '../components/icons.jsx'

const NAV = [['home', 'Home'], ['about', 'About Us'], ['how', 'How It Works'], ['organizations', 'Organizations'], ['impact', 'Our Impact'], ['contact', 'Contact']]
const CONTACT_EMAIL = import.meta.env?.VITE_CONTACT_EMAIL || ''
const NEEDS = [
  { name: 'Food', text: 'Meals, groceries and kitchen supplies.', color: 'bg-amber-50 text-amber-700' },
  { name: 'Clothing', text: 'Uniforms, winter wear and bedding.', color: 'bg-sky-50 text-sky-700' },
  { name: 'Education', text: 'Books, fees and learning materials.', color: 'bg-teal-50 text-teal-700' },
  { name: 'Healthcare', text: 'Check-ups, medicines and hygiene.', color: 'bg-rose-50 text-rose-600' }
]
const STEPS = [
  ['Organizations are verified', 'An administrator checks each child-care organization before its needs become public.'],
  ['Needs are published', 'Verified organizations post what they need, with quantity and urgency.'],
  ['People give and volunteer', 'Donors and volunteers find a need that suits them, with AI suggestions that a person reviews.'],
  ['Every step is tracked', 'Donations and decisions are recorded so supporters can see what happened.']
]
const STATS = [['verified_organizations', 'Verified organizations'], ['open_needs', 'Open needs'], ['fulfilled_needs', 'Needs fulfilled'], ['confirmed_donations', 'Donations received'], ['registered_donors', 'Donors'], ['registered_volunteers', 'Volunteers'], ['beneficiaries_supported', 'Children supported by fulfilled needs']]
const URGENCY_TONE = { critical: 'red', high: 'amber', medium: 'sky', low: 'green' }

function Unavailable({ what, onRetry }) {
  return (
    <div role="status" className="card flex flex-wrap items-center justify-between gap-3 p-5 text-sm text-ink-muted">
      <span>{what} can’t be loaded right now. We never show estimated numbers.</span>
      <Button variant="ghost" onClick={onRetry}>Try again</Button>
    </div>
  )
}

function SectionHead({ eyebrow, title, text }) {
  return (
    <div>
      <p className="text-sm font-semibold uppercase tracking-wide text-teal-700">{eyebrow}</p>
      {title && <h2 className="mt-2 font-display text-3xl font-bold text-ink">{title}</h2>}
      <span aria-hidden="true" className="mt-3 block h-1 w-14 rounded-full bg-teal-600" />
      {text && <p className="mt-4 max-w-3xl text-ink-muted">{text}</p>}
    </div>
  )
}

/** Notice bar built only from real, open needs of verified organizations. Hidden while loading, on error, or when empty. */
function NoticeBar({ needs }) {
  const items = (needs.data || []).slice(0, 3)
  if (!items.length) return null
  return (
    <div role="region" aria-label="Urgent needs" className="border-b border-line bg-amber-50">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 text-sm sm:px-8">
        <span className="inline-flex items-center gap-1.5 font-semibold text-amber-700"><IconNeeds className="h-4 w-4" /> Urgent needs</span>
        <ul className="flex min-w-0 flex-1 flex-wrap gap-x-6 gap-y-1">
          {items.map((n) => (
            <li key={n.id} className="min-w-0 truncate text-ink"><a href="#organizations" className="hover:underline">{n.title}<span className="text-ink-muted"> · {n.organization}</span></a></li>
          ))}
        </ul>
        <a href="#organizations" className="font-semibold text-teal-700 hover:underline">View all</a>
      </div>
    </div>
  )
}

const QUICK = [
  { icon: IconDonations, title: 'Donate', text: 'Choose a verified need.', to: '/register?role=donor' },
  { icon: IconHand, title: 'Volunteer', text: 'Share your skills and time.', to: '/register?role=volunteer' },
  { icon: IconBuilding, title: 'Organizations', text: 'See who is verified.', href: '#organizations' },
  { icon: IconBook, title: 'How it works', text: 'Read the beginner guide.', to: '/guide' }
]

export default function Home() {
  const { isAuthenticated, user } = useAuth()
  const [menu, setMenu] = useState(false)
  const stats = useAsync(() => api.publicStats(), [])
  const needs = useAsync(() => api.publicNeeds(), [])
  const orgs = useAsync(() => api.publicOrganizations(), [])
  const dash = user?.role === 'admin' ? '/admin' : '/dashboard'

  return (
    <div className="lp text-ink">
      <div className="lp-bg" aria-hidden="true">
        <picture>
          <source srcSet="/images/carebridge-hero.webp" type="image/webp" />
          <img src="/images/carebridge-hero.jpg" alt="" width="1672" height="941" fetchpriority="high" decoding="async" />
        </picture>
      </div>

      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:font-semibold focus:text-teal-800 focus:shadow-lift">Skip to main content</a>

      <header className="lp-header">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
          <a href="#home" aria-label="CareBridge AI home"><Logo size={36} light showTagline /></a>
          <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
            {NAV.map(([id, label]) => <a key={id} href={`#${id}`} className="lp-nav-link">{label}</a>)}
          </nav>
          <div className="flex items-center gap-1.5 sm:gap-2">
            <ThemeToggle className="lp-icon-btn rounded-xl p-2.5 transition" />
            {isAuthenticated
              ? <Link to={dash} className="lp-btn lp-btn-primary lp-btn-sm">Open dashboard</Link>
              : <><Link to="/register" className="lp-btn lp-btn-secondary lp-btn-sm lp-btn-register">Register</Link><Link to="/login" className="lp-btn lp-btn-primary lp-btn-sm">Login</Link></>}
            <button type="button" className="lp-icon-btn rounded-xl p-2.5 transition lg:hidden" aria-label={menu ? 'Close menu' : 'Open menu'} aria-expanded={menu} aria-controls="mobile-menu" onClick={() => setMenu((m) => !m)}>{menu ? <IconX /> : <IconMenu />}</button>
          </div>
        </div>
        {menu && (
          <nav id="mobile-menu" aria-label="Mobile" className="lp-header-menu px-4 py-2 lg:hidden">
            {NAV.map(([id, label]) => <a key={id} href={`#${id}`} onClick={() => setMenu(false)} className="lp-nav-link py-2.5">{label}</a>)}
          </nav>
        )}
      </header>

      <main id="main">
        <section id="home" aria-labelledby="hero-title" className="lp-hero scroll-mt-20">
          <div className="lp-hero-inner">
            <div className="lp-hero-copy">
              <p className="lp-eyebrow"><IconShield className="h-4 w-4" /> Verified organizations only</p>
              <h1 id="hero-title" className="lp-title">Connecting Compassion with Every Need.</h1>
              <p className="lp-lead">We connect verified child-care organizations with donors and volunteers, openly and transparently.</p>
              <div className="lp-actions">
                <Link to={isAuthenticated ? '/needs' : '/login'} className="lp-btn lp-btn-primary">Explore Needs <IconArrowRight className="h-4 w-4" /></Link>
                <Link to="/register?role=volunteer" className="lp-btn lp-btn-secondary">Become a Volunteer</Link>
              </div>
            </div>
          </div>
        </section>

        <div className="lp-sheet-first">
          <NoticeBar needs={needs} />
        <section aria-label="Quick links" className="lp-sheet px-4 pb-2 pt-10 sm:px-8">
          <ul className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {QUICK.map(({ icon: Icon, title, text, to, href }) => {
              const inner = (<><span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-teal-50 text-teal-700"><Icon className="h-5 w-5" /></span><span><span className="block font-display font-bold text-ink">{title}</span><span className="block text-sm text-ink-muted">{text}</span></span></>)
              const cls = 'card card-hover flex items-center gap-3 p-4'
              return <li key={title}>{to ? <Link to={to} className={cls}>{inner}</Link> : <a href={href} className={cls}>{inner}</a>}</li>
            })}
          </ul>
        </section>
        </div>

        <section id="about" className="lp-sheet scroll-mt-20 px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="About CareBridge AI" title="One place to coordinate care, resources and kindness." text="Child-care organizations list what they need. Donors and volunteers see verified needs and choose how to help. AI suggests matches and flags anything unusual, and a person always makes the decision." />
          </div>
        </section>

        <section id="how" className="lp-sheet-alt scroll-mt-20 border-y border-line px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="How it works" title="How the platform works" />
            <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map(([title, text], i) => (
                <li key={title} className="card card-hover p-5"><span className="grid h-8 w-8 place-items-center rounded-full bg-teal-700 text-sm font-bold text-white">{i + 1}</span><h3 className="mt-3 font-semibold text-ink">{title}</h3><p className="mt-1 text-sm text-ink-muted">{text}</p></li>
              ))}
            </ol>
            <h3 className="mt-14 font-display text-2xl font-bold text-ink">From a child&apos;s need to a better outcome</h3>
            <p className="mt-2 max-w-2xl text-ink-muted">Information comes in, AI analyses it, an administrator reviews and approves, support reaches the child, and every step is recorded.</p>
            <div className="mt-6"><WorkflowBoard /></div>
            <p className="mt-6"><Link to="/guide" className="btn-soft"><IconBook className="h-4 w-4" /> Read the beginner guide</Link></p>
          </div>
        </section>

        <section id="needs" className="lp-sheet scroll-mt-20 px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="Essential needs" title="What children need most" />
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {NEEDS.map((n) => <div key={n.name} className="card card-hover p-5"><span className={`inline-block rounded-lg px-2.5 py-1 text-sm font-semibold ${n.color}`}>{n.name}</span><p className="mt-3 text-sm text-ink-muted">{n.text}</p></div>)}
            </div>
          </div>
        </section>

        <section id="organizations" className="lp-sheet-alt scroll-mt-20 border-y border-line px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="Verified organizations" title="Organizations reviewed by an administrator" />
            <div className="mt-6">
              {orgs.error ? <Unavailable what="The organization list" onRetry={orgs.reload} /> : orgs.loading && !orgs.data ? <p className="text-sm text-ink-muted">Loading…</p> : orgs.data.length === 0 ? <p className="card p-5 text-sm text-ink-muted">No organizations have been verified yet.</p> : (
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{orgs.data.map((o) => (
                  <li key={o.id} className="card card-hover p-5"><p className="flex items-center gap-2 font-semibold text-ink"><IconBuilding className="h-4 w-4 text-teal-700" />{o.name}</p>
                    {o.about && <p className="mt-2 text-sm text-ink-muted">{o.about}</p>}
                    {o.website && <a href={o.website} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm font-semibold text-sky-600 hover:underline">Website<span className="sr-only"> of {o.name} (opens in a new tab)</span></a>}
                    <p className="mt-3"><Pill tone="green"><IconCheck className="h-3.5 w-3.5" /> Verified</Pill></p></li>
                ))}</ul>
              )}
            </div>
            <h3 className="mt-12 font-display text-xl font-bold text-ink">Urgent needs</h3>
            <div className="mt-4">
              {needs.error ? <Unavailable what="Urgent needs" onRetry={needs.reload} /> : needs.loading && !needs.data ? <p className="text-sm text-ink-muted">Loading…</p> : needs.data.length === 0 ? <p className="card p-5 text-sm text-ink-muted">There are no open needs from verified organizations right now.</p> : (
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{needs.data.map((n) => (
                  <li key={n.id} className="card card-hover p-5"><div className="flex items-start justify-between gap-2"><p className="font-semibold text-ink">{n.title}</p><Pill tone={URGENCY_TONE[n.urgency] || 'gray'} className="capitalize">{n.urgency}</Pill></div>
                    <p className="mt-1 text-sm text-ink-muted">{n.category} · quantity {n.quantity}</p><p className="mt-1 text-xs text-ink-muted">{n.organization}{n.required_by ? ` · needed by ${new Date(n.required_by).toLocaleDateString()}` : ''}</p></li>
                ))}</ul>
              )}
            </div>
          </div>
        </section>

        <section id="opportunities" className="lp-sheet scroll-mt-20 px-4 py-16 sm:px-8">
          <div className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2">
            <div className="card card-hover p-6"><IconDonations className="h-6 w-6 text-teal-700" /><h3 className="mt-3 font-display text-xl font-bold text-ink">Donate</h3><p className="mt-1 text-sm text-ink-muted">Choose a verified need and record your gift. You can follow it in your donation history.</p><Link to="/register?role=donor" className="btn-primary mt-4">Become a donor</Link></div>
            <div className="card card-hover p-6"><IconHand className="h-6 w-6 text-teal-700" /><h3 className="mt-3 font-display text-xl font-bold text-ink">Volunteer</h3><p className="mt-1 text-sm text-ink-muted">Share your skills and time with organizations that need them.</p><Link to="/register?role=volunteer" className="btn-primary mt-4">Become a volunteer</Link></div>
          </div>
        </section>

        <section id="impact" className="lp-sheet-alt scroll-mt-20 border-y border-line px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="Our impact" title="Live figures from the platform" />
            <div className="mt-6">
              {stats.error ? <Unavailable what="Impact statistics" onRetry={stats.reload} /> : stats.loading && !stats.data ? <p className="text-sm text-ink-muted">Loading…</p> : (
                <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{STATS.map(([key, label]) => (
                  <div key={key} className="card border-l-4 border-l-teal-700 p-5"><dd className="font-display text-3xl font-bold text-teal-700">{Number(stats.data[key] ?? 0).toLocaleString('en-IN')}</dd><dt className="mt-1 text-sm text-ink-muted">{label}</dt></div>
                ))}</dl>
              )}
            </div>
          </div>
        </section>

        <section id="trust" className="lp-sheet scroll-mt-20 px-4 py-16 sm:px-8">
          <div className="mx-auto max-w-6xl">
            <SectionHead eyebrow="Transparency and trust" title="Built to be accountable" />
            <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[[IconShield, 'Verified first', 'Needs from organizations an administrator has not verified are never shown here.'], [IconSpark, 'People decide', 'AI suggests and flags. It never approves, rejects or accuses on its own.'], [IconLock, 'Children are protected', 'No names, photos or records of children appear on public pages.'], [IconPeople, 'Every decision is recorded', 'Reviews and changes are saved in an audit trail.']].map(([Icon, title, text]) => (
                <li key={title} className="card card-hover p-5"><Icon className="h-5 w-5 text-teal-700" /><h3 className="mt-3 font-semibold text-ink">{title}</h3><p className="mt-1 text-sm text-ink-muted">{text}</p></li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer id="contact" className="site-footer scroll-mt-20 px-4 pb-6 pt-12 text-white sm:px-8">
        <div className="mx-auto grid max-w-6xl gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div><Logo size={34} light showTagline /><p className="mt-3 max-w-xs text-sm text-teal-100">Connecting verified child-care organizations with donors and volunteers.</p></div>
          <div><h2 className="lp-footer-head text-sm font-semibold uppercase tracking-wide">Contact</h2>
            {CONTACT_EMAIL ? <a href={`mailto:${CONTACT_EMAIL}`} className="mt-2 inline-flex items-center gap-2 text-sm text-white hover:underline"><IconMail className="h-4 w-4" />{CONTACT_EMAIL}</a>
              : <p className="mt-2 text-sm text-teal-100">Public contact details have not been added yet. Registered users can reach an administrator from inside the platform.</p>}</div>
          <div><h2 className="lp-footer-head text-sm font-semibold uppercase tracking-wide">Explore</h2>
            <ul className="mt-2 space-y-1 text-sm">{NAV.map(([id, label]) => <li key={id}><a href={`#${id}`} className="text-teal-100 hover:text-white hover:underline">{label}</a></li>)}<li><Link to="/guide" className="text-teal-100 hover:text-white hover:underline">How it works (guide)</Link></li></ul></div>
          <div><h2 className="lp-footer-head text-sm font-semibold uppercase tracking-wide">Account</h2>
            <ul className="mt-2 space-y-1 text-sm">
              <li><Link to="/login" className="text-teal-100 hover:text-white hover:underline">Login</Link></li>
              <li><Link to="/register" className="text-teal-100 hover:text-white hover:underline">Register</Link></li>
              <li><Link to="/forgot-password" className="text-teal-100 hover:text-white hover:underline">Forgot password</Link></li>
              <li><Link to="/admin/login" className="text-teal-100 hover:text-white hover:underline">Administrator login</Link></li>
            </ul></div>
        </div>
        <p className="mx-auto mt-8 max-w-6xl border-t border-white/15 pt-4 text-xs text-teal-200">© {new Date().getFullYear()} CareBridge AI. Connecting Hearts, Fulfilling Needs.</p>
      </footer>
    </div>
  )
}
