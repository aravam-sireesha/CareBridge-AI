import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ThemeProvider } from '../src/context/ThemeContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const ADMIN = { id: 1, email: 'boss@x.org', role: 'admin', display_name: 'Asha', organization_id: null, donor_id: null, volunteer_id: null }
const VALID = { schema_ok: true, rag_ok: true, constraints_ok: true, numbers_ok: true, ungrounded: [], warnings: [] }

const AGENT_FORECAST = { question: 'Forecast books demand', route: { route: 'prediction', routes: ['prediction'], complexity: 'simple' }, planned_by: 'rules', mode: 'template', duration_ms: 42,
  plan: [], steps: [{ tool: 'forecast_demand', kind: 'ml', agent: 'analyst', status: 'ok', ms: 5, why: 'Forecast demand with a backtested model.', args: {}, requires_approval: false, output: { items: [{ category: 'books', forecast: 4.2 }] } }],
  answer: 'Next month for books: about 4.2 request(s), using naive.', citations: [], proposals: [], requires_approval: false, validation: VALID, trace: [] }
const AGENT_OPT = { ...AGENT_FORECAST, question: 'Allocate the books fairly', route: { route: 'optimization', routes: ['optimization'], complexity: 'simple' }, answer: 'The allocation plan gives out 40 units. This is a proposal that needs human approval.',
  steps: [{ tool: 'optimize_allocation', kind: 'optimization', agent: 'optimizer', status: 'ok', ms: 30, why: 'Allocate scarce stock.', args: {}, requires_approval: true, output: {} }], requires_approval: true }
const AGENT_KNOW = { ...AGENT_FORECAST, question: 'Lock?', route: { route: 'knowledge', routes: ['knowledge'], complexity: 'simple' }, answer: 'After 5 wrong passwords the account is locked for 15 minutes [1].',
  steps: [{ tool: 'retrieve_knowledge', kind: 'knowledge', agent: 'retriever', status: 'ok', ms: 8, why: 'Retrieve it with citations.', args: {}, requires_approval: false, output: { answer: 'x' } }],
  citations: [{ n: 1, title: 'Account lockout after wrong passwords', source: 'Security guide', kind: 'knowledge' }] }

const OPT = { kind: 'allocation', metrics: { utility: 120.5, units_allocated: 40, unmet_units: 60, min_coverage: 0.52, jain: 0.99, best_possible_min_coverage: 0.52 }, baseline: { utility: 130, units_allocated: 45, unmet_units: 55, min_coverage: 0, jain: 0.63 },
  allocations: [{ supply_id: 1, demand_id: 5, units: 12, relevance: 0.9 }], assignments: [], notes: ['the worst-served need stays at zero coverage because stock is too scarce'], violations: [], proposals_created: [], requires_approval: true }

function mockApi(extra = {}) {
  const routes = {
    'GET /auth/me': ADMIN, 'GET /': { status: 'running' },
    'GET /admin/ai/models': { problem: 'Will a need be fulfilled within 14 days of being posted?', trained: false, meta: null, real_labelled_needs: 12, min_rows: 80, min_per_class: 12, note: 'The baseline (urgency prior) is used until there is enough real history.' },
    'GET /admin/ai/forecast': [{ category: 'books', method: 'naive', forecast: 4.2, history: [1, 2, 3], confident: true, skill_vs_naive: 0.12 }],
    'GET /admin/ai/anomalies': { donations: [{ donation_id: 7, donor_id: 2, amount: 980000, anomaly_score: 0.97, reasons: ['amount is unusual'] }], needs: { clusters: [], outliers: [] } },
    'GET /admin/ai/segments': { k: 3, segments: [{ segment: 0, name: 'Loyal', donors: 8, median_gifts: 6, median_amount: 900, median_recency_days: 20 }], donors: [] },
    'GET /admin/ai/data-quality': { ok: false, errors: 1, warnings: 0, tables: { needs: 9, donors: 2 }, issues: [{ code: 'resource_stock', severity: 'error', category: 'inventory', title: 'Inventory does not add up', count: 1, examples: ["Resource #2: available=3, expected 10"], hint: 'Run the repair.', auto_fixable: true }] },
    'GET /admin/ai/report': { available: false, hint: 'Run: python scripts/run_ai_pipeline.py' },
    'POST /agent/run': (init) => (JSON.parse(init.body).question.toLowerCase().includes('allocate') ? AGENT_OPT : JSON.parse(init.body).question.toLowerCase().includes('lock') ? AGENT_KNOW : AGENT_FORECAST),
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
const signedIn = () => { localStorage.setItem('cb_token', 'tok'); localStorage.setItem('cb_user', JSON.stringify({ id: 1, email: ADMIN.email, role: 'admin', name: 'Asha', organization_id: null, donor_id: null, volunteer_id: null })) }
const mount = (path = '/admin/ai-lab') => render(<MemoryRouter initialEntries={[path]}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>)
const calls = (suffix, method = 'POST') => global.fetch.mock.calls.filter(([u, i]) => String(u).split('?')[0].endsWith(suffix) && (i?.method || 'GET') === method)

beforeEach(() => { document.documentElement.classList.remove('dark'); signedIn() })

describe('AI Lab', () => {
  it('runs the agent and shows the route, the tools it used, the answer and every verifier check', async () => {
    mockApi()
    const user = userEvent.setup()
    mount()
    await user.type(await screen.findByLabelText(/ask the ai agent/i), 'Forecast books demand')
    await user.click(screen.getByRole('button', { name: /run agent/i }))
    expect(await screen.findByText(/Next month for books: about 4.2/)).toBeInTheDocument()
    expect(JSON.parse(calls('/agent/run')[0][1].body)).toEqual({ question: 'Forecast books demand', create_proposals: false })
    expect(screen.getByText('route: prediction')).toBeInTheDocument()
    expect(screen.getByText('forecast_demand')).toBeInTheDocument() && expect(screen.getByText('analyst')).toBeInTheDocument()
    for (const label of [/structured outputs valid/i, /citations supported/i, /constraints respected/i, /numbers come from tools/i]) expect(screen.getByText(label)).toBeInTheDocument()
    expect(screen.queryByText(/is a proposal, not an action/i)).not.toBeInTheDocument()
  })

  it('cited knowledge answers show their sources', async () => {
    mockApi()
    const user = userEvent.setup()
    mount()
    await user.type(await screen.findByLabelText(/ask the ai agent/i), 'Lock?')
    await user.click(screen.getByRole('button', { name: /run agent/i }))
    expect(await screen.findByText(/\[1\] Account lockout after wrong passwords/)).toBeInTheDocument()
    expect(screen.getByText('retriever')).toBeInTheDocument()
  })

  it('optimiser answers are labelled as proposals and only enter the review queue when the box is ticked', async () => {
    mockApi()
    const user = userEvent.setup()
    mount()
    await user.type(await screen.findByLabelText(/ask the ai agent/i), 'Allocate the books fairly')
    await user.click(screen.getByRole('button', { name: /run agent/i }))
    expect(await screen.findByText(/Tick the box above to add it to the review queue/i)).toBeInTheDocument()
    await user.click(screen.getByLabelText(/add optimiser plans to the review queue as proposals/i))
    await user.click(screen.getByRole('button', { name: /run agent/i }))
    await waitFor(() => expect(calls('/agent/run')).toHaveLength(2))
    expect(JSON.parse(calls('/agent/run')[1][1].body).create_proposals).toBe(true)
  })

  it('example questions run immediately', async () => {
    mockApi()
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /allocate the books and food fairly/i }))
    await waitFor(() => expect(calls('/agent/run')).toHaveLength(1))
    expect(JSON.parse(calls('/agent/run')[0][1].body).question).toMatch(/allocate the books/i)
  })

  it('shows the prediction status, trains only when allowed, predicts for a need and lists forecasts, anomalies and segments', async () => {
    mockApi({ 'POST /admin/ai/models/train': { trained: false, rows: 12, reason: 'Needs at least 80 labelled needs with 12 of each outcome; the baseline stays in use.' },
      'GET /admin/ai/predict/5': { need_id: 5, probability: 0.63, risk: 'medium', model: 'baseline (urgency prior)', trained_on: '12 real labelled needs', factors: [{ feature: 'urgency', value: 3, effect: 0.12 }], note: '' } })
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('tab', { name: /predictions & forecasts/i }))
    expect(await screen.findByText(/Will a need be fulfilled within 14 days/)).toBeInTheDocument()
    expect(screen.getByText('baseline in use')).toBeInTheDocument() && expect(screen.getByText(/12 real labelled needs/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /train on real data/i }))
    expect(await screen.findByText(/Needs at least 80 labelled needs/)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/need number/i), '5')
    await user.click(screen.getByRole('button', { name: /^predict$/i }))
    expect(await screen.findByText(/chance of fulfilment within 14 days/i)).toBeInTheDocument()
    expect(screen.getByText(/urgency \(\+12 pts\)/)).toBeInTheDocument()
    expect(await screen.findByText('books')).toBeInTheDocument()
    expect(screen.getByText(/Donation 7 · amount 980000/)).toBeInTheDocument() && expect(screen.getByText('Loyal')).toBeInTheDocument()
  })

  it('previews an allocation against the greedy baseline, verifies constraints, and adds proposals only on request', async () => {
    mockApi({ 'POST /admin/ai/optimize/allocation': (init) => ({ ...OPT, proposals_created: JSON.parse(init.body).create_proposals ? [{ type: 'allocation', id: 1 }, { type: 'allocation', id: 2 }] : [] }) })
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('tab', { name: /optimisation/i }))
    const card = screen.getAllByRole('button', { name: /run \(preview\)/i })[0]
    await user.selectOptions(screen.getByLabelText(/^fairness$/i), 'floor')
    await user.click(card)
    expect(await screen.findByText(/every constraint verified independently/i)).toBeInTheDocument()
    expect(screen.getByText('52%')).toBeInTheDocument() && expect(screen.getByText(/greedy: 0%/)).toBeInTheDocument()
    expect(screen.getByText(/Proposal only/)).toBeInTheDocument()
    expect(JSON.parse(calls('/admin/ai/optimize/allocation')[0][1].body)).toMatchObject({ fairness: 'floor', urgent_first: true, create_proposals: false })
    await user.click(screen.getByRole('button', { name: /add as proposals/i }))
    expect(await screen.findByText(/2 proposal\(s\) added to the review queue/i)).toBeInTheDocument()
    expect(JSON.parse(calls('/admin/ai/optimize/allocation')[1][1].body).create_proposals).toBe(true)
  })

  it('shows data-quality problems and repairs the safe ones', async () => {
    mockApi({ 'POST /admin/ai/data-quality/repair': { changed: { resource_stock: 1 }, report: {} } })
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('tab', { name: /data quality/i }))
    expect(await screen.findByText(/Inventory does not add up/)).toBeInTheDocument()
    expect(screen.getByText(/1 error\(s\)/)).toBeInTheDocument() && expect(screen.getByText(/Resource #2: available=3, expected 10/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /repair automatically/i }))
    await waitFor(() => expect(calls('/admin/ai/data-quality/repair')).toHaveLength(1))
    expect(JSON.parse(calls('/admin/ai/data-quality/repair')[0][1].body)).toEqual({ fixes: ['resource_stock'] })
  })

  it('the benchmark report tab explains how to create the report, and shows it when it exists', async () => {
    mockApi()
    const user = userEvent.setup()
    const { unmount } = mount()
    await user.click(await screen.findByRole('tab', { name: /benchmark report/i }))
    expect(await screen.findByText(/python scripts\/run_ai_pipeline.py/)).toBeInTheDocument()
    unmount()
    mockApi({ 'GET /admin/ai/report': { available: true, dataset_note: 'Synthetic benchmarks measure methods, not real-world accuracy.', phase3_need_model: { data: 'synthetic', oracle_test_auc: 0.72, selected: 'logistic regression',
      table: [{ model: 'logistic regression', cv_auc_mean: 0.735, test_roc_auc: 0.699, test_ece: 0.04 }, { model: 'baseline (urgency prior)', cv_auc_mean: 0.575, test_roc_auc: 0.558, test_ece: 0.03 }] },
      phase2_rag: { fresh: { 'hybrid (BM25 + n-gram + fusion + rerank)': { recall_at_3: 0.59 } } } } })
    mount()
    await user.click(await screen.findByRole('tab', { name: /benchmark report/i }))
    expect(await screen.findByText(/measure methods, not real-world accuracy/)).toBeInTheDocument()
    expect(screen.getByText(/logistic regression ✓/)).toBeInTheDocument() && expect(screen.getByText(/fresh:/)).toBeInTheDocument()
  })

  it('administrators see AI Lab in the menu', async () => {
    mockApi()
    mount()
    await screen.findByLabelText(/ask the ai agent/i)
    expect(screen.getAllByRole('link', { name: /ai lab/i }).length).toBeGreaterThan(0)
  })
})
