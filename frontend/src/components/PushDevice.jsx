import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { Section } from './ui.jsx'
import { EVENT_STATUS_TEXT, PushError, disablePush, enablePush, pushSupport, thisDeviceSubscribed } from '../lib/push.js'

/** Notifications on THIS device. Honest about every state: unsupported, blocked, off, on, and what the push service actually answered. */
export default function PushDevice({ env = {} }) {
  const toast = useToast()
  const [support] = useState(() => pushSupport(env))
  const [here, setHere] = useState(false)
  const [server, setServer] = useState(null)             // { enabled }
  const [devices, setDevices] = useState([])
  const [events, setEvents] = useState([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    const [h, cfg, dev, ev] = await Promise.allSettled([thisDeviceSubscribed(env), api.pushConfig(), api.pushDevices(), api.pushEvents()])
    if (h.status === 'fulfilled') setHere(h.value)
    if (cfg.status === 'fulfilled') setServer(cfg.value)
    if (dev.status === 'fulfilled') setDevices(dev.value?.devices || [])
    if (ev.status === 'fulfilled') setEvents(ev.value?.events || [])
  }, [env])
  useEffect(() => { load() }, [load])

  const run = async (fn, okText) => {
    setBusy(true); setMessage('')
    try { const r = await fn(); if (r?.error) throw new Error(r.error); if (okText) toast.success(okText); await load() }
    catch (e) { setMessage(e instanceof PushError || e?.message ? e.message : 'Something went wrong.') } finally { setBusy(false) }
  }
  const on = () => run(() => enablePush({ api, ...env }), 'Notifications are on for this device.')
  const off = () => run(() => disablePush({ api, ...env }), 'Notifications are off for this device.')
  const test = () => run(async () => { await api.pushTest(); setTimeout(load, 3000) }, 'Test sent. Check the list below in a few seconds.')

  const serverOff = server && !server.enabled
  return (
    <Section title="Push notifications on this device">
      <div className="card space-y-3 p-4 text-sm text-ink">
        {!support.supported ? <p role="status">{support.reason}</p> : serverOff ? <p role="status">Push notifications are not set up on this server yet, so they cannot be turned on. In-app notifications still work.</p> : (
          <>
            <p role="status">{here ? 'Notifications are on for this device.' : support.permission === 'denied' ? support.reason : 'Get a notification on this device when something needs your attention, even when CareBridge is closed.'}</p>
            <div className="flex flex-wrap gap-2">
              {!here && <button type="button" className="btn-primary" onClick={on} disabled={busy || support.permission === 'denied'}>Turn on for this device</button>}
              {here && <button type="button" className="btn-ghost" onClick={off} disabled={busy}>Turn off for this device</button>}
              {here && <button type="button" className="btn-ghost" onClick={test} disabled={busy}>Send a test</button>}
            </div>
          </>
        )}
        {message && <p className="text-red-700" role="alert">{message}</p>}
        {devices.length > 0 && <p className="text-xs text-ink-muted">{devices.length} device{devices.length === 1 ? '' : 's'} will receive your notifications. Turning notifications off here only affects this device.</p>}
        {events.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Recent push attempts</h3>
            <ul className="mt-1 divide-y divide-line text-xs">
              {events.map((e) => <li key={e.id} className="flex justify-between gap-3 py-1.5"><span className="truncate">{e.title || e.kind}</span><span className="shrink-0 text-ink-muted">{EVENT_STATUS_TEXT[e.status] || e.status}</span></li>)}
            </ul>
            <p className="mt-2 text-xs text-ink-muted">\u201cSent to your device\u2019s push service\u201d means that service accepted the message. We cannot see whether it appeared on your screen.</p>
          </div>
        )}
      </div>
    </Section>
  )
}
