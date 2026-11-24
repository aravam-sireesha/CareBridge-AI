import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PwaBoot from '../src/components/PwaBoot.jsx'
import PushDevice from '../src/components/PushDevice.jsx'
import LiveTracking from '../src/components/LiveTracking.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'
import { api, tokenStore } from '../src/api/client.js'

const DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1'
const emitter = () => { const l = {}; return { addEventListener: (t, fn, o) => { (l[t] ||= []).push({ fn, once: o?.once }) }, removeEventListener: (t, fn) => { l[t] = (l[t] || []).filter((x) => x.fn !== fn) }, emit: (t, e = {}) => { for (const x of [...(l[t] || [])]) { x.fn({ type: t, ...e }); if (x.once) l[t] = l[t].filter((y) => y !== x) } } } }

function signIn(role = 'volunteer') {
  localStorage.clear(); tokenStore.set('tok'); localStorage.setItem('cb_user', JSON.stringify({ id: 9, email: 'u@x.org', role, name: 'U' }))
  api.me = vi.fn().mockResolvedValue({ id: 9, email: 'u@x.org', role }); api.ping = vi.fn().mockResolvedValue({})
}
function boot({ ua = DESKTOP, standalone = false, permission = 'default', signedIn = true, storage } = {}) {
  if (signedIn) signIn(); else { localStorage.clear(); tokenStore.clear() }
  const win = Object.assign(emitter(), { matchMedia: () => ({ matches: standalone }), location: { reload: vi.fn(), protocol: 'https:', hostname: 'x' }, Notification: { permission, requestPermission: vi.fn(async () => 'granted') }, PushManager: {} })
  const sw = Object.assign(emitter(), { ready: Promise.resolve({ pushManager: { getSubscription: async () => null, subscribe: async () => ({ toJSON: () => ({ endpoint: 'https://fcm.googleapis.com/x', keys: { p256dh: 'P', auth: 'A' } }) }) } }) })
  const nav = { userAgent: ua, serviceWorker: sw }
  const store = storage || new Map(); const st = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
  const view = render(<MemoryRouter><AuthProvider><PwaBoot win={win} nav={nav} storage={st} /></AuthProvider></MemoryRouter>)
  return { win, nav, sw, store, view, st }
}
const promptEvent = (outcome = 'accepted') => ({ preventDefault: vi.fn(), prompt: vi.fn(async () => {}), userChoice: Promise.resolve({ outcome }) })

afterEach(() => { cleanup(); localStorage.clear() })

describe('PwaBoot: install banner', () => {
  it('shows nothing to a signed-out visitor, even when the browser could install', async () => {
    const b = boot({ signedIn: false }); await act(async () => { b.win.emit('beforeinstallprompt', promptEvent()) })
    expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull()
  })
  it('offers Install once the browser allows it, and installing hides the banner', async () => {
    const b = boot(); const e = promptEvent()
    expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull()
    await act(async () => { b.win.emit('beforeinstallprompt', e) })
    fireEvent.click(await screen.findByText('Install'))
    await waitFor(() => expect(e.prompt).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull())
    expect(b.store.size).toBe(0)                                                     // accepted: nothing to remember
  })
  it('remembers "Not now" and a declined system prompt, so it does not nag', async () => {
    const b = boot(); await act(async () => { b.win.emit('beforeinstallprompt', promptEvent('dismissed')) })
    fireEvent.click(await screen.findByText('Install'))
    await waitFor(() => expect(b.store.has('cb_install_dismissed_at')).toBe(true))
    cleanup()
    boot({ storage: b.store }).win.emit('beforeinstallprompt', promptEvent())      // a later visit within 30 days
    await new Promise((r) => setTimeout(r, 20)); expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull()
  })
  it('"Not now" hides it immediately', async () => {
    const b = boot(); await act(async () => { b.win.emit('beforeinstallprompt', promptEvent()) })
    fireEvent.click(await screen.findByText('Not now'))
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull()); expect(b.store.has('cb_install_dismissed_at')).toBe(true)
  })
  it('is silent in the installed app', async () => {
    const b = boot({ standalone: true }); await act(async () => { b.win.emit('beforeinstallprompt', promptEvent()) })
    expect(screen.queryByRole('region', { name: 'Install CareBridge' })).toBeNull()
  })
  it('on iPhone it gives the Share > Add to Home Screen steps and no Install button (iOS has no install prompt)', async () => {
    boot({ ua: IPHONE })
    expect(await screen.findByText(/Add to Home Screen/)).toBeTruthy(); expect(screen.queryByText('Install')).toBeNull(); expect(screen.queryByText('Not now')).toBeTruthy()
  })
})

describe('PwaBoot: updates', () => {
  it('announces a new version and applies it only when asked', async () => {
    const b = boot(); const waiting = { postMessage: vi.fn() }
    await act(async () => { b.win.emit('cb:sw-update', { detail: { waiting } }) })
    expect(await screen.findByText(/new version of CareBridge is ready/)).toBeTruthy(); expect(waiting.postMessage).toHaveBeenCalledTimes(0)
    fireEvent.click(screen.getByText('Refresh now'))
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
    expect(b.win.location.reload).toHaveBeenCalledTimes(0)
    await act(async () => { b.sw.emit('controllerchange') })
    expect(b.win.location.reload).toHaveBeenCalledTimes(1)
  })
  it('"Later" dismisses the notice without reloading', async () => {
    const b = boot(); await act(async () => { b.win.emit('cb:sw-update', { detail: { waiting: { postMessage() {} } } }) })
    fireEvent.click(await screen.findByText('Later'))
    expect(screen.queryByText(/new version/)).toBeNull(); expect(b.win.location.reload).toHaveBeenCalledTimes(0)
  })
})

describe('PwaBoot: renewing a rotated push subscription', () => {
  it('re-subscribes silently, but only when notification permission was already granted', async () => {
    api.pushConfig = vi.fn().mockResolvedValue({ enabled: true, public_key: 'BAEC' }); api.pushSubscribe = vi.fn().mockResolvedValue({})
    const granted = boot({ permission: 'granted' }); await new Promise((r) => setTimeout(r, 20))
    await act(async () => { granted.sw.emit('message', { data: { type: 'cb:resubscribe' } }) })
    await waitFor(() => expect(api.pushSubscribe).toHaveBeenCalledTimes(1)); cleanup()
    api.pushSubscribe.mockClear()
    const asking = boot({ permission: 'default' }); await new Promise((r) => setTimeout(r, 20))
    await act(async () => { asking.sw.emit('message', { data: { type: 'cb:resubscribe' } }) }); await new Promise((r) => setTimeout(r, 30))
    expect(api.pushSubscribe).toHaveBeenCalledTimes(0)
    expect(asking.win.Notification.requestPermission).toHaveBeenCalledTimes(0)       // never opens a permission prompt on its own
  })
  it('ignores other worker messages and does nothing for a signed-out visitor', async () => {
    api.pushConfig = vi.fn().mockResolvedValue({ enabled: true, public_key: 'BAEC' }); api.pushSubscribe = vi.fn().mockResolvedValue({})
    const a = boot({ permission: 'granted' }); await new Promise((r) => setTimeout(r, 20))
    await act(async () => { a.sw.emit('message', { data: { type: 'something-else' } }) }); cleanup()
    const b = boot({ permission: 'granted', signedIn: false }); await act(async () => { b.sw.emit('message', { data: { type: 'cb:resubscribe' } }) })
    await new Promise((r) => setTimeout(r, 30)); expect(api.pushSubscribe).toHaveBeenCalledTimes(0)
  })
})

// ---------------------------------------------------------------- PushDevice
function deviceEnv({ permission = 'default', hasPush = true, ua = DESKTOP, subscribed = false, requestResult = 'granted' } = {}) {
  const state = { sub: subscribed ? { endpoint: 'https://fcm.googleapis.com/x', unsubscribe: vi.fn(async () => { state.sub = null }) } : null }
  const pm = { getSubscription: async () => state.sub, subscribe: async () => { state.sub = { endpoint: 'https://fcm.googleapis.com/x', toJSON: () => ({ endpoint: 'https://fcm.googleapis.com/x', keys: { p256dh: 'P', auth: 'A' } }), unsubscribe: vi.fn(async () => { state.sub = null }) }; return state.sub } }
  const win = { Notification: { permission, requestPermission: vi.fn(async () => requestResult) }, PushManager: hasPush ? {} : undefined, matchMedia: () => ({ matches: false }) }
  const nav = { userAgent: ua, serviceWorker: { ready: Promise.resolve({ pushManager: pm }), getRegistration: async () => ({ pushManager: pm }) } }
  return { win, nav, state }
}
function renderDevice(env, apiSetup = {}) {
  Object.assign(api, { pushConfig: vi.fn().mockResolvedValue({ enabled: true, public_key: 'BAEC' }), pushSubscribe: vi.fn().mockResolvedValue({ subscribed: true }), pushUnsubscribe: vi.fn().mockResolvedValue({ removed: 1 }),
    pushDevices: vi.fn().mockResolvedValue({ devices: [] }), pushEvents: vi.fn().mockResolvedValue({ events: [] }), pushTest: vi.fn().mockResolvedValue({ queued: true }), ...apiSetup })
  return render(<ToastProvider><PushDevice env={env} /></ToastProvider>)
}

describe('PushDevice', () => {
  it('explains an unsupported browser and offers no controls', async () => {
    renderDevice(deviceEnv({ hasPush: false }))
    expect(await screen.findByText(/does not support push notifications/)).toBeTruthy(); expect(screen.queryByText('Turn on for this device')).toBeNull()
  })
  it('explains the iPhone install requirement', async () => {
    renderDevice(deviceEnv({ ua: IPHONE })); expect(await screen.findByText(/Add to Home Screen/)).toBeTruthy()
  })
  it('says so when the server cannot send push, instead of offering a button that cannot work', async () => {
    renderDevice(deviceEnv(), { pushConfig: vi.fn().mockResolvedValue({ enabled: false, public_key: null }) })
    expect(await screen.findByText(/not set up on this server yet/)).toBeTruthy(); expect(screen.queryByText('Turn on for this device')).toBeNull()
  })
  it('turns notifications on for this device and registers it', async () => {
    const env = deviceEnv(); renderDevice(env)
    fireEvent.click(await screen.findByText('Turn on for this device'))
    await waitFor(() => expect(api.pushSubscribe).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Turn off for this device')).toBeTruthy(); expect(screen.queryByText('Send a test')).toBeTruthy()
  })
  it('a blocked permission disables the button and explains how to unblock', async () => {
    renderDevice(deviceEnv({ permission: 'denied' }))
    expect(await screen.findByText(/blocked for this site/)).toBeTruthy(); expect(screen.getByText('Turn on for this device').disabled).toBe(true)
  })
  it('declining the browser prompt registers nothing and shows why', async () => {
    renderDevice(deviceEnv({ requestResult: 'denied' }))
    fireEvent.click(await screen.findByText('Turn on for this device'))
    expect(await screen.findByRole('alert')).toBeTruthy(); expect(api.pushSubscribe).toHaveBeenCalledTimes(0)
  })
  it('turns notifications off for this device', async () => {
    renderDevice(deviceEnv({ subscribed: true }))
    fireEvent.click(await screen.findByText('Turn off for this device'))
    await waitFor(() => expect(api.pushUnsubscribe).toHaveBeenCalledWith('https://fcm.googleapis.com/x'))
    expect(await screen.findByText('Turn on for this device')).toBeTruthy()
  })
  it('sends a test and says where to look', async () => {
    renderDevice(deviceEnv({ subscribed: true }))
    fireEvent.click(await screen.findByText('Send a test'))
    await waitFor(() => expect(api.pushTest).toHaveBeenCalledTimes(1))
  })
  it('shows a server error from the test button', async () => {
    renderDevice(deviceEnv({ subscribed: true }), { pushTest: vi.fn().mockRejectedValue(new Error('No notifications are switched on for this device.')) })
    fireEvent.click(await screen.findByText('Send a test'))
    expect(await screen.findByText(/No notifications are switched on/)).toBeTruthy()
  })
  it('lists recent attempts with the provider\u2019s answer and never says "delivered"', async () => {
    renderDevice(deviceEnv({ subscribed: true }), { pushEvents: vi.fn().mockResolvedValue({ events: [
      { id: 1, kind: 'donation', title: 'Delivery #5: In transit', status: 'accepted_by_provider', accepted_devices: 1, error: null },
      { id: 2, kind: 'need', title: 'Need approved', status: 'failed', accepted_devices: 0, error: '403' }] }) })
    expect(await screen.findByText('Sent to your device\u2019s push service')).toBeTruthy(); expect(screen.queryByText('Could not be sent')).toBeTruthy()
    expect(/delivered/i.test(document.body.textContent.replace(/Delivery #5/, ''))).toBe(false)
    expect(screen.queryByText(/We cannot see whether it appeared on your screen/)).toBeTruthy()
  })
})

// ---------------------------------------------------------------- wake lock inside live tracking
describe('LiveTracking keeps the screen on while sharing', () => {
  const volunteerTask = { id: 5, tracking: { can_share: true, sharing: false, can_watch: true }, points: { pickup: { latitude: 17.4, longitude: 78.45, label: 'A' }, delivery: { latitude: 17.385, longitude: 78.4867, label: 'B' } }, addresses_visible: { pickup: true, delivery: true } }
  function setup() {
    const sentinel = { release: vi.fn(async () => {}), addEventListener() {} }
    Object.defineProperty(navigator, 'wakeLock', { value: { request: vi.fn(async () => sentinel) }, configurable: true })
    Object.defineProperty(navigator, 'geolocation', { value: { watchPosition: vi.fn(() => 1), clearWatch: vi.fn() }, configurable: true })
    Object.assign(api, { deliveryTrackingStart: vi.fn().mockResolvedValue({ sharing: true, tracking_session_id: 's', retain_history: false }), deliveryTrackingStop: vi.fn().mockResolvedValue({}), deliveryTrackingPause: vi.fn().mockResolvedValue({}) })
    return { sentinel }
  }
  it('requests a screen wake lock on start and releases it on pause', async () => {
    const { sentinel } = setup(); render(<LiveTracking task={volunteerTask} />)
    fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(navigator.wakeLock.request).toHaveBeenCalledWith('screen'))
    expect(await screen.findByText(/screen is being kept on while you share/)).toBeTruthy()
    fireEvent.click(await screen.findByText('Pause'))
    await waitFor(() => expect(sentinel.release).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByText(/screen is being kept on/)).toBeNull())
  })
  it('releases it when the volunteer stops sharing or leaves the page', async () => {
    const { sentinel } = setup(); const view = render(<LiveTracking task={volunteerTask} />)
    fireEvent.click(screen.getByText('Start sharing my location')); await waitFor(() => expect(navigator.wakeLock.request).toHaveBeenCalled())
    view.unmount(); await waitFor(() => expect(sentinel.release).toHaveBeenCalled())
  })
  it('works (without the screen hold) where the browser has no Wake Lock', async () => {
    setup(); Object.defineProperty(navigator, 'wakeLock', { value: undefined, configurable: true })
    render(<LiveTracking task={volunteerTask} />); fireEvent.click(screen.getByText('Start sharing my location'))
    await waitFor(() => expect(api.deliveryTrackingStart).toHaveBeenCalled())
    expect(await screen.findByText(/Keep this page open and your screen on/)).toBeTruthy(); expect(screen.queryByText(/screen is being kept on/)).toBeNull()
  })
})
