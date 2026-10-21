import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { Button, Field, PasswordStrength } from '../components/ui.jsx'
import Logo from '../components/Logo.jsx'
import { IconAlert, IconMail, IconKey, IconCheck } from '../components/icons.jsx'

export default function ForgotPassword() {
  const [step, setStep] = useState('request')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [info, setInfo] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const toast = useToast()
  const navigate = useNavigate()

  useEffect(() => { document.title = 'Reset password · CareBridge AI' }, [])

  const request = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const res = await api.requestPasswordReset(email.trim())
      setInfo(res.message); setStep('reset')
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }
  const complete = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      await api.completePasswordReset(code.trim(), password)
      toast.success('Password updated. You can now sign in.')
      navigate('/login')
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  return (
    <div className="bg-mesh grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Link to="/"><Logo size={42} /></Link></div>
        <div className="card reveal p-7 shadow-lift sm:p-8">
          <div className="mb-5 flex items-center gap-2 text-xs font-semibold text-ink-muted">
            <span className={`grid h-6 w-6 place-items-center rounded-full ${step === 'request' ? 'bg-teal-600 text-white' : 'bg-green-700 text-white'}`}>{step === 'request' ? '1' : <IconCheck className="h-3.5 w-3.5" />}</span>Request code
            <span className="h-px flex-1 bg-line" />
            <span className={`grid h-6 w-6 place-items-center rounded-full ${step === 'reset' ? 'bg-teal-600 text-white' : 'bg-line text-ink-muted'}`}>2</span>New password
          </div>

          {error && <div role="alert" className="mb-4 flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100"><IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div>}

          {step === 'request' ? (
            <form onSubmit={request} className="space-y-4">
              <div><h1 className="font-display text-2xl font-bold text-teal-900">Forgot password?</h1><p className="mt-1 text-sm text-ink-muted">Enter your account email. We will send a one-time reset code if e-mail delivery is configured.</p></div>
              <Field label="Email"><div className="relative"><IconMail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@organization.org" /></div></Field>
              <Button type="submit" loading={loading} className="w-full py-3">Send reset code</Button>
              <button type="button" onClick={() => setStep('reset')} className="w-full text-center text-sm font-semibold text-sky-600 hover:underline">I already have a code</button>
            </form>
          ) : (
            <form onSubmit={complete} className="space-y-4">
              <div><h1 className="font-display text-2xl font-bold text-teal-900">Set a new password</h1>
                {info && <p className="mt-2 rounded-xl bg-sky-50 p-3 text-sm text-sky-800">{info}</p>}
                <p className="mt-2 text-xs text-ink-muted">If e-mail is not configured on this server, ask a CareBridge administrator to issue a one-time code from <strong>Settings → Users</strong>. Codes expire after 30 minutes.</p></div>
              <Field label="Reset code"><div className="relative"><IconKey className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10 font-mono text-[13px]" required minLength={32} value={code} onChange={(e) => setCode(e.target.value)} placeholder="Paste the code" /></div></Field>
              <Field label="New password"><input className="field" type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 12 characters" /><PasswordStrength password={password} /></Field>
              <Button type="submit" loading={loading} disabled={password.length < 12 || code.trim().length < 32} className="w-full py-3">Update password</Button>
              <button type="button" onClick={() => { setStep('request'); setError('') }} className="w-full text-center text-sm font-semibold text-sky-600 hover:underline">Back</button>
            </form>
          )}
        </div>
        <p className="mt-5 text-center text-sm text-ink-muted">Remembered it? <Link to="/login" className="font-semibold text-teal-700 hover:underline">Back to sign in</Link></p>
      </div>
    </div>
  )
}
