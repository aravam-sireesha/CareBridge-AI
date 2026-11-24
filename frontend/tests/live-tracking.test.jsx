import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'
import LiveTracking from '../src/components/LiveTracking.jsx'
import { api } from '../src/api/client.js'
import { connectLive, disconnectLive, liveStatus } from '../src/lib/liveEvents.js'

const task = (tracking, extra = {}) => ({
  id: 5, tracking: { can_share: false, sharing: false, can_watch: false, ...tracking },
  points: { pickup: { latitude: 17.4, longitude: 78.45, label: 'Banjara Hills' }, delivery: { latitude: 17.385, longitude: 78.4867, label: '12 Hope Road' } },
  addresses_visible: { pickup: true, delivery: true }, ...extra,
})
const volunteer = (extra) => task({ can_share: true, can_watch: true, ...extra })
const viewer = (extra) => task({ can_watch: true, ...extra })

let geo, watchers
function installGeolocation() {
  watchers = []
  geo = { watchPosition: vi.fn((ok, err) => { watchers.push({ ok, err }); return watchers.length }), clearWatch: vi.fn() }
  Object.defineProperty(navigator, 'geolocation', { value: geo, configurable: true })
}
const position = (extra = {}) => ({ coords: { latitude: 17.385129, longitude: 78.486718, accuracy: 9, heading: null, speed: null, ...extra }, timestamp: Date.now() })

beforeEach(() => {
  installGeolocation()
  api.deliveryTrackingStart = vi.fn().mockResolvedValue({ sharing: true, tracking_session_id: 'sess-1', retain_history: false })
  api.deliveryTrackingStop = vi.fn().mockResolvedValue({ sharing: false })
  api.deliveryTrackingPause = vi.fn().mockResolvedValue({ sharing: true, paused: true })
  api.deliveryTrackingResume = vi.fn().mockResolvedValue({ sharing: true, paused: false })
  api.sendDeliveryLocation = vi.fn().mockResolvedValue({ recorded_at: 'now' })
  api.getDeliveryLocation = vi.fn().mockResolvedValue({ sharing: true, has_position: false })
})
afterEach(() => { cleanup(); disconnectLive() })

describe('volunteer', () => {
  it('asks for consent in plain words and sends nothing until the button is pressed', () => {
    render(<LiveTracking task={volunteer()} />)
    expect(screen.queryByText(/Share my live location for this delivery/)).toBeTruthy()
    expect(screen.queryByText(/If this is unticked, no route record is kept/)).toBeTruthy()
    expect(api.deliveryTrackingStart).toHaveBeenCalledTimes(0)
    expect(geo.watchPosition).toHaveBeenCalledTimes(0)
  })

  it('starts with NO route record unless the optional box is ticked', async () => {
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(api.deliveryTrackingStart).toHaveBeenCalledTimes(1))
    expect(api.deliveryTrackingStart).toHaveBeenCalledWith(5, { retain_history: false })
    expect(geo.watchPosition).toHaveBeenCalledTimes(1)
  })

  it('sends retain_history only when the volunteer ticks the box, and says so while recording', async () => {
    api.deliveryTrackingStart = vi.fn().mockResolvedValue({ sharing: true, tracking_session_id: 'sess-2', retain_history: true })
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(api.deliveryTrackingStart).toHaveBeenCalledWith(5, { retain_history: true }))
    await waitFor(() => expect(screen.queryByText(/A route record is being kept/)).toBeTruthy())
  })

  it('sends validated fixes with the session id, a sequence number and the device time, and never NaN fields', async () => {
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    await act(async () => { await watchers[0].ok(position({ heading: NaN, speed: null })) })
    expect(api.sendDeliveryLocation).toHaveBeenCalledTimes(1)
    const [id, body] = api.sendDeliveryLocation.mock.calls[0]
    expect(id).toBe(5)
    expect(body.tracking_session_id).toBe('sess-1')
    expect(Number.isInteger(body.seq) && body.seq >= 0).toBe(true)
    expect(typeof body.timestamp).toBe('number')
    expect('heading' in body || 'speed' in body).toBe(false)
    expect(body.latitude).toBe(17.385129)
  })

  it('does not flood the server: a second fix right after the first is not sent', async () => {
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    await act(async () => { await watchers[0].ok(position()); await watchers[0].ok(position()) })
    expect(api.sendDeliveryLocation).toHaveBeenCalledTimes(1)
  })

  it('stops sharing and says why when location permission is denied', async () => {
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    await act(async () => { await watchers[0].err({ code: 1 }) })
    expect(api.deliveryTrackingStop).toHaveBeenCalledWith(5)
    expect(geo.clearWatch).toHaveBeenCalled()
    expect(screen.queryByText(/Location permission was blocked/)).toBeTruthy()
    expect(screen.queryByText('Start sharing my location')).toBeTruthy()
  })

  it('does not start when the browser cannot share location, and does not leave the server believing it is on', async () => {
    Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true })
    delete navigator.geolocation
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(api.deliveryTrackingStop).toHaveBeenCalledWith(5))
    expect(screen.queryByText(/cannot share its location/)).toBeTruthy()
  })

  it('pause stops the device sending and tells the server; resume starts it again', async () => {
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    fireEvent.click(await screen.findByText('Pause'))
    await waitFor(() => expect(api.deliveryTrackingPause).toHaveBeenCalledWith(5))
    expect(geo.clearWatch).toHaveBeenCalled()
    expect(await screen.findByText(/Sharing is paused. Nobody can see your position/)).toBeTruthy()
    fireEvent.click(screen.getByText('Resume sharing'))
    await waitFor(() => expect(api.deliveryTrackingResume).toHaveBeenCalledWith(5))
    await waitFor(() => expect(watchers.length).toBe(2))
  })

  it('goes back to "not sharing" when the server says the session ended', async () => {
    api.sendDeliveryLocation = vi.fn().mockRejectedValue(new Error('That sharing session has ended. Start sharing again.'))
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    await act(async () => { await watchers[0].ok(position()) })
    expect(screen.queryByText('Start sharing my location')).toBeTruthy()
    expect(screen.queryByText(/session has ended/)).toBeTruthy()
  })

  it('an old-reading or too-quick rejection is not shown as an error', async () => {
    api.sendDeliveryLocation = vi.fn().mockRejectedValue(new Error('That position is out of date (the device sent an old reading). Wait for a fresh GPS fix.'))
    render(<LiveTracking task={volunteer()} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(watchers.length).toBe(1))
    await act(async () => { await watchers[0].ok(position()) })
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

// ---- viewers receive updates over the REAL event-stream client, fed by a fake fetch
function fakeStream() {
  let controller
  const enc = new TextEncoder()
  const fetchImpl = vi.fn(async (url, init) => {
    const body = new ReadableStream({ start(c) { controller = c; init.signal.addEventListener('abort', () => { try { c.error(new Error('aborted')) } catch { /* closed */ } }) } })
    return new Response(body, { status: 200 })
  })
  const send = async (id, type, payload) => { controller.enqueue(enc.encode(`${id ? `id: ${id}\n` : ''}event: ${type}\ndata: ${JSON.stringify({ id, type, payload, ts: 1 })}\n\n`)); await new Promise((r) => setTimeout(r, 15)) }
  return { fetchImpl, send, ready: async () => { for (let i = 0; i < 100 && !controller; i++) await new Promise((r) => setTimeout(r, 5)) } }
}

describe('viewer (organization, donor, administrator)', () => {
  it('shows a live position the moment an event arrives, without polling', async () => {
    const s = fakeStream()
    connectLive(() => 'tok', { fetchImpl: s.fetchImpl, sleep: async () => {} })
    await s.ready()
    render(<LiveTracking task={viewer()} />)
    await waitFor(() => expect(screen.queryByText(/Waiting for the volunteer/)).toBeTruthy())
    await s.send('1-0', 'delivery.location', { task_id: 5, latitude: 17.3851, longitude: 78.4867, accuracy_m: 8, recorded_at: 'x', status: 'in_transit' })
    await waitFor(() => expect(screen.queryByText(/Live · updated/)).toBeTruthy())
  })

  it('ignores events about other deliveries', async () => {
    const s = fakeStream()
    connectLive(() => 'tok', { fetchImpl: s.fetchImpl, sleep: async () => {} })
    await s.ready()
    render(<LiveTracking task={viewer()} />)
    await waitFor(() => expect(screen.queryByText(/Waiting for the volunteer/)).toBeTruthy())
    await s.send('2-0', 'delivery.location', { task_id: 999, latitude: 1, longitude: 2, status: 'in_transit' })
    expect(screen.queryByText(/Live · updated/)).toBeNull()
  })

  it('removes the position when the volunteer pauses, and explains it', async () => {
    const s = fakeStream()
    connectLive(() => 'tok', { fetchImpl: s.fetchImpl, sleep: async () => {} })
    await s.ready()
    render(<LiveTracking task={viewer()} />)
    await s.send('3-0', 'delivery.location', { task_id: 5, latitude: 17.3851, longitude: 78.4867, status: 'in_transit' })
    await waitFor(() => expect(screen.queryByText(/Live · updated/)).toBeTruthy())
    await s.send('4-0', 'delivery.tracking', { task_id: 5, state: 'paused' })
    await waitFor(() => expect(screen.queryByText(/has paused sharing/)).toBeTruthy())
    await s.send('5-0', 'delivery.tracking', { task_id: 5, state: 'stopped' })
    await waitFor(() => expect(screen.queryByText(/not sharing a live location/)).toBeTruthy())
  })

  it('re-reads the server position after a resync request', async () => {
    const s = fakeStream()
    connectLive(() => 'tok', { fetchImpl: s.fetchImpl, sleep: async () => {} })
    await s.ready()
    await waitFor(() => expect(liveStatus()).toBe('open'))           // deterministic: the stream is fully open before the page renders
    render(<LiveTracking task={viewer()} />)
    await waitFor(() => expect(api.getDeliveryLocation).toHaveBeenCalledTimes(1))
    await s.send(null, 'system.resync', { reason: 'gap' })
    await waitFor(() => expect(api.getDeliveryLocation).toHaveBeenCalledTimes(2))
  })

  it('a volunteer never gets the viewer polling or the viewer map marker', async () => {
    render(<LiveTracking task={volunteer()} />)
    await new Promise((r) => setTimeout(r, 30))
    expect(api.getDeliveryLocation).toHaveBeenCalledTimes(0)
  })
})
