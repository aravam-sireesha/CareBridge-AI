import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api/client.js'
import { bannerDismissed, dismissBanner, getInstallController, isStandalone, platformHint, shouldShowInstall } from '../lib/pwa.js'
import { enablePush } from '../lib/push.js'

/** Three small, quiet jobs for the installed-app experience. Renders nothing unless it has something useful to say:
 *   1. offers "Install" (or the iPhone how-to) to signed-in people, never twice within 30 days of "Not now";
 *   2. says when a new version is ready, and applies it only when asked (no surprise reloads mid-task);
 *   3. quietly renews this device's push subscription when the push service rotates it (only if permission was already granted). */
export default function PwaBoot({ win = window, nav = navigator, storage = localStorage }) {
  const { user } = useAuth()
  const [install, setInstall] = useState({ canPrompt: false, installed: false })
  const [dismissed, setDismissed] = useState(() => bannerDismissed(storage))
  const [update, setUpdate] = useState(null)
  const signedIn = Boolean(user)

  useEffect(() => getInstallController(win).subscribe(setInstall), [win])
  useEffect(() => { const on = (e) => setUpdate(e.detail || {}); win.addEventListener('cb:sw-update', on); return () => win.removeEventListener('cb:sw-update', on) }, [win])
  useEffect(() => {
    if (!signedIn || !nav.serviceWorker?.addEventListener) return undefined
    const onMessage = (event) => {
      if (event.data?.type === 'cb:resubscribe' && win.Notification?.permission === 'granted') enablePush({ api, win, nav }).catch((e) => console.warn('Could not renew notifications', e.message))
    }
    nav.serviceWorker.addEventListener('message', onMessage)
    return () => nav.serviceWorker.removeEventListener('message', onMessage)
  }, [signedIn, win, nav])

  const applyUpdate = () => {
    const waiting = update?.waiting
    nav.serviceWorker?.addEventListener?.('controllerchange', () => win.location.reload(), { once: true })
    if (waiting) waiting.postMessage({ type: 'SKIP_WAITING' }); else win.location.reload()
  }
  const hint = platformHint(nav.userAgent)
  const show = signedIn && shouldShowInstall({ canPrompt: install.canPrompt, hint, standalone: isStandalone(win, nav) || install.installed, dismissed })
  const notNow = () => { dismissBanner(storage); setDismissed(true) }
  const doInstall = async () => { const r = await getInstallController(win).prompt(); if (r.outcome !== 'accepted') notNow() }

  if (!update && !show) return null
  const bar = 'fixed inset-x-3 bottom-3 z-40 rounded-2xl border border-line bg-white p-3 text-sm text-ink shadow-lift sm:left-auto sm:max-w-sm'
  const style = { marginBottom: 'env(safe-area-inset-bottom, 0px)' }
  if (update) {
    return (
      <div className={bar} style={style} role="status" aria-label="Update available">
        <p className="font-semibold">A new version of CareBridge is ready.</p>
        <p className="mt-0.5 text-xs text-ink-muted">Refreshing applies it. Finish what you are doing first if you have unsaved work.</p>
        <div className="mt-2 flex gap-2"><button type="button" className="btn-primary" onClick={applyUpdate}>Refresh now</button><button type="button" className="btn-ghost" onClick={() => setUpdate(null)}>Later</button></div>
      </div>
    )
  }
  return (
    <div className={bar} style={style} role="region" aria-label="Install CareBridge">
      <p className="font-semibold">Install CareBridge on this device</p>
      <p className="mt-0.5 text-xs text-ink-muted">
        {hint === 'ios' ? 'Tap the Share button, then \u201cAdd to Home Screen\u201d. On iPhone this is also needed for notifications.' : 'Opens faster, works like an app, and lets you turn on notifications.'}
      </p>
      <div className="mt-2 flex gap-2">
        {hint !== 'ios' && <button type="button" className="btn-primary" onClick={doInstall}>Install</button>}
        <button type="button" className="btn-ghost" onClick={notNow}>Not now</button>
      </div>
    </div>
  )
}
