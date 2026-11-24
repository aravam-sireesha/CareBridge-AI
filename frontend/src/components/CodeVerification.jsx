import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Field } from './ui.jsx'
import { IconAlert } from './icons.jsx'
import { countdownText, digitsOnly } from '../lib/recovery.js'

/** One-time-code form shared by e-mail and mobile verification. The caller supplies the request/confirm calls and the wording.
 *  Wording stays conditional ("if this account is waiting...") because the server answers the same for every account. */
export default function CodeVerification({ identity, request, confirm: confirmCode, onVerified, sentLine, buttonLabel, helpText, unavailableNote }) {
  const [phase, setPhase] = useState('sending')      // sending | ready | unavailable
  const [code, setCode] = useState('')
  const [length, setLength] = useState(6)
  const [wait, setWait] = useState(0)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const started = useRef(false)

  const send = useCallback(async () => {
    setError('')
    try {
      const r = await request(identity)
      if (r.delivery === 'not_configured') { setPhase('unavailable'); setNotice(r.message); return }
      setNotice(r.message); setLength(r.code_length || 6); setWait(r.resend_in_seconds || 0); setCode(''); setPhase('ready')
    } catch (e) { setPhase('ready'); setError(e.message) }
  }, [identity, request])

  useEffect(() => { if (!started.current) { started.current = true; send() } }, [send])
  useEffect(() => {
    if (wait <= 0) return undefined
    const t = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  const confirm = async (e) => {
    e.preventDefault(); setError(''); setBusy(true)
    try { await confirmCode(identity, digitsOnly(code)); onVerified() }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  if (phase === 'unavailable') {
    return <div role="status" className="space-y-3 text-sm text-ink-muted"><p className="rounded-xl bg-amber-50 p-3 text-amber-800">{notice}</p><p>{unavailableNote}</p></div>
  }
  return (
    <form onSubmit={confirm} className="space-y-4" noValidate>
      <p className="text-sm text-ink-muted">{phase === 'sending' ? 'Sending a code…' : sentLine(length)}</p>
      {error && <div role="alert" className="flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100"><IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div>}
      <Field label="Verification code">
        <input className="field text-center font-mono text-xl tracking-[.35em]" inputMode="numeric" autoComplete="one-time-code" required value={code} disabled={phase === 'sending'}
          onChange={(e) => setCode(digitsOnly(e.target.value).slice(0, length))} placeholder={'•'.repeat(length)} />
      </Field>
      <Button type="submit" loading={busy} disabled={digitsOnly(code).length !== length} className="w-full py-3">{buttonLabel}</Button>
      <div className="flex items-center justify-between text-sm">
        <span className="text-ink-muted">{helpText}</span>
        {wait > 0 ? <span className="text-ink-muted" aria-live="polite">Send again in {countdownText(wait)}</span>
          : <button type="button" onClick={send} disabled={phase === 'sending'} className="font-semibold text-sky-700 hover:underline disabled:opacity-60">Send a new code</button>}
      </div>
    </form>
  )
}
