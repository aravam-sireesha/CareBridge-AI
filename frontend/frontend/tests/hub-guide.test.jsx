import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ThemeProvider } from '../src/context/ThemeContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const U = (role, extra = {}) => ({ id: 1, email: `${role}@x.org`, role, display_name: role, organization_id: null, donor_id: null, volunteer_id: null, ...extra })
const ADMIN = U('admin')

const ENTITIES = { organization: [{ id: 1, label: 'Hope Home', sublabel: 'verified' }], need: [{ id: 5, label: 'Books · Hope Home', sublabel: 'critical urgency, qty 40' }],
  donor: [{ id: 2, label: 'Edu Donor', sublabel: 'education' }], volunteer: [{ id: 3, label: 'Tutor', sublabel: 'teaching' }] }
const item = (kind, id, label, score, extra = {}) => ({ kind, id, label, sublabel: 'sub', score, reasons: [`Why ${label}`], extra })
const REC = {
  need: { entity: { kind: 'need', id: 5, label: 'Books · Hope Home', sublabel: 'critical urgency, quantity 40, AI priority 0.8 (high)', score: 0.8, reasons: [] },
    sections: { donors: [item('donor', 2, 'Edu Donor', 0.9)], volunteers: [item('volunteer', 3, 'Tutor', 0.8)], resources: [item('resource', 9, 'Textbook set', 0.7)], organizations: [item('organization', 4, 'Little Stars', 0.6)] },
    forecast: [{ category: 'books', history: [1, 2, 3], periods: 3, forecast_needs: 4, forecast_units: 120, trend: 'rising', confidence: 0.6, method: 'damped-trend smoothing', stock_units: 30, matching_donors: 1, matching_volunteers: 1, supply_gap_units: 90, risk: 'medium', notes: ['About 120 unit(s) expected but only 30 in stock'] }] },
  donor: { entity: { kind: 'donor', id: 2, label: 'Edu Donor', sublabel: 'education', score: null, reasons: [] }, sections: { needs: [item('need', 5, 'Books · Hope Home', 0.85)], organizations: [item('organization', 1, 'Hope Home', 0.8, { verified: false })] }, forecast: [] }
}

function mockApi(extra = {}, me = ADMIN) {
  const routes = {
    'GET /auth/me': me, 'GET /': { status: 'running' }, 'GET /admin/entities': ENTITIES,
    'GET /admin/recommend': (init, url) => (String(url).includes('entity=donor') ? REC.donor : REC.need),
    'GET /admin/workflow': { generated_at: '2026-10-09T10:00:00Z', open_needs: 1, pending: { total: 0, by_type: {} }, stages: [] },
    'GET /admin/review-queue': { total: 1, counts: { volunteer_suggestion: 1 }, items: [{ type: 'volunteer_suggestion', id: 4, key: 'volunteer_suggestion:4', title: 'Tutor → Books', subtitle: 'Hope Home · fit 80%', score: 0.8, reasons: ['Skills match'], severity: 'medium', decisions: ['approved', 'contacted', 'rejected'], created_at: null }] },
    'GET /admin/overview': { totals: { organizations: 1, unverified_organizations: 0, needs: 1, open_needs: 1, critical_needs: 1, donors: 1, suggestions_waiting: 0 }, suggestions_by_status: {}, needs_by_priority: {}, top_needs: [], model: { mode: 'blend', model_version: 'v', reviewed_rows: 0, needed: 20, description: 'd' } },
    'GET /admin/forecast': { periods_days: 30, items: REC.need.forecast, summary: { categories: 1, high_risk: 0, rising: 1 } },
    'GET /admin/audit': { total: 0, actions: [], items: [] }, 'GET /admin/2fa/status': { enabled: true, recovery_codes_left: 8 },
    ...extra
  }
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    if (!(key in routes)) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: `no mock for ${key}` }) }
    const v = routes[key]
    return { ok: true, status: 200, text: async () => JSON.stringify(typeof v === 'function' ? v(init, url) : v) }
  })
}
const signedIn = (u) => { localStorage.setItem('cb_token', 'tok'); localStorage.setItem('cb_user', JSON.stringify({ id: u.id, email: u.email, role: u.role, name: u.display_name, organization_id: null, donor_id: null, volunteer_id: null })) }
const mount = (path) => render(<MemoryRouter initialEntries={[path]}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>)
const calls = (suffix, method = 'GET') => global.fetch.mock.calls.filter(([u, i]) => String(u).split('?')[0].endsWith(suffix) && (i?.method || 'GET') === method)

beforeEach(() => { document.documentElement.classList.remove('dark') })

describe('beginner guide', () => {
  it('visitors see the five-step picture and can switch role tabs', async () => {
    mockApi()
    const user = userEvent.setup()
    mount('/guide')
    expect(await screen.findByRole('heading', { name: /how carebridge ai works/i, level: 1 })).toBeInTheDocument()
    const imgs = screen.getAllByRole('img').filter((i) => i.getAttribute('src')?.startsWith('/images/carebridge-'))
    expect(imgs).toHaveLength(4)
    expect(imgs.every((i) => i.getAttribute('alt').length > 40)).toBe(true)  // meaningful alt text for screen readers
    expect(screen.getByText('Sign up and wait for verification')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /donor/i }))
    expect(screen.getByText('Sign up and say what you like to support')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /download image/i })).toHaveLength(4)
  })

  it('signed-in people start on their own role and find the guide in the menu', async () => {
    signedIn(U('volunteer')); mockApi({}, U('volunteer'))
    mount('/guide')
    expect(await screen.findByText('Sign up with your skills')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /how it works/i }).length).toBeGreaterThan(0)
  })
})

describe('AI suggestion hub', () => {
  it('shows donors, volunteers, resources and partner organizations for a need, with the forecast', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin/recommend')
    expect(await screen.findByText('Best donors')).toBeInTheDocument()
    for (const t of ['Best volunteers', 'Resources that fit', 'Partner organizations holding resources', 'Predicted demand for the related categories']) expect(screen.getByText(t)).toBeInTheDocument()
    expect(screen.getByText('Edu Donor')).toBeInTheDocument() && expect(screen.getByText('Textbook set')).toBeInTheDocument()
    expect(screen.getByText(/units next 30 days/i)).toBeInTheDocument()
    expect(screen.getByText(/About 120 unit\(s\) expected but only 30 in stock/)).toBeInTheDocument()
    expect(calls('/admin/recommend')[0][0]).toContain('entity=need&id=5')
  })

  it('exploring a suggested donor switches the hub to that donor, and unverified organizations are flagged', async () => {
    signedIn(ADMIN); mockApi()
    const user = userEvent.setup()
    mount('/admin/recommend')
    await user.click(await screen.findByRole('button', { name: /explore edu donor/i }))
    expect(await screen.findByText('Needs this donor should support')).toBeInTheDocument()
    expect(screen.getByText('unverified')).toBeInTheDocument()
    expect(calls('/admin/recommend').some(([u]) => String(u).includes('entity=donor&id=2'))).toBe(true)
    expect(screen.getByRole('tab', { name: /^donor$/i })).toHaveAttribute('aria-selected', 'true')
  })

  it('sends a need\'s suggestions to the review queue in one click', async () => {
    signedIn(ADMIN)
    mockApi({ 'POST /admin/needs/5/suggest-donors': { suggestions: [] }, 'POST /admin/needs/5/suggest-volunteers': { suggestions: [] }, 'POST /admin/needs/5/suggest-resources': { allocations: [] } })
    const user = userEvent.setup()
    mount('/admin/recommend')
    await user.click(await screen.findByRole('button', { name: /send suggestions to review queue/i }))
    await waitFor(() => expect(calls('/admin/needs/5/suggest-donors', 'POST')).toHaveLength(1))
    expect(calls('/admin/needs/5/suggest-volunteers', 'POST')).toHaveLength(1) && expect(calls('/admin/needs/5/suggest-resources', 'POST')).toHaveLength(1)
    expect(await screen.findByText(/added to the review queue/i)).toBeInTheDocument()
  })
})

describe('volunteers, review queue and forecast', () => {
  const VOLS = [{ id: 3, name: 'Tutor', contact: 't@x', skills: 'teaching', availability: 'weekends', location: null, organization_id: 1, organization_name: 'Hope Home', account_email: null, matches: 2, pending_suggestions: 1 },
    { id: 4, name: 'Nurse', contact: 'n@x', skills: 'healthcare', availability: '', location: null, organization_id: null, organization_name: null, account_email: 'n@x.org', matches: 0, pending_suggestions: 0 }]

  it('lists volunteers of every organization, filters, shows matching needs, and flags missing availability', async () => {
    signedIn(ADMIN)
    mockApi({ 'GET /admin/volunteers': VOLS, 'GET /admin/organizations': [{ id: 1, name: 'Hope Home' }],
      'GET /admin/volunteers/3': { ...VOLS[0], matches_history: [{ id: 1, need_category: 'Books', status: 'confirmed', score: 0.8, created_at: '2026-09-01T10:00:00' }],
        recommended_needs: [{ need_id: 5, category: 'Tutoring', urgency: 'high', quantity: 3, organization_name: 'Little Stars', priority_score: 0.8, fit_score: 0.7, reasons: ['Skill match'] }] } })
    const user = userEvent.setup()
    mount('/admin/volunteers')
    expect(await screen.findByText('Tutor')).toBeInTheDocument() && expect(screen.getByText('Nurse')).toBeInTheDocument()
    expect(screen.getByText('not stated')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/search volunteers/i), 'health')
    expect(screen.queryByText('Tutor')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText(/search volunteers/i))
    await user.click((await screen.findAllByRole('button', { name: /^view$/i }))[0])
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Tutoring')).toBeInTheDocument() && expect(within(dialog).getByText('Books')).toBeInTheDocument()
  })

  it('adds a volunteer', async () => {
    signedIn(ADMIN)
    mockApi({ 'GET /admin/volunteers': [], 'GET /admin/organizations': [], 'POST /admin/volunteers': { id: 9, name: 'New' } })
    const user = userEvent.setup()
    mount('/admin/volunteers')
    await user.click(await screen.findByRole('button', { name: /add volunteer/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getAllByRole('textbox')[0], 'New Helper')
    await user.click(within(dialog).getByRole('button', { name: /^add volunteer$/i }))
    await waitFor(() => expect(calls('/admin/volunteers', 'POST')).toHaveLength(1))
    expect(JSON.parse(calls('/admin/volunteers', 'POST')[0][1].body)).toMatchObject({ name: 'New Helper', organization_id: null })
  })

  it('the review queue has a volunteer suggestion tab with approve, contact and reject', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin/review')
    expect(await screen.findByText('Tutor → Books')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /volunteer suggestion \(1\)/i })).toBeInTheDocument()
    for (const b of [/^approve$/i, /mark contacted/i, /^reject$/i]) expect(screen.getByRole('button', { name: b })).toBeInTheDocument()
  })

  it('the workflow page shows predicted demand', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin')
    expect(await screen.findByText('Predicted demand (next 30 days)')).toBeInTheDocument()
    expect(await screen.findByText(/units next 30 days/i)).toBeInTheDocument()
  })
})

describe('assistant confidence and knowledge tools', () => {
  const status = { knowledge_entries: 3, embedded_entries: 0, needs_indexing: 3, mode: 'retrieval_only', guide_entries_available: 57, guide_entries_loaded: 0, dense_vectors: false }

  it('abstains visibly on a low-confidence answer and lets an administrator load the guide', async () => {
    signedIn(ADMIN)
    mockApi({ 'GET /assistant/status': status, 'GET /assistant/history': [], 'GET /assistant/insights': { generated_at: '2026-10-09T10:00:00Z', scope: 'admin', health: [], selection: [], snapshot: null },
      'GET /assistant/gaps': [{ question: 'How do I bake bread?', times: 3, best_confidence: 0.1, last_asked: '2026-10-09T10:00:00' }],
      'POST /assistant/knowledge/seed-defaults': { added: 57, updated: 0, total: 57, embedded_now: 0, embedded_total: 0, dense_available: false },
      'POST /assistant/ask': { conversation_id: 1, question: 'q', answer: 'I am not confident that the knowledge base answers this question, so I will not guess.', answer_mode: 'low_confidence',
        matches: [{ id: 1, title: 'Closest passage', content: 'Some text', source: 'CareBridge guide', score: 0.2, confidence: 0.2, label: 'low', answerable: false }],
        confidence: { value: 0.2, label: 'low', answerable: false, threshold: 0.33 }, records: [], live_sources: [], analysis: null, follow_ups: [], focus: [], follow_up_of: null } })
    const user = userEvent.setup()
    mount('/assistant')
    expect(await screen.findByText(/questions the assistant could not answer \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText('How do I bake bread?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /load carebridge guide \(57 entries\)/i }))
    expect(await screen.findByText(/57 added, 0 updated/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/your question/i), 'Something unrelated')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByText(/low confidence: these are only the closest passages/i)).toBeInTheDocument()
    expect(screen.getByText(/low confidence · 20%/i)).toBeInTheDocument()
  })

  it('a confident answer shows its confidence level', async () => {
    signedIn(U('organization', { organization_id: 1 }))
    mockApi({ 'GET /assistant/status': { ...status, guide_entries_loaded: 57 }, 'GET /assistant/history': [], 'GET /assistant/insights': { generated_at: '2026-10-09T10:00:00Z', scope: 'organization', health: [], selection: [], snapshot: null },
      'POST /assistant/ask': { conversation_id: 2, question: 'q', answer: 'Passages below.', answer_mode: 'retrieval_only', matches: [{ id: 2, title: 'Account lockout after wrong passwords', content: 'After 5 wrong passwords...', source: 'Security guide', score: 0.7, confidence: 0.7, label: 'high', answerable: true }],
        confidence: { value: 0.7, label: 'high', answerable: true, threshold: 0.33 }, records: [], live_sources: [], analysis: null, follow_ups: [], focus: [], follow_up_of: null } }, U('organization', { organization_id: 1 }))
    const user = userEvent.setup()
    mount('/assistant')
    await user.type(await screen.findByLabelText(/your question/i), 'lockout?')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByText(/answer confidence: high \(70%\)/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load carebridge guide/i })).not.toBeInTheDocument()  // administrators only
  })
})
