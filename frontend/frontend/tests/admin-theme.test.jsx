import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ThemeProvider } from '../src/context/ThemeContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const ADMIN = { id: 1, email: 'boss@carebridge.org', role: 'admin', display_name: 'Asha Rao', organization_id: null, donor_id: null, volunteer_id: null }
const DONOR = { ...ADMIN, id: 2, email: 'd@x.org', role: 'donor', display_name: 'Dee Donor', donor_id: 5 }

const OVERVIEW = {
  totals: { organizations: 2, unverified_organizations: 1, needs: 4, open_needs: 3, critical_needs: 1, donors: 6, suggestions_waiting: 2 },
  suggestions_by_status: {}, needs_by_priority: {}, top_needs: [],
  model: { mode: 'blend', model_version: 'donor-ml-1.0.0-blend', reviewed_rows: 3, needed: 20, description: 'blend' }
}

function mockApi(extra = {}, me = ADMIN) {
  const routes = {
    'GET /auth/me': me, 'GET /': { status: 'running' }, 'GET /admin/overview': OVERVIEW,
    'POST /admin/login': { access_token: 'tok', token_type: 'bearer', user: ADMIN, admin: {} },
    'GET /admin/register-status': { first_admin: false, invite_required: true, signup_enabled: true },
    'GET /assistant/insights': { generated_at: '2026-10-09T10:00:00Z', scope: 'admin', health: [], selection: [], snapshot: { open_needs: 3, urgent_open: 1, organizations: 2, donors: 6 } },
    ...extra
  }
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    if (!(key in routes)) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: `no mock for ${key}` }) }
    return { ok: true, status: 200, text: async () => JSON.stringify(routes[key]) }
  })
}

function signedIn(user) { localStorage.setItem('cb_token', 'tok'); localStorage.setItem('cb_user', JSON.stringify({ id: user.id, email: user.email, role: user.role, name: user.display_name, organization_id: null, donor_id: user.donor_id, volunteer_id: null })) }

const mount = (path) => render(
  <MemoryRouter initialEntries={[path]}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>
)

beforeEach(() => { document.documentElement.classList.remove('dark') })

describe('dark mode', () => {
  it('Settings > Appearance switches the page to dark, saves the choice, and switches back', async () => {
    signedIn(ADMIN); mockApi()
    const user = userEvent.setup()
    mount('/settings?tab=appearance')
    await screen.findByText(/^Theme$/)
    await user.click(screen.getAllByRole('radio', { name: /^dark$/i })[0])
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('cb_theme')).toBe('dark')
    await user.click(screen.getAllByRole('radio', { name: /^light$/i })[0])
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('cb_theme')).toBe('light')
  })

  it('the header sun/moon button toggles the theme', async () => {
    signedIn(ADMIN); mockApi()
    const user = userEvent.setup()
    mount('/admin')
    await user.click(await screen.findByRole('button', { name: /switch to dark mode/i }))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument()
  })

  it('a saved dark choice is applied on load', async () => {
    localStorage.setItem('cb_theme', 'dark'); signedIn(ADMIN); mockApi()
    mount('/admin')
    await screen.findByRole('heading', { name: /^administration$/i })
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})

describe('logout', () => {
  it('Settings has a Log out button that ends the session', async () => {
    signedIn(ADMIN); mockApi()
    const user = userEvent.setup()
    mount('/settings')
    await screen.findByText(/^Sign out$/)
    await user.click(screen.getAllByRole('button', { name: /log out/i }).pop())
    await screen.findByRole('heading', { name: /administrator sign in/i })
    expect(localStorage.getItem('cb_token')).toBeNull()
  })

  it('the profile menu shows the account and a Log out button', async () => {
    signedIn(DONOR); mockApi({}, DONOR)
    const user = userEvent.setup()
    mount('/settings')
    await user.click(await screen.findByRole('button', { name: /open profile menu/i }))
    expect(within(await screen.findByRole('menu')).getByText('d@x.org')).toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: /log out/i }))
    await screen.findByRole('heading', { name: /welcome back/i })  // donors return to the normal sign in
    expect(localStorage.getItem('cb_token')).toBeNull()
  })
})

describe('administration frame', () => {
  it('administrator sign in leads to the Administration overview', async () => {
    mockApi({}, undefined)
    const user = userEvent.setup()
    mount('/admin/login')
    await user.type(screen.getByPlaceholderText(/admin@carebridge.org/i), 'boss@carebridge.org')
    await user.type(screen.getByPlaceholderText(/your password/i), 'StrongPass1234')
    await user.click(screen.getByRole('button', { name: /sign in as administrator/i }))
    await screen.findByRole('heading', { name: /^administration$/i })
    expect(screen.getByText('Suggestions to review')).toBeInTheDocument()
    expect(localStorage.getItem('cb_token')).toBe('tok')
  })

  it('the admin frame logo goes to the admin home', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin')
    await screen.findByRole('heading', { name: /^administration$/i })
    expect(screen.getAllByRole('link', { name: /administration home/i })[0]).toHaveAttribute('href', '/admin')
    expect(screen.getAllByRole('link', { name: /donor suggestions/i }).length).toBeGreaterThan(0)
  })

  it('signed-out visitors are sent to the administrator sign in, other roles are refused', async () => {
    mockApi()
    mount('/admin/needs')
    await screen.findByRole('heading', { name: /administrator sign in/i })
  })

  it('a donor cannot open the Administration pages', async () => {
    signedIn(DONOR); mockApi({}, DONOR)
    mount('/admin')
    await screen.findByText(/not available for your account/i)
  })

  it('public administrator sign-up is not offered: the old page is gone', async () => {
    mockApi()
    mount('/admin/register')
    expect(screen.queryByRole('heading', { name: /create administrator account/i })).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/invite code/i)).not.toBeInTheDocument()
  })

  it('the administrator sign-in page does not link to a sign-up page', async () => {
    mockApi()
    mount('/admin/login')
    expect(await screen.findByRole('heading', { name: /administrator sign in/i })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /create an administrator account/i })).not.toBeInTheDocument()
  })
})


describe('administration: donors, team, sign-up rules and the upgraded assistant', () => {
  const DONORS = [
    { id: 1, name: 'Edu Donor', contact: 'e@x', preferences: 'education', location: 'Kadapa', organization_id: 1, organization_name: 'Hope Home', account_email: null, gifts: 2, total_given: 1500, last_gift: '2026-09-01T10:00:00', pending_suggestions: 1 },
    { id: 2, name: 'Food Donor', contact: 'f@x', preferences: 'food', location: null, organization_id: 2, organization_name: 'Little Stars', account_email: 'f@x.org', gifts: 0, total_given: 0, last_gift: null, pending_suggestions: 0 }
  ]

  it('lists the donors of every organization, filters them, and opens a donor with matching needs', async () => {
    signedIn(ADMIN)
    mockApi({
      'GET /admin/donors': DONORS, 'GET /admin/organizations': [{ id: 1, name: 'Hope Home' }, { id: 2, name: 'Little Stars' }],
      'GET /admin/donors/1': { ...DONORS[0], donations: [{ id: 9, amount: 500, description: null, timestamp: '2026-09-01T10:00:00', need_category: 'School supplies', organization_name: 'Hope Home' }],
        recommended_needs: [{ need_id: 4, category: 'Books', urgency: 'high', quantity: 20, organization_name: 'Little Stars', priority_score: 0.8, fit_score: 0.7, reasons: ['Donor supports education'] }] }
    })
    const user = userEvent.setup()
    mount('/admin/donors')
    expect(await screen.findByText('Edu Donor')).toBeInTheDocument()
    expect(screen.getByText('Food Donor')).toBeInTheDocument()
    expect(screen.getByText('Little Stars', { selector: 'td' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/search donors/i), 'food')
    expect(screen.queryByText('Edu Donor')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText(/search donors/i))
    await user.click((await screen.findAllByRole('button', { name: /^view$/i }))[0])
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Books')).toBeInTheDocument()
    expect(within(dialog).getByText(/school supplies/i)).toBeInTheDocument()
  })

  it('adds an administrator from the Administrators page', async () => {
    signedIn(ADMIN)
    mockApi({ 'GET /admin/administrators': [{ id: 1, user_id: 1, full_name: 'Asha Rao', email: 'boss@carebridge.org', is_active: true, is_you: true, designation: 'Director', phone: null, last_login_at: null }],
      'POST /admin/administrators': { id: 2, full_name: 'Ravi K', email: 'ravi@x.org', is_active: true, is_you: false } })
    const user = userEvent.setup()
    mount('/admin/team')
    expect(await screen.findByText('Asha Rao')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^deactivate$/i })).toBeDisabled()  // cannot deactivate yourself
    await user.click(screen.getByRole('button', { name: /add administrator/i }))
    const dialog = await screen.findByRole('dialog')
    const inputs = within(dialog).getAllByRole('textbox')
    await user.type(inputs[0], 'Ravi K'); await user.type(inputs[1], 'ravi@x.org'); await user.type(inputs[inputs.length - 1], 'LongPassword-2026')
    await user.click(within(dialog).getByRole('button', { name: /create administrator/i }))
    await waitFor(() => expect(global.fetch.mock.calls.some(([u, i]) => String(u).endsWith('/admin/administrators') && i?.method === 'POST')).toBe(true))
    const post = global.fetch.mock.calls.find(([u, i]) => String(u).endsWith('/admin/administrators') && i?.method === 'POST')
    expect(JSON.parse(post[1].body)).toMatchObject({ full_name: 'Ravi K', email: 'ravi@x.org' })
  })

  it('assistant shows live records, a focused donor profile and clickable follow-up questions', async () => {
    signedIn(ADMIN)
    const answer = {
      conversation_id: 1, question: 'Tell me about Edu Donor', answer: 'Live data as of 10:00 UTC.\nEdu Donor is active: 2 gift(s).', matches: [], answer_mode: 'live_analysis',
      records: [{ id: null, title: 'Donor: Edu Donor', content: 'Edu Donor supports education. 2 gift(s).', source: 'live database (donor records)', score: 0.8, live: true, kind: 'donor' }],
      live_sources: [], focus: ['Edu Donor'], follow_up_of: null, follow_ups: ['Which donors have stopped giving?'],
      analysis: { generated_at: '2026-10-09T10:00:00Z', scope: 'admin', health: [], selection: [], snapshot: null, donor_insights: null,
        donor_profiles: [{ donor_id: 1, label: 'Edu Donor', preferences: 'education', location: null, gifts: 2, total_given: 1500, days_since_last: 12, status: 'active', categories_given: ['School supplies'], best_needs: [{ need_id: 4, category: 'Books', organization: 'Little Stars', urgency: 'high', priority_score: 0.8, fit_score: 0.7 }] }] }
    }
    mockApi({ 'GET /assistant/status': { knowledge_entries: 1, embedded_entries: 1, needs_indexing: 0, mode: 'retrieval_only' }, 'GET /assistant/history': [], 'POST /assistant/ask': answer })
    const user = userEvent.setup()
    mount('/assistant')
    await user.type(await screen.findByLabelText(/your question/i), 'Tell me about Edu Donor')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByText(/Focused on Edu Donor/i)).toBeInTheDocument()
    expect(screen.getByText('LIVE RECORD')).toBeInTheDocument()
    expect(screen.getByText(/best open needs for this donor/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /which donors have stopped giving\?/i }))
    await waitFor(() => expect(global.fetch.mock.calls.filter(([u, i]) => String(u).endsWith('/assistant/ask') && i?.method === 'POST')).toHaveLength(2))
  })

  it('the Administration menu has donors and administrators', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin')
    await screen.findByRole('heading', { name: /^administration$/i })
    expect(screen.getAllByRole('link', { name: /all donors/i }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: /^administrators$/i }).length).toBeGreaterThan(0)
  })
})
