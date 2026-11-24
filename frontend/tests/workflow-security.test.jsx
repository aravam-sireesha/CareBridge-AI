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
const ORG = { ...ADMIN, id: 3, email: 'org@x.org', role: 'organization', display_name: 'Hope Home', organization_id: 1 }

const item = (key, label, count, detail = '') => ({ key, label, detail, count, to: '/x' })
const WORKFLOW = {
  generated_at: '2026-10-09T10:00:00Z', open_needs: 3, pending: { total: 2, by_type: { fraud_flag: 1, match: 1 } },
  stages: [
    { key: 'input', title: 'Data Input', items: [item('children', 'Children', 12), item('organizations', 'Organizations', 4, '3 verified'), item('donors', 'Donors', 9), item('volunteers', 'Volunteers', 5), item('resources', 'Resources', 7)] },
    { key: 'processing', title: 'AI Processing & Analysis', items: [item('predict', 'Predictive need analysis', 2), item('fraud', 'Fraud / anomaly detection', 1), item('matching', 'Donor & volunteer matching', 3), item('career', 'Career guidance', 0)] },
    { key: 'decision', title: 'Decision & Collaboration', items: [item('assistant', 'AI Assistant (RAG)', 20), item('review', 'Administrator review & approve', 2)] },
    { key: 'action', title: 'Action & Support', items: [item('connect', 'Connect donors & volunteers', 1), item('allocate', 'Allocate resources', 2), item('guidance', 'Provide guidance', 0), item('coordinate', 'Coordinate with organizations', 3)] },
    { key: 'outcomes', title: 'Better Outcomes', items: [item('timely', 'Timely support for children', 40), item('efficient', 'Efficient resource utilization', 25), item('trust', 'Transparency & trust', 75), item('impact', 'Stronger social impact', 12)] }
  ]
}
const QUEUE = { total: 2, counts: { fraud_flag: 1, match: 1 }, items: [
  { type: 'fraud_flag', id: 7, key: 'fraud_flag:7', title: 'Suspicious donation #7', subtitle: 'Edu Donor · 90,000', score: 0.91, reasons: ['Unusually large amount'], severity: 'high', decisions: ['confirmed_fraud', 'false_positive'], created_at: null },
  { type: 'match', id: 3, key: 'match:3', title: 'Match for Books', subtitle: 'Edu Donor + Tutor', score: 0.7, reasons: ['Skills match'], severity: 'medium', decisions: ['confirmed', 'rejected'], created_at: null }] }
const OVERVIEW = { totals: { organizations: 4, unverified_organizations: 1, needs: 9, open_needs: 5, critical_needs: 2, donors: 9, suggestions_waiting: 3 }, suggestions_by_status: {}, needs_by_priority: {}, top_needs: [], model: { mode: 'blend', model_version: 'donor-ml-1.0.0-blend', reviewed_rows: 1, needed: 20, description: 'blend' } }

function mockApi(extra = {}, me = ADMIN) {
  const routes = {
    'GET /auth/me': me, 'GET /': { status: 'running' }, 'GET /admin/workflow': WORKFLOW, 'GET /admin/review-queue': QUEUE, 'GET /admin/overview': OVERVIEW,
    'GET /admin/audit': { total: 1, actions: ['auth.login'], items: [{ id: 1, created_at: '2026-10-09T10:00:00', actor_email: 'boss@carebridge.org', actor_role: 'admin', action: 'auth.login', entity_type: null, entity_id: null, detail: null, ip: '10.0.0.1' }] },
    'GET /admin/2fa/status': { enabled: false, recovery_codes_left: 0 },
    ...extra
  }
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    if (!(key in routes)) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: `no mock for ${key}` }) }
    const v = routes[key]
    if (v && v.__error) return { ok: false, status: v.status || 400, text: async () => JSON.stringify({ detail: v.__error }) }
    return { ok: true, status: 200, text: async () => JSON.stringify(typeof v === 'function' ? v(init) : v) }
  })
}
const signedIn = (u) => { localStorage.setItem('cb_token', 'tok'); localStorage.setItem('cb_user', JSON.stringify({ id: u.id, email: u.email, role: u.role, name: u.display_name, organization_id: u.organization_id, donor_id: null, volunteer_id: null })) }
const mount = (path) => render(<MemoryRouter initialEntries={[path]}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>)
const posts = (suffix) => global.fetch.mock.calls.filter(([u, i]) => String(u).endsWith(suffix) && i?.method === 'POST')

beforeEach(() => { document.documentElement.classList.remove('dark') })

describe('workflow console', () => {
  it('shows the five stages with live numbers and the pending decisions', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin')
    for (const title of ['Data Input', 'AI Processing & Analysis', 'Decision & Collaboration', 'Action & Support', 'Better Outcomes']) expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.getByLabelText('Organizations: 4')).toBeInTheDocument()
    expect(screen.getByLabelText('Transparency & trust: 75 percent')).toBeInTheDocument()
    expect(await screen.findByText('Suspicious donation #7')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run all ai scans/i })).toBeInTheDocument()
  })

  it('an administrator decision from the board is saved through the review endpoint', async () => {
    signedIn(ADMIN); mockApi({ 'POST /admin/review-queue/fraud_flag/7': { status: 'ok' } })
    const user = userEvent.setup()
    mount('/admin')
    await user.click(await screen.findByRole('button', { name: /confirm fraud/i }))
    await waitFor(() => expect(posts('/admin/review-queue/fraud_flag/7')).toHaveLength(1))
    expect(JSON.parse(posts('/admin/review-queue/fraud_flag/7')[0][1].body)).toEqual({ decision: 'confirmed_fraud' })
  })

  it('one click runs every AI scan and reports what it found', async () => {
    signedIn(ADMIN); mockApi({ 'POST /admin/workflow/run-scans': { predicted_needs: 2, donations_scanned: 5, new_fraud_flags: 1, donor_suggestions: 4, resource_proposals: 3 } })
    const user = userEvent.setup()
    mount('/admin')
    await user.click(await screen.findByRole('button', { name: /run all ai scans/i }))
    expect(await screen.findByText(/2 predicted need\(s\), 1 new fraud flag\(s\), 4 donor suggestion\(s\), 3 resource proposal\(s\)/)).toBeInTheDocument()
  })

  it('the review queue filters by type', async () => {
    signedIn(ADMIN); mockApi()
    const user = userEvent.setup()
    mount('/admin/review')
    expect(await screen.findByText('Match for Books')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /suspicious donation \(1\)/i }))
    expect(screen.queryByText('Match for Books')).not.toBeInTheDocument()
    expect(screen.getByText('Suspicious donation #7')).toBeInTheDocument()
  })

  it('the audit trail lists events', async () => {
    signedIn(ADMIN); mockApi()
    mount('/admin/audit')
    expect(await screen.findByText('Auth login')).toBeInTheDocument()
    expect(screen.getByText('10.0.0.1')).toBeInTheDocument()
  })

  it('shows the workflow to visitors on the home page and nav entries to administrators', async () => {
    mockApi()
    const { unmount } = mount('/')
    expect(await screen.findByText('From a child\'s need to a better outcome')).toBeInTheDocument()
    expect(screen.getAllByText('Predictive need analysis').length).toBeGreaterThan(0)
    unmount()
    signedIn(ADMIN)
    mount('/admin')
    await screen.findByText('Data Input')
    for (const name of [/review queue/i, /^resources$/i, /audit trail/i]) expect(screen.getAllByRole('link', { name }).length).toBeGreaterThan(0)
  })
})

describe('secure authentication screens', () => {
  it('two-step administrator sign-in asks for the code after the password', async () => {
    mockApi({
      'POST /admin/login': { mfa_required: true, mfa_token: 'mfa-token-123456' },
      'POST /admin/login/verify': { access_token: 'tok', token_type: 'bearer', user: ADMIN, admin: {} }
    })
    const user = userEvent.setup()
    mount('/admin/login')
    await user.type(screen.getByPlaceholderText(/admin@carebridge.org/i), 'boss@carebridge.org')
    await user.type(screen.getByPlaceholderText(/your password/i), 'StrongPass1234!')
    await user.click(screen.getByRole('button', { name: /sign in as administrator/i }))
    const code = await screen.findByLabelText(/verification code/i)
    expect(localStorage.getItem('cb_token')).toBeNull()  // not signed in yet
    await user.type(code, '123456')
    await user.click(screen.getByRole('button', { name: /verify and sign in/i }))
    await screen.findByText('Data Input')
    expect(JSON.parse(posts('/admin/login/verify')[0][1].body)).toEqual({ mfa_token: 'mfa-token-123456', code: '123456' })
    expect(localStorage.getItem('cb_token')).toBe('tok')
  })

  it('a wrong code shows the server message and stays on the code step', async () => {
    mockApi({ 'POST /admin/login': { mfa_required: true, mfa_token: 'mfa-token-123456' }, 'POST /admin/login/verify': { __error: 'That code is not correct.', status: 401 } })
    const user = userEvent.setup()
    mount('/admin/login')
    await user.type(screen.getByPlaceholderText(/admin@carebridge.org/i), 'boss@carebridge.org')
    await user.type(screen.getByPlaceholderText(/your password/i), 'StrongPass1234!')
    await user.click(screen.getByRole('button', { name: /sign in as administrator/i }))
    await user.type(await screen.findByLabelText(/verification code/i), '000000')
    await user.click(screen.getByRole('button', { name: /verify and sign in/i }))
    expect(await screen.findByText(/that code is not correct/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/verification code/i)).toBeInTheDocument()
  })

  it('Settings > Security changes the password and keeps this session', async () => {
    signedIn(ORG); mockApi({ 'POST /auth/change-password': { access_token: 'fresh-token', token_type: 'bearer' } }, ORG)
    const user = userEvent.setup()
    mount('/settings?tab=security')
    await user.type(await screen.findByLabelText(/current password/i), 'StrongPass1234!')
    await user.type(screen.getByLabelText(/^new password$/i), 'Another-Strong-9876')
    await user.type(screen.getByLabelText(/confirm new password/i), 'Another-Strong-9876')
    await user.click(screen.getByRole('button', { name: /^change password$/i }))
    await waitFor(() => expect(localStorage.getItem('cb_token')).toBe('fresh-token'))
    expect(JSON.parse(posts('/auth/change-password')[0][1].body)).toEqual({ current_password: 'StrongPass1234!', new_password: 'Another-Strong-9876' })
    expect(screen.queryByText(/two-step verification/i)).not.toBeInTheDocument()  // administrators only
  })

  it('administrators can set up two-step verification and are shown recovery codes once', async () => {
    signedIn(ADMIN)
    mockApi({ 'POST /admin/2fa/setup': { secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/CareBridge%20AI:boss?secret=JBSWY3DPEHPK3PXP' },
      'POST /admin/2fa/enable': { enabled: true, recovery_codes: ['AAAAA-BBBBB', 'CCCCC-DDDDD'] } })
    const user = userEvent.setup()
    mount('/settings?tab=security')
    await user.click(await screen.findByRole('button', { name: /set up two-step verification/i }))
    expect(await screen.findByTestId('setup-key')).toHaveTextContent('JBSW Y3DP EHPK 3PXP')
    await user.type(screen.getByLabelText(/6-digit code/i), '123456')
    await user.click(screen.getByRole('button', { name: /^turn on$/i }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('AAAAA-BBBBB')).toBeInTheDocument()
    await user.click(within(alert).getByRole('button', { name: /i have saved them/i }))
    expect(screen.queryByText('AAAAA-BBBBB')).not.toBeInTheDocument()
  })

  it('organizations manage their own resources', async () => {
    signedIn(ORG)
    mockApi({ 'GET /resources/': [], 'POST /resources/': { id: 1, name: 'Textbooks' } }, ORG)
    const user = userEvent.setup()
    mount('/resources')
    await user.click(await screen.findByRole('button', { name: /add resource/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getAllByRole('textbox')[0], 'Textbooks')
    await user.click(within(dialog).getByRole('button', { name: /^add resource$/i }))
    await waitFor(() => expect(posts('/resources/')).toHaveLength(1))
    expect(JSON.parse(posts('/resources/')[0][1].body)).toMatchObject({ name: 'Textbooks', kind: 'material' })
  })
})
