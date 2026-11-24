import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import MapHub from '../src/pages/MapHub.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { api, tokenStore } from '../src/api/client.js'
import { connectLive, disconnectLive, liveStatus } from '../src/lib/liveEvents.js'

const hoursAgo = (h) => new Date(Date.now() - h * 3600_000).toISOString()
const delivery = (id, status, extra = {}) => ({
  id, status, status_label: status, need: { id: id * 10, title: `Rice ${id}`, category: 'food', urgency: 'high' }, organization: { id: 1, name: 'Hope Home' }, quantity: 40,
  points: { pickup: { latitude: 17.40, longitude: 78.45, label: 'Banjara Hills' }, delivery: { latitude: 17.385, longitude: 78.4867, label: '12 Hope Road' } },
  tracking: { can_share: false, sharing: false, can_watch: true }, created_at: hoursAgo(1), milestones: {}, allowed_actions: [], ...extra,
})
const ROUTE = { duration_s: 1260, distance_m: 11250, traffic_aware: true, arrival_at: '2026-11-05T10:21:00Z', polyline: '_p~iF~ps|U_ulLnnqC', delivery_id: 1, leg: 'delivery', provider: 'google_routes' }

function setup(role, deliveries, overrides = {}) {
  localStorage.clear(); tokenStore.set('tok')
  localStorage.setItem('cb_user', JSON.stringify({ id: 9, email: 'u@x.org', role, name: 'U' }))
  api.me = vi.fn().mockResolvedValue({ id: 9, email: 'u@x.org', role })
  api.ping = vi.fn().mockResolvedValue({}); api.unreadCount = vi.fn().mockResolvedValue({ unread: 0 })
  api.listDeliveries = vi.fn().mockResolvedValue(deliveries)
  api.getDeliveryLocation = vi.fn().mockResolvedValue({ sharing: true, has_position: false })
  api.adminMap = vi.fn().mockResolvedValue({ organizations: [], needs: [], donors: [], volunteers: [], live: [], unplaced: {} })
  api.nearbyNeeds = vi.fn().mockResolvedValue({ needs: [] })
  api.mapsConfig = vi.fn().mockResolvedValue({ geocoding: false, routes: true })
  api.mapsRoute = vi.fn().mockResolvedValue(ROUTE)
  api.deliveryLocationHistory = vi.fn().mockResolvedValue({ points: [{ latitude: 17.4, longitude: 78.4 }, { latitude: 17.41, longitude: 78.41 }], retention_days: 30 })
  Object.assign(api, overrides)                                   // per-test API behaviour, applied BEFORE the page renders
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: vi.fn((ok) => ok({ coords: { latitude: 17.39, longitude: 78.47, accuracy: 10 } })) }, configurable: true })
  return render(<MemoryRouter><AuthProvider><MapHub /></AuthProvider></MemoryRouter>)
}
const panel = async () => screen.findByRole('complementary', { name: 'Deliveries' })
// the map's own pins are buttons too, so list rows are looked up inside the side panel only
const listItem = async (title) => within(await panel()).findByRole('button', { name: new RegExp(title) })

function fakeStream() {
  let controller; const enc = new TextEncoder()
  const fetchImpl = vi.fn(async (u, init) => new Response(new ReadableStream({ start(c) { controller = c; init.signal.addEventListener('abort', () => { try { c.error(new Error('x')) } catch { /* closed */ } }) } }), { status: 200 }))
  return { fetchImpl, ready: async () => { for (let i = 0; i < 100 && !controller; i++) await new Promise((r) => setTimeout(r, 5)) },
    send: async (id, type, payload) => { controller.enqueue(enc.encode(`${id ? `id: ${id}\n` : ''}event: ${type}\ndata: ${JSON.stringify({ id, type, payload, ts: 1 })}\n\n`)); await new Promise((r) => setTimeout(r, 20)) } }
}

afterEach(() => { cleanup(); disconnectLive(); localStorage.clear() })

describe('MapHub: what each role sees and can do', () => {
  it('an organization sees its deliveries on the map, with no open-needs layer and no needs request', async () => {
    setup('organization', [delivery(1, 'in_transit'), delivery(2, 'receipt_confirmed')])
    await listItem('Rice 1')
    expect(within(await panel()).queryByRole('button', { name: /Rice 2/ })).toBeNull()       // finished deliveries are hidden by the default "In progress" filter
    expect(screen.queryByText('Show open needs')).toBeNull()
    expect(api.adminMap).toHaveBeenCalledTimes(0); expect(api.nearbyNeeds).toHaveBeenCalledTimes(0)
    await waitFor(() => expect(document.querySelector('[data-marker="d1:dest"]')).toBeTruthy())
    expect(document.querySelector('[data-marker="d2:dest"]')).toBeNull()
  })

  it('donors and volunteers load the nearby-needs layer; administrators load the admin overview', async () => {
    setup('donor', [delivery(1, 'in_transit')]); await listItem('Rice 1')
    expect(api.nearbyNeeds).toHaveBeenCalledTimes(1); expect(api.adminMap).toHaveBeenCalledTimes(0); cleanup()
    setup('admin', [delivery(1, 'in_transit')]); await listItem('Rice 1')
    expect(api.adminMap).toHaveBeenCalledTimes(1)
  })

  it('a failed needs layer does not take the deliveries down with it', async () => {
    setup('volunteer', [delivery(1, 'accepted', { tracking: { can_share: true, can_watch: true } })], { nearbyNeeds: vi.fn().mockRejectedValue(new Error('boom')) })
    await listItem('Rice 1')
    expect(await screen.findByText(/open-needs layer could not be loaded: boom/)).toBeTruthy()
    expect(document.querySelector('[data-marker="d1:dest"]')).toBeTruthy()
  })

  it('shows a clear error with a working retry when deliveries cannot be loaded', async () => {
    const listDeliveries = vi.fn().mockRejectedValueOnce(new Error('Server unreachable')).mockResolvedValue([delivery(1, 'in_transit')])
    setup('organization', [], { listDeliveries })
    expect((await screen.findAllByText(/Server unreachable/))[0]).toBeTruthy()
    fireEvent.click(screen.getByText('Try again'))
    await listItem('Rice 1')
  })

  it('the panel can be hidden and shown', async () => {
    setup('organization', [delivery(1, 'in_transit')]); await listItem('Rice 1')
    fireEvent.click(screen.getByText('Hide panel'))
    expect(screen.queryByRole('complementary', { name: 'Deliveries' })).toBeNull(); expect(screen.getByText('Show panel').getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(screen.getByText('Show panel')); await listItem('Rice 1')
  })

  it('filters by status', async () => {
    setup('organization', [delivery(1, 'in_transit'), delivery(2, 'accepted')]); await listItem('Rice 1'); await listItem('Rice 2')
    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'in_transit' } })
    await waitFor(() => expect(within(screen.getByRole('complementary', { name: 'Deliveries' })).queryByRole('button', { name: /Rice 2/ })).toBeNull())
    expect(within(screen.getByRole('complementary', { name: 'Deliveries' })).queryByRole('button', { name: /Rice 1/ })).toBeTruthy()
  })
})

describe('MapHub: routes and arrival times', () => {
  it('a volunteer asks for a route, and the device position (not a stored one) is sent with the chosen mode', async () => {
    setup('volunteer', [delivery(1, 'in_transit', { tracking: { can_share: true, sharing: true, can_watch: true } })])
    fireEvent.click(await listItem('Rice 1'))
    fireEvent.change(screen.getByLabelText('Travel mode'), { target: { value: 'two_wheeler' } })
    fireEvent.click(screen.getByText(/Route to destination/))
    await waitFor(() => expect(api.mapsRoute).toHaveBeenCalledTimes(1))
    expect(api.mapsRoute).toHaveBeenCalledWith(1, { leg: 'delivery', mode: 'two_wheeler', lat: 17.39, lon: 78.47 })
    expect(await screen.findByText('21 min')).toBeTruthy(); expect(screen.queryByText(/by road/)).toBeTruthy(); expect(screen.queryByText('Includes current traffic')).toBeTruthy()
  })

  it('before pickup the volunteer routes to the pickup, not the destination', async () => {
    setup('volunteer', [delivery(1, 'accepted', { tracking: { can_share: true, can_watch: true } })])
    fireEvent.click(await listItem('Rice 1'))
    fireEvent.click(screen.getByText(/Route to pickup/))
    await waitFor(() => expect(api.mapsRoute.mock.calls[0][1].leg).toBe('pickup'))
  })

  it('a volunteer who blocks location is told why, and no route is requested', async () => {
    setup('volunteer', [delivery(1, 'in_transit', { tracking: { can_share: true, can_watch: true } })])
    navigator.geolocation.getCurrentPosition = vi.fn((ok, err) => err({ code: 1 }))
    fireEvent.click(await listItem('Rice 1')); fireEvent.click(screen.getByText(/Route to destination/))
    expect(await screen.findByText(/Location permission was blocked/)).toBeTruthy()
    expect(api.mapsRoute).toHaveBeenCalledTimes(0)
  })

  it('a viewer gets an arrival time automatically once the volunteer is sharing, and never sends coordinates', async () => {
    const getDeliveryLocation = vi.fn().mockResolvedValue({ sharing: true, has_position: true, latitude: 17.39, longitude: 78.47, age_seconds: 3 })
    setup('organization', [delivery(1, 'in_transit')], { getDeliveryLocation })
    fireEvent.click(await listItem('Rice 1'))
    await waitFor(() => expect(api.mapsRoute).toHaveBeenCalled())
    expect(api.mapsRoute.mock.calls[0]).toEqual([1, { leg: 'delivery', mode: 'drive' }])
    expect(await screen.findByText('21 min')).toBeTruthy()
  })

  it('explains the absence of an arrival time instead of inventing one', async () => {
    setup('organization', [delivery(1, 'in_transit')])
    fireEvent.click(await listItem('Rice 1'))
    expect(await screen.findByText(/Arrival time appears once the volunteer shares their location/)).toBeTruthy()
    expect(api.mapsRoute).toHaveBeenCalledTimes(0)
  })

  it('shows the routing service\'s own explanation when it cannot produce a route', async () => {
    setup('volunteer', [delivery(1, 'in_transit', { tracking: { can_share: true, can_watch: true } })], { mapsRoute: vi.fn().mockRejectedValue(new Error('Road routing is not set up on this server, so no road distance or arrival time can be shown.')) })
    fireEvent.click(await listItem('Rice 1')); fireEvent.click(screen.getByText(/Route to destination/))
    expect(await screen.findByText(/Road routing is not set up/)).toBeTruthy()
    expect(screen.queryByText(/by road/)).toBeNull()                                        // no straight-line number is shown in its place
  })
})

describe('MapHub: administrator tools', () => {
  it('flags delayed deliveries and unconfirmed receipts, and clicking one opens it', async () => {
    setup('admin', [delivery(1, 'in_transit', { milestones: { in_transit_at: hoursAgo(9) } }), delivery(2, 'delivered', { milestones: { delivered_at: hoursAgo(40) } }), delivery(3, 'in_transit')])
    const region = await screen.findByRole('region', { name: 'Needs attention' })
    expect(within(region).queryByText(/in transit for over 6 hours/)).toBeTruthy(); expect(within(region).queryByText(/not confirmed receipt/)).toBeTruthy()
    fireEvent.click(within(region).getByText(/in transit for over 6 hours/))
    expect(await screen.findByText('Show movement record')).toBeTruthy()
  })

  it('does not fetch a movement record until asked, and says the view is logged', async () => {
    setup('admin', [delivery(1, 'in_transit')])
    fireEvent.click(await listItem('Rice 1'))
    expect(api.deliveryLocationHistory).toHaveBeenCalledTimes(0)
    fireEvent.click(screen.getByText('Show movement record'))
    expect(await screen.findByText(/2 recorded points, kept 30 days. Viewing this is logged/)).toBeTruthy()
    expect(api.deliveryLocationHistory).toHaveBeenCalledWith(1)
  })

  it('says plainly when no route record exists, and shows an access error as is', async () => {
    setup('admin', [delivery(1, 'in_transit')], { deliveryLocationHistory: vi.fn().mockResolvedValueOnce({ points: [], retention_days: 30 }).mockRejectedValueOnce(new Error('Administrators only')) })
    fireEvent.click(await listItem('Rice 1')); fireEvent.click(screen.getByText('Show movement record'))
    expect(await screen.findByText(/No route record exists/)).toBeTruthy()
    fireEvent.click(screen.getByText('Show movement record'))
    expect(await screen.findByText('Administrators only')).toBeTruthy()
  })

  it('only administrators are offered the movement record', async () => {
    for (const role of ['organization', 'donor', 'volunteer']) {
      setup(role, [delivery(1, 'in_transit')]); fireEvent.click(await listItem('Rice 1'))
      expect(screen.queryByText('Show movement record')).toBeNull(); cleanup()
    }
  })
})

describe('MapHub: live updates over the event stream', () => {
  async function liveSetup(role = 'organization') {
    const s = fakeStream()
    connectLive(() => 'tok', { fetchImpl: s.fetchImpl, sleep: async () => {} })
    await s.ready(); await waitFor(() => expect(liveStatus()).toBe('open'))
    setup(role, [delivery(1, 'in_transit')]); await listItem('Rice 1')
    return s
  }

  it('a volunteer pin appears when a position event arrives, and disappears when sharing pauses', async () => {
    const s = await liveSetup()
    expect(document.querySelector('[data-marker="d1:vol"]')).toBeNull()
    await s.send('1-0', 'delivery.location', { task_id: 1, latitude: 17.39, longitude: 78.47, accuracy_m: 8, status: 'in_transit' })
    await waitFor(() => expect(document.querySelector('[data-marker="d1:vol"]')).toBeTruthy())
    await s.send('2-0', 'delivery.tracking', { task_id: 1, state: 'paused' })
    await waitFor(() => expect(document.querySelector('[data-marker="d1:vol"]')).toBeNull())
  })

  it('ignores positions for deliveries it does not list', async () => {
    const s = await liveSetup()
    await s.send('3-0', 'delivery.location', { task_id: 999, latitude: 17.39, longitude: 78.47, status: 'in_transit' })
    await new Promise((r) => setTimeout(r, 30))
    expect(document.querySelector('[data-marker="d999:vol"]')).toBeNull(); expect(document.querySelector('[data-marker="d1:vol"]')).toBeNull()
  })

  it('a status change refreshes the list quietly', async () => {
    const s = await liveSetup()
    const before = api.listDeliveries.mock.calls.length
    api.listDeliveries = vi.fn().mockResolvedValue([delivery(1, 'delivered', { milestones: { delivered_at: hoursAgo(1) } })])
    await s.send('4-0', 'delivery.status', { task_id: 1, status: 'delivered', label: 'Delivered' })
    await waitFor(() => expect(api.listDeliveries).toHaveBeenCalled(), { timeout: 3000 })
    expect(before).toBeGreaterThan(0)
  })

  it('administrators see live risk alerts; other roles do not', async () => {
    const s = await liveSetup('admin')
    await s.send('5-0', 'risk.alert', { task_id: 1, kind: 'location_jump', severity: 'medium' })
    expect(await screen.findByRole('region', { name: 'Live alerts' })).toBeTruthy(); expect(screen.queryByText(/location jump \(medium\)/)).toBeTruthy()
    cleanup(); disconnectLive()
    const s2 = await liveSetup('donor')
    await s2.send('6-0', 'risk.alert', { task_id: 1, kind: 'location_jump', severity: 'medium' })
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByRole('region', { name: 'Live alerts' })).toBeNull()
  })
})
