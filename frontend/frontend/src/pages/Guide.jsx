import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Layout from '../components/Layout.jsx'
import Logo from '../components/Logo.jsx'
import { ThemeToggle } from '../components/ProfileMenu.jsx'
import { PageHeader, Tabs } from '../components/ui.jsx'
import { IconBook } from '../components/icons.jsx'

const IMAGES = {
  beginner: { src: '/images/carebridge-1-beginner-workflow.png', alt: 'CareBridge AI in five steps: 1 Tell us what is needed, 2 AI looks for the best match, 3 A person checks and approves, 4 Help reaches the child, 5 Everyone can see the result.' },
  hub: { src: '/images/carebridge-2-administrator-hub.png', alt: 'The administrator sits in the centre, connected to organizations, needs, donors, volunteers and resources. AI engines send suggestions to the administrator, who decides.' },
  roles: { src: '/images/carebridge-3-role-journeys.png', alt: 'Four columns showing what an organization, a donor, a volunteer and an administrator each do, in four steps.' },
  pro: { src: '/images/carebridge-4-professional-workflow.png', alt: 'End to end flow: users and data sources, AI and analytics engine, decision layer, services and operations, impact and outcomes.' }
}

const ROLES = {
  organization: { label: 'Organization', steps: [
    ['Sign up and wait for verification', 'Create an account with your home\'s name and contact. An administrator checks it. Until then donors and volunteers cannot see your needs.'],
    ['Add children and their needs', 'Record each child\'s basic profile, then post needs such as books, food or medicine with a quantity and how urgent it is.'],
    ['Add resources you can share', 'List materials, services or funds you hold. Administrators can allocate them to needs anywhere on the platform.'],
    ['Watch needs get fulfilled', 'Use the assistant and your dashboard to see progress, your health score and tips to improve.'] ] },
  donor: { label: 'Donor', steps: [
    ['Sign up and say what you like to support', 'Choose interests such as education, food or medicine. The AI uses them to suggest the right needs for you.'],
    ['See needs from verified homes', 'Only organizations an administrator has verified are shown, so you can give with confidence.'],
    ['Give money or items and record the gift', 'Every gift is linked to a need so progress is accurate.'],
    ['See the impact of your help', 'Needs turn to fulfilled and the record is kept in the audit trail.'] ] },
  volunteer: { label: 'Volunteer', steps: [
    ['Sign up with your skills', 'For example teaching, cooking or first aid. Be specific: it helps the AI find the right task.'],
    ['Say when you are available', 'Weekends, evenings or full time. Volunteers with no stated availability are ranked lower.'],
    ['Get matched to a need that fits', 'The AI suggests tasks; an administrator approves the match.'],
    ['Help, and the match is recorded', 'Your help is recorded so future suggestions know what works.'] ] },
  admin: { label: 'Administrator', steps: [
    ['Verify organizations and manage records', 'Under Administration you can see and edit every organization, need, donor, volunteer and resource.'],
    ['Run the AI scans and read the ideas', 'Press Run all AI scans on the Workflow page. Use the AI suggestion hub to explore any organization, need, donor or volunteer.'],
    ['Approve or reject in the review queue', 'Fraud flags, predicted needs, matches, suggestions and allocations all wait here for your decision.'],
    ['Track results in the audit trail', 'Every sign-in and decision is recorded and cannot be edited. Turn on two-step verification in Settings.'] ] }
}

const GLOSSARY = [
  ['Need', 'Something a child or home requires, like books or food.'], ['Donor', 'A person or group who gives money or items.'],
  ['Volunteer', 'A person who gives time and skills.'], ['Resource', 'Materials, services or funds that can be given.'],
  ['Allocation', 'Assigning a resource to a need.'], ['Verified', 'An organization an administrator has checked.'],
  ['Suggestion', 'An AI idea. A person approves or rejects it.'], ['Flag', 'A warning from the AI that a person should look at something.'],
  ['Audit trail', 'The permanent record of who did what and when.'], ['Confidence', 'How sure the assistant is that its answer is in the knowledge base.']
]

function Figure({ img, caption }) {
  return (
    <figure className="card overflow-hidden p-2 sm:p-3">
      <a href={img.src} target="_blank" rel="noreferrer" title="Open the full-size image"><img src={img.src} alt={img.alt} loading="lazy" className="w-full rounded-xl" /></a>
      <figcaption className="px-2 pb-1 pt-3 text-center text-xs text-ink-muted">{caption} <a className="font-semibold text-sky-600 hover:underline" href={img.src} download>Download image</a></figcaption>
    </figure>
  )
}

function Content({ role }) {
  const initial = ROLES[role] ? role : 'organization'
  const [tab, setTab] = useState(initial)
  useEffect(() => { setTab(initial) }, [initial])
  const r = ROLES[tab]
  return (
    <div className="space-y-12">
      <section aria-labelledby="g-steps">
        <h2 id="g-steps" className="font-display text-2xl font-bold text-teal-900">How it works in 5 steps</h2>
        <p className="mb-5 mt-1 max-w-2xl text-ink-muted">Think of CareBridge AI as a careful matchmaker. People say what they have and what they need, the AI proposes good matches, a person checks them, and everything is written down.</p>
        <Figure img={IMAGES.beginner} caption="The whole journey on one page." />
      </section>

      <section aria-labelledby="g-roles">
        <h2 id="g-roles" className="font-display text-2xl font-bold text-teal-900">What do I do? Pick your role</h2>
        <div className="mt-4"><Tabs tabs={Object.entries(ROLES).map(([k, v]) => ({ key: k, label: v.label }))} value={tab} onChange={setTab} /></div>
        <ol className="mt-4 grid gap-3 md:grid-cols-2">
          {r.steps.map(([title, text], i) => (
            <li key={title} className="card flex gap-3 p-4"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-teal-500 to-sky-600 font-display text-sm font-bold text-white">{i + 1}</span><div><p className="text-sm font-semibold text-ink">{title}</p><p className="mt-0.5 text-sm text-ink-muted">{text}</p></div></li>
          ))}
        </ol>
        <div className="mt-6"><Figure img={IMAGES.roles} caption="All four roles side by side." /></div>
      </section>

      <section aria-labelledby="g-admin">
        <h2 id="g-admin" className="font-display text-2xl font-bold text-teal-900">The administrator is the control centre</h2>
        <p className="mb-5 mt-1 max-w-2xl text-ink-muted">One administrator can see and manage every organization, need, donor, volunteer and resource. The AI engines suggest; the administrator decides. Nothing important happens automatically.</p>
        <Figure img={IMAGES.hub} caption="The administrator at the centre of the platform." />
      </section>

      <section aria-labelledby="g-pro">
        <h2 id="g-pro" className="font-display text-2xl font-bold text-teal-900">The full flow, for technical readers</h2>
        <p className="mb-5 mt-1 max-w-2xl text-ink-muted">Data sources feed the AI and analytics engine; the decision layer keeps people in charge and records everything; services deliver help; outcomes are measured.</p>
        <Figure img={IMAGES.pro} caption="End to end working flow." />
      </section>

      <section aria-labelledby="g-gloss">
        <h2 id="g-gloss" className="font-display text-2xl font-bold text-teal-900">Words you will see</h2>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2">{GLOSSARY.map(([t, d]) => <div key={t} className="card p-4"><dt className="text-sm font-semibold text-teal-700">{t}</dt><dd className="mt-0.5 text-sm text-ink-muted">{d}</dd></div>)}</dl>
        <p className="mt-6 text-sm text-ink-muted">Still stuck? Ask the <Link to="/assistant" className="font-semibold text-sky-600 hover:underline">AI assistant</Link>. It explains how the platform works and always shows where its answer came from.</p>
      </section>
    </div>
  )
}

export default function Guide() {
  const { isAuthenticated, user } = useAuth()
  useEffect(() => { document.title = 'How CareBridge AI works' }, [])
  if (isAuthenticated) {
    return (
      <Layout title="How it works">
        <PageHeader icon={IconBook} title="How CareBridge AI works" subtitle="A beginner-friendly guide with pictures. No technical knowledge needed." />
        <Content role={user?.role} />
      </Layout>
    )
  }
  return (
    <div className="bg-mesh min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-8"><Link to="/" aria-label="CareBridge AI home"><Logo size={38} /></Link><div className="flex items-center gap-2"><ThemeToggle /><Link to="/login" className="btn-ghost">Login</Link></div></header>
      <main className="mx-auto max-w-6xl px-4 pb-16 pt-4 sm:px-8">
        <h1 className="font-display text-3xl font-bold text-teal-900 sm:text-4xl">How CareBridge AI works</h1>
        <p className="mb-10 mt-2 max-w-2xl text-ink-muted">A beginner-friendly guide with pictures. No technical knowledge needed.</p>
        <Content role="organization" />
      </main>
    </div>
  )
}
