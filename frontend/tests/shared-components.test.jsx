import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import DataTable from '../src/components/DataTable.jsx'
import StatusBadge from '../src/components/StatusBadge.jsx'
import AdminAlerts from '../src/components/AdminAlerts.jsx'
import NeedAssist from '../src/components/NeedAssist.jsx'
import ForecastChart from '../src/components/ForecastChart.jsx'
import { speechMessage } from '../src/hooks/useSpeechInput.js'

const json = (v, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(v), json: async () => v })
const ROWS = Array.from({ length: 23 }, (_, i) => ({ id: i + 1, name: `Item ${String(i + 1).padStart(2, '0')}`, status: i % 3 === 0 ? 'pending' : 'approved', qty: 100 - i }))
const COLS = [{ key: 'name', header: 'Name', sortValue: (r) => r.name }, { key: 'status', header: 'Status', sortValue: (r) => r.status, render: (r) => <StatusBadge status={r.status} /> }, { key: 'qty', header: 'Quantity', sortValue: (r) => r.qty }]
const FILTERS = [{ key: 'status', label: 'Status', options: [{ value: 'pending', label: 'pending' }, { value: 'approved', label: 'approved' }] }]
const setWidth = (narrow) => { window.matchMedia = vi.fn().mockImplementation((q) => ({ matches: narrow && q.includes('max-width'), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })) }
beforeEach(() => setWidth(false))

describe('StatusBadge', () => {
  it('uses one semantic colour per meaning and a neutral fallback for anything unknown', () => {
    const cls = (s) => render(<StatusBadge status={s} />).container.firstChild.className
    expect(cls('pending')).toMatch(/amber/); expect(cls('approved')).toMatch(/green/); expect(cls('rejected')).toMatch(/red/)
    expect(cls('In Progress')).toMatch(/sky/); expect(cls('delivered')).toMatch(/green/); expect(cls('cancelled')).toMatch(/ink/)
    expect(cls('totally-new-status')).toMatch(/ink/); expect(cls(null)).toMatch(/ink/); expect(cls(undefined)).toMatch(/ink/)
  })
})

describe('DataTable', () => {
  it('searches, filters, sorts and pages', async () => {
    const user = userEvent.setup()
    render(<DataTable columns={COLS} rows={ROWS} filters={FILTERS} pageSize={10} searchPlaceholder="Search items" />)
    expect(screen.getByRole('status')).toHaveTextContent('Showing 1–10 of 23')
    await user.click(screen.getByRole('button', { name: /^next$/i }))
    expect(screen.getByRole('status')).toHaveTextContent('Showing 11–20 of 23')
    await user.type(screen.getByLabelText('Search items'), 'item 05')
    expect(screen.getByRole('table')).toHaveTextContent('Item 05'); expect(screen.queryByText('Item 06')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Search items'))
    await user.selectOptions(screen.getByLabelText('Status'), 'pending')
    expect(screen.getAllByRole('row')).toHaveLength(9)                                        // header + the 8 pending rows
    expect(screen.queryByRole('navigation', { name: /pagination/i })).not.toBeInTheDocument()   // one page: no pager
    await user.click(screen.getByRole('button', { name: /quantity/i }))                       // ascending
    expect(within(screen.getAllByRole('row')[1]).getByText('Item 22')).toBeInTheDocument()   // the smallest quantity among pending rows
    expect(screen.getByRole('columnheader', { name: /quantity/i })).toHaveAttribute('aria-sort', 'ascending')
    await user.click(screen.getByRole('button', { name: /quantity/i }))                       // descending
    expect(within(screen.getAllByRole('row')[1]).getByText('Item 01')).toBeInTheDocument()
  })

  it('shows skeletons while loading, a retry on error, and honest empty states', async () => {
    const retry = vi.fn()
    const { rerender } = render(<DataTable columns={COLS} rows={null} loading label="Donations" />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading donations/i)
    rerender(<DataTable columns={COLS} rows={null} error="Server unreachable" onRetry={retry} />)
    await userEvent.click(screen.getByRole('button', { name: /try again/i })); expect(retry).toHaveBeenCalled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()                               // an error is never shown as "no records"
    rerender(<DataTable columns={COLS} rows={[]} emptyTitle="No donations have been recorded yet" />)
    expect(screen.getByText('No donations have been recorded yet')).toBeInTheDocument()
    rerender(<DataTable columns={COLS} rows={ROWS} />)
    await userEvent.type(screen.getByRole('searchbox'), 'zzzz')
    expect(screen.getByText('No matching records')).toBeInTheDocument()
  })

  it('opens a details drawer from a row, closes it with Escape and returns focus', async () => {
    const user = userEvent.setup()
    render(<DataTable columns={COLS} rows={ROWS} detail={(r) => <p>Detail for {r.name}</p>} detailTitle={(r) => `Record ${r.id}`} />)
    const button = screen.getByRole('button', { name: /details for record 1$/i })
    await user.click(button)
    expect(screen.getByRole('dialog', { name: 'Record 1' })).toHaveTextContent('Detail for Item 01')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
  })

  it('opens the record named by openId once rows are present (a link from an alert)', () => {
    render(<DataTable columns={COLS} rows={ROWS} openId="7" detail={(r) => <p>Detail for {r.name}</p>} detailTitle={(r) => `Record ${r.id}`} />)
    expect(screen.getByRole('dialog', { name: 'Record 7' })).toHaveTextContent('Detail for Item 07')
  })

  it('shows one readable card per record on small screens instead of a wide table', () => {
    setWidth(true)
    render(<DataTable columns={COLS} rows={ROWS.slice(0, 3)} label="Items" actions={(r) => <button type="button">Act {r.id}</button>} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const cards = within(screen.getByRole('list', { name: 'Items' })).getAllByRole('listitem')
    expect(cards).toHaveLength(3)
    expect(cards[0]).toHaveTextContent('Item 01'); expect(within(cards[0]).getByRole('button', { name: 'Act 1' })).toBeInTheDocument()
  })
})

describe('AdminAlerts', () => {
  const mount = () => render(<MemoryRouter><AdminAlerts /></MemoryRouter>)
  it('lists calculated alerts with links that open the records, and states what is not tracked', async () => {
    global.fetch = vi.fn(async () => json({ generated_at: '2026-10-23T09:00:00', stale_days: 14, alerts: [{ key: 'stale_needs', severity: 'high', count: 2, title: '2 needs open for 14+ days', detail: '1 of them is critical or high urgency.', link: '/needs', items: [{ label: 'Winter blankets (#4), open 20 days', link: '/needs?open=4' }] }], not_tracked: [{ key: 'overdue_deliveries', title: 'Deliveries past their expected date', reason: 'Donations do not store an expected delivery date.' }] }))
    mount()
    expect(await screen.findByText('2 needs open for 14+ days')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /winter blankets \(#4\)/i })).toHaveAttribute('href', '/needs?open=4')
    expect(screen.getByText(/do not store an expected delivery date/i)).toBeInTheDocument()
  })
  it('says plainly when nothing needs attention, and offers a retry on failure', async () => {
    global.fetch = vi.fn(async () => json({ generated_at: '2026-10-23T09:00:00', stale_days: 14, alerts: [], not_tracked: [] }))
    const { unmount } = mount()
    expect(await screen.findByText('Nothing needs attention')).toBeInTheDocument()
    unmount()
    global.fetch = vi.fn(async () => json({ detail: 'boom' }, 500))
    mount()
    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})

describe('NeedAssist', () => {
  it('shows suggestions separately and applies only the one the person accepts', async () => {
    const onUse = vi.fn()
    global.fetch = vi.fn(async () => json({ source: 'rules', notice: 'No language model is connected, so these suggestions come from simple keyword rules.', suggestions: { category: 'Clothing', urgency: 'high', title: 'We need blankets', description: 'We need 40 blankets.', missing: ['By when are they needed?'] } }))
    const user = userEvent.setup()
    render(<NeedAssist onUse={onUse} />)
    await user.click(screen.getByText(/get help filling this in/i))
    await user.type(screen.getByLabelText(/describe the need/i), 'We urgently need 40 winter blankets for the children.')
    await user.click(screen.getByRole('button', { name: /suggest details/i }))
    expect(await screen.findByText(/simple keyword rules/i)).toBeInTheDocument()
    expect(onUse).not.toHaveBeenCalled()                                                      // suggestions never reach the form by themselves
    await user.click(screen.getByRole('button', { name: /use suggested category/i }))
    expect(onUse).toHaveBeenCalledTimes(1); expect(onUse).toHaveBeenCalledWith('category', 'Clothing')
    expect(screen.getByText('By when are they needed?')).toBeInTheDocument()
  })
})

describe('ForecastChart', () => {
  const history = [{ label: 'Jun 2026', value: 2 }, { label: 'Jul 2026', value: 3 }, { label: 'Aug 2026', value: 5 }]
  it('draws a range only when the backend supplied one', () => {
    const { container, rerender } = render(<ForecastChart history={history} forecast={{ label: 'Nov 2026', value: 6, band: { lower: 4, upper: 8, n: 8 } }} category="food" />)
    expect(screen.getByRole('img')).toHaveAccessibleName(/typically between 4 and 8/i)
    expect(screen.getByText(/typical error range/i)).toBeInTheDocument()
    rerender(<ForecastChart history={history} forecast={{ label: 'Nov 2026', value: 6, band: null }} category="food" />)
    expect(screen.getByRole('img')).not.toHaveAccessibleName(/typically between/i)
    expect(screen.queryByText(/typical error range/i)).not.toBeInTheDocument()
    expect(container.querySelectorAll('circle').length).toBe(history.length + 1)
  })
})

describe('voice input messages', () => {
  it('explains permission, missing microphone and unsupported languages, and always offers typing', () => {
    expect(speechMessage('not-allowed')).toMatch(/permission was denied.*type your question/i)
    expect(speechMessage('audio-capture')).toMatch(/no microphone/i)
    expect(speechMessage('language-not-supported')).toMatch(/selected language/i)
    expect(speechMessage('something-else')).toMatch(/type your question/i)
  })
})
