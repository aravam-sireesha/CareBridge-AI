import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const API = import.meta.env.VITE_API_URL
const stamp = Date.now()
const ORG = { email: `org${stamp}@e2e-carebridge.org`, password: 'StrongPass-2026!', name: `E2E Hope Home ${stamp}` }
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL || 'admin@e2e-carebridge.org', password: process.env.E2E_ADMIN_PASSWORD || 'AdminPass-2026!' }

const mount = (path = '/') => render(
  <MemoryRouter initialEntries={[path]}><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></MemoryRouter>
)
const wait = { timeout: 15000 }

async function login(user, creds) {
  await user.type(screen.getByPlaceholderText(/you@organization.org/i), creds.email)
  await user.type(screen.getByPlaceholderText(/your password/i), creds.password)
  await user.click(screen.getByRole('button', { name: /^login$/i }))
}

describe('CareBridge UI against the live backend', () => {
  it('backend is reachable', async () => {
    const res = await fetch(`${API}/`)
    expect((await res.json()).status).toBe('running')
  })

  it('home page has the header navigation, logo, tagline, hero and a login link', async () => {
    mount('/')
    expect(screen.getAllByLabelText(/carebridge ai logo/i).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: /^login$/i }).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Connecting Hearts, Fulfilling Needs\./i).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { level: 1, name: /connecting compassion with every need/i })).toBeInTheDocument()
    for (const name of [/^about us$/i, /^how it works$/i, /^organizations$/i, /^our impact$/i, /^contact$/i]) expect(screen.getAllByRole('link', { name }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: /administrator account/i })).not.toBeInTheDocument()   // no public admin sign-up
  })

  it('registers an organization, then logs in and reads its data back', async () => {
    const user = userEvent.setup()
    mount('/register')
    await user.type(screen.getByPlaceholderText(/hope children/i), ORG.name)
    await user.type(screen.getByPlaceholderText(/you@example.org/i), ORG.email)
    await user.type(screen.getByPlaceholderText(/\+91/i), '9876543210')
    await user.type(screen.getByPlaceholderText(/at least 12/i), ORG.password)
    await user.type(screen.getByPlaceholderText(/repeat your password/i), ORG.password)
    await user.click(screen.getByRole('button', { name: /create account/i }))
    await screen.findByRole('heading', { name: /welcome back/i }, wait)   // redirected to /login

    await login(user, ORG)
    await screen.findByText(new RegExp(`Good (morning|afternoon|evening), ${ORG.name}`), {}, wait)
    expect(await screen.findByText(/Open needs/i, {}, wait)).toBeInTheDocument()
  })

  it('wrong password shows a clear message, not a crash', async () => {
    const user = userEvent.setup()
    mount('/login')
    await login(user, { email: ORG.email, password: 'definitely-wrong-123' })
    expect(await screen.findByRole('alert', {}, wait)).toHaveTextContent(/invalid email or password/i)
  })

  it('organization can add a child and a need, and sees them after a reload', async () => {
    const user = userEvent.setup()
    mount('/login')
    await login(user, ORG)
    await screen.findByText(/Good (morning|afternoon|evening)/i, {}, wait)

    // navigate through the sidebar (this used to bounce back to the dashboard)
    await user.click(screen.getAllByRole('link', { name: /^children$/i })[0])
    await screen.findByRole('heading', { name: /^children$/i }, wait)
    await user.click(screen.getAllByRole('button', { name: /add child/i })[0])
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByRole('spinbutton'), '11')
    await user.type(within(dialog).getByPlaceholderText(/drawing, cricket/i), 'Painting and science')
    await user.click(within(dialog).getByRole('button', { name: /save child/i }))
    await screen.findByText(/Painting and science/i, {}, wait)

    await user.click(screen.getAllByRole('link', { name: /^needs$/i })[0])
    await screen.findByRole('heading', { name: /^needs$/i }, wait)
    await user.click(screen.getAllByRole('button', { name: /add need/i })[0])
    const nd = await screen.findByRole('dialog')
    await user.type(within(nd).getByPlaceholderText(/school supplies/i), 'School supplies')
    await user.type(within(nd).getAllByRole('spinbutton')[0], '40')
    await user.click(within(nd).getByRole('button', { name: /save need/i }))
    await screen.findByText('School supplies', {}, wait)

    // a fresh mount re-reads everything from the database
    document.body.innerHTML = ''
    mount('/dashboard')
    await screen.findByText(/Good (morning|afternoon|evening)/i, {}, wait)
    await waitFor(() => expect(screen.getByText('School supplies')).toBeInTheDocument(), wait)
  })

  it('every sidebar link opens its screen for an organization', async () => {
    const user = userEvent.setup()
    mount('/login')
    await login(user, ORG)
    await screen.findByText(/Good (morning|afternoon|evening)/i, {}, wait)
    const pages = [
      [/^dashboard$/i, /Good (morning|afternoon|evening)/i], [/^children$/i, /records are visible only/i], [/^needs$/i, /record what children need/i],
      [/^donations$/i, /record gifts/i], [/donors & volunteers/i, /who can be matched/i], [/need alerts/i, /flagged for high urgency/i],
      [/matching review/i, /suggested for open needs/i], [/career guidance/i, /three suggested career paths/i],
      [/ai assistant/i, /every answer shows/i], [/^settings$/i, /your account details|manage accounts/i]
    ]
    for (const [name, text] of pages) {
      await user.click(screen.getAllByRole('link', { name })[0])
      await screen.findByText(text, {}, wait)
    }
    expect(screen.queryByRole('link', { name: /fraud flags/i })).not.toBeInTheDocument() // admin only
  })

  it('admin: fraud scan, assistant knowledge + grounded answer, and the system health page', async () => {
    const user = userEvent.setup()
    mount('/login')
    await login(user, ADMIN)
    await screen.findByText(/Good (morning|afternoon|evening)/i, {}, wait)

    await user.click(screen.getAllByRole('link', { name: /fraud flags/i })[0])
    await screen.findByText(/an administrator reviews every flag/i, {}, wait)
    await user.click(screen.getByRole('button', { name: /scan donations/i }))
    await screen.findByText(/Checked \d+ new donation/i, {}, wait)

    await user.click(screen.getAllByRole('link', { name: /ai assistant/i })[0])
    await screen.findByText(/how can i help today/i, {}, wait)
    await user.click(screen.getByRole('button', { name: /add knowledge/i }))
    const kd = await screen.findByRole('dialog')
    await user.type(within(kd).getByPlaceholderText(/volunteer background checks/i), `Uniform policy ${stamp}`)
    await user.type(within(kd).getByPlaceholderText(/write the policy/i), 'Every child receives two school uniforms at the start of each academic year.')
    await user.type(within(kd).getByPlaceholderText(/policy manual/i), 'Policy manual section 4')
    await user.click(within(kd).getByRole('button', { name: /save knowledge/i }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), wait)

    await user.type(screen.getByLabelText(/your question/i), 'How many school uniforms does each child receive?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText(new RegExp(`Uniform policy ${stamp}`), {}, wait)
    expect((await screen.findAllByText(/two school uniforms/i)).length).toBeGreaterThan(0)   // re-runnable: earlier runs leave the same entry
    expect((await screen.findAllByText(/Source: Policy manual section 4/i)).length).toBeGreaterThan(0)

    await user.click(screen.getAllByRole('link', { name: /^settings$/i })[0])
    await user.click(await screen.findByRole('tab', { name: /system & database/i }))
    await screen.findByText(/PostgreSQL connection/i, {}, wait)
    expect(await screen.findByText(/Connected \(postgresql\)/i, {}, wait)).toBeInTheDocument()
  })

  it('a donor can register, sign in, and ask the assistant (global knowledge only)', async () => {
    const user = userEvent.setup()
    const donor = { email: `donor${stamp}@e2e-carebridge.org`, password: 'DonorPass-2026!!', name: `E2E Donor ${stamp}` }
    mount('/register?role=donor')
    await user.type(screen.getByPlaceholderText(/your full name/i), donor.name)
    await user.type(screen.getByPlaceholderText(/you@example.org/i), donor.email)
    await user.type(screen.getByPlaceholderText(/at least 12/i), donor.password)
    await user.type(screen.getByPlaceholderText(/repeat your password/i), donor.password)
    await user.click(screen.getByRole('button', { name: /create account/i }))
    await screen.findByRole('heading', { name: /welcome back/i }, wait)
    await login(user, donor)
    await screen.findAllByText(new RegExp(donor.name), {}, wait)
    // donors do not see organization-only areas
    expect(screen.queryByRole('link', { name: /^children$/i })).not.toBeInTheDocument()
    await user.click(screen.getAllByRole('link', { name: /ai assistant/i })[0])
    await screen.findByText(/how can i help today/i, {}, wait)
    await user.type(screen.getByLabelText(/your question/i), 'How many school uniforms does each child receive?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect((await screen.findAllByText(/two school uniforms/i, {}, wait)).length).toBeGreaterThan(0)
  })
})
