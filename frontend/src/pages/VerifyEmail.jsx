import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import Logo from '../components/Logo.jsx'
import EmailVerification from '../components/EmailVerification.jsx'
import { Button, Field } from '../components/ui.jsx'
import { IconCheck, IconMail } from '../components/icons.jsx'
import { looksLikeEmail } from '../lib/recovery.js'

/** Verify the e-mail address of a new account. Reached from sign-in when it says the address must be verified first. */
export default function VerifyEmail() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [email, setEmail] = useState(params.get('email') || '')
  const [started, setStarted] = useState(looksLikeEmail(params.get('email')))
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { document.title = 'Verify your email · CareBridge AI' }, [])

  return (
    <div className="bg-mesh grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Link to="/"><Logo size={42} /></Link></div>
        <div className="card p-7 shadow-lift sm:p-8">
          <h1 className="font-display text-2xl font-bold text-teal-900">{done ? 'Email verified' : 'Verify your email'}</h1>
          <div className="mt-4">
            {done ? (
              <div className="space-y-5 text-center">
                <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-green-50 text-green-700"><IconCheck className="h-7 w-7" /></span>
                <p className="text-sm text-ink-muted">Thank you. You can sign in now.</p>
                <Button className="w-full py-3" onClick={() => navigate('/login')}>Go to sign in</Button>
              </div>
            ) : started ? (
              <EmailVerification email={email.trim()} onVerified={() => setDone(true)} />
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); if (!looksLikeEmail(email)) return setError('Enter the email address you signed up with.'); setError(''); setStarted(true) }} className="space-y-4" noValidate>
                <p className="text-sm text-ink-muted">Enter the email address you signed up with and we will send you a code.</p>
                {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
                <Field label="Email address"><div className="relative"><IconMail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div></Field>
                <Button type="submit" className="w-full py-3">Send code</Button>
              </form>
            )}
          </div>
        </div>
        {!done && <p className="mt-5 text-center text-sm text-ink-muted">Already verified? <Link to="/login" className="font-semibold text-teal-700 hover:underline">Sign in</Link></p>}
      </div>
    </div>
  )
}
