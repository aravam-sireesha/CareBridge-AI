import React, { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import { Button, Field, PasswordStrength } from '../components/ui.jsx'
import Logo from '../components/Logo.jsx'
import { IconAlert, IconCheck, IconMail } from '../components/icons.jsx'
import { STEPS, countdownText, digitsOnly, looksLikeEmail, passwordProblem } from '../lib/recovery.js'

/** Password recovery: email -> code -> new password -> done. One centered card, nothing else on the page.
 *  The server answers the same way whether or not the email has an account, so this screen never says "no such account". */
export default function ForgotPassword() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)             // 0 email, 1 code, 2 new password, 3 done
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [codeLength, setCodeLength] = useState(6)
  const [grant, setGrant] = useState('')           // short-lived reset grant returned after the code is accepted
  const [manual, setManual] = useState(false)     // administrator-issued code instead of an e-mailed one
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const [wait, setWait] = useState(0)             // seconds until a new code may be requested
  const headingRef = useRef(null)

  useEffect(() => { document.title = 'Reset password · CareBridge AI' }, [])
  useEffect(() => { headingRef.current?.focus() }, [step])          // keyboard and screen-reader users land on the new step
  useEffect(() => {
    if (wait <= 0) return undefined
    const t = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  const guard = async (work) => { setError(''); setLoading(true); try { await work() } catch (err) { setError(err.message) } finally { setLoading(false) } }

  const sendCode = (e) => {
    e?.preventDefault()
    if (!looksLikeEmail(email)) { setError('Enter the email address you registered with.'); return }
    return guard(async () => {
      const res = await api.requestOtp(email.trim())
      if (res.delivery === 'not_configured') { setNotice(res.message); setManual(true); setStep(1); return }
      setNotice(res.message); setManual(false); setCode('')
      setCodeLength(res.code_length || 6); setWait(res.resend_in_seconds || 0); setStep(1)
    })
  }
  const checkCode = (e) => {
    e.preventDefault()
    return guard(async () => {
      if (manual) { setGrant(code.trim()); setStep(2); return }          // an administrator-issued code is used directly as the grant
      const res = await api.verifyOtp(email.trim(), digitsOnly(code))
      setGrant(res.reset_token); setStep(2)
    })
  }
  const savePassword = (e) => {
    e.preventDefault()
    const problem = passwordProblem(password, confirm)
    if (problem) { setError(problem); return }
    return guard(async () => { await api.completePasswordReset(grant, password); setStep(3) })
  }

  const codeReady = manual ? code.trim().length >= 32 : digitsOnly(code).length === codeLength
  const title = ['Reset your password', manual ? 'Enter the code from your administrator' : 'Enter the verification code', 'Choose a new password', 'Password updated'][step]

  return (
    <div className="bg-mesh grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Link to="/"><Logo size={42} /></Link></div>
        <div className="card p-7 shadow-lift sm:p-8">
          {step < 3 && (
            <ol className="mb-6 flex items-center" aria-label="Progress">
              {STEPS.map((label, i) => (
                <li key={label} className="flex flex-1 items-center last:flex-none" aria-current={i === step ? 'step' : undefined}>
                  <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${i < step ? 'bg-green-700 text-white' : i === step ? 'bg-teal-700 text-white' : 'bg-line text-ink-muted'}`}>
                    {i < step ? <IconCheck className="h-3.5 w-3.5" /> : i + 1}<span className="sr-only">{i < step ? ' done, ' : i === step ? ' current, ' : ' '}{label}</span>
                  </span>
                  <span className={`ml-2 text-xs font-semibold ${i === step ? 'text-ink' : 'text-ink-muted'}`}>{label}</span>
                  {i < STEPS.length - 1 && <span className={`mx-3 h-px flex-1 ${i < step ? 'bg-green-700' : 'bg-line'}`} />}
                </li>
              ))}
            </ol>
          )}

          <h1 ref={headingRef} tabIndex={-1} className="font-display text-2xl font-bold text-teal-900 outline-none">{title}</h1>

          {error && <div role="alert" className="mt-4 flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100"><IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div>}

          {step === 0 && (
            <form onSubmit={sendCode} className="mt-4 space-y-4" noValidate>
              <p className="text-sm text-ink-muted">Enter your account email and we will send you a verification code.</p>
              <Field label="Email address">
                <div className="relative"><IconMail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                  <input className="field pl-10" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@organization.org" /></div>
              </Field>
              <Button type="submit" loading={loading} className="w-full py-3">Send code</Button>
            </form>
          )}

          {step === 1 && (
            <form onSubmit={checkCode} className="mt-4 space-y-4" noValidate>
              <p role="status" className="rounded-xl bg-sky-50 p-3 text-sm text-sky-800">{notice}</p>
              {manual ? (
                <>
                  <p className="text-sm text-ink-muted">Ask a CareBridge administrator to issue a one-time code for your account (Settings, then Users), and paste it here. It expires after 30 minutes.</p>
                  <Field label="Code from your administrator"><input className="field font-mono text-[13px]" required value={code} onChange={(e) => setCode(e.target.value)} placeholder="Paste the code" autoComplete="off" /></Field>
                </>
              ) : (
                <>
                  <p className="text-sm text-ink-muted">We sent a {codeLength}-digit code to <strong className="text-ink">{email.trim()}</strong>, if an account exists for it. The code works once.</p>
                  <Field label="Verification code">
                    <input className="field text-center font-mono text-xl tracking-[.35em]" inputMode="numeric" autoComplete="one-time-code" required
                      value={code} onChange={(e) => setCode(digitsOnly(e.target.value).slice(0, codeLength))} placeholder={'•'.repeat(codeLength)} aria-describedby="otp-help" />
                  </Field>
                  <p id="otp-help" className="text-xs text-ink-muted">Not there? Check your spam folder.</p>
                </>
              )}
              <Button type="submit" loading={loading} disabled={!codeReady} className="w-full py-3">Verify code</Button>
              <div className="flex items-center justify-between text-sm">
                <button type="button" onClick={() => { setStep(0); setError(''); setNotice('') }} className="font-semibold text-sky-700 hover:underline">Use a different email</button>
                {!manual && (wait > 0
                  ? <span className="text-ink-muted" aria-live="polite">Send again in {countdownText(wait)}</span>
                  : <button type="button" onClick={sendCode} disabled={loading} className="font-semibold text-sky-700 hover:underline disabled:opacity-60">Send a new code</button>)}
              </div>
            </form>
          )}

          {step === 2 && (
            <form onSubmit={savePassword} className="mt-4 space-y-4" noValidate>
              <Field label="New password" hint="At least 12 characters.">
                <div className="relative">
                  <input className="field pr-16" type={show ? 'text' : 'password'} autoComplete="new-password" required maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} />
                  <button type="button" onClick={() => setShow((s) => !s)} aria-pressed={show} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 text-xs font-semibold text-teal-700 hover:bg-teal-50">{show ? 'Hide' : 'Show'}</button>
                </div>
                <PasswordStrength password={password} />
              </Field>
              <Field label="Confirm new password"><input className="field" type={show ? 'text' : 'password'} autoComplete="new-password" required maxLength={128} value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
              <Button type="submit" loading={loading} className="w-full py-3">Update password</Button>
            </form>
          )}

          {step === 3 && (
            <div className="mt-4 space-y-5 text-center">
              <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-green-50 text-green-700"><IconCheck className="h-7 w-7" /></span>
              <p className="text-sm text-ink-muted">Your password has been changed and other devices have been signed out. Sign in with your new password.</p>
              <Button className="w-full py-3" onClick={() => navigate('/login')}>Back to sign in</Button>
            </div>
          )}
        </div>
        {step < 3 && <p className="mt-5 text-center text-sm text-ink-muted">Remembered it? <Link to="/login" className="font-semibold text-teal-700 hover:underline">Back to sign in</Link></p>}
      </div>
    </div>
  )
}
