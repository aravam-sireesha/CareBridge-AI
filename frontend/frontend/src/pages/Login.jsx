import React, { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { Button, Field } from '../components/ui.jsx'
import Logo from '../components/Logo.jsx'
import { IconEye, IconEyeOff, IconMail, IconLock, IconChildren, IconDonations, IconPeople, IconBuilding, IconAlert, IconHome } from '../components/icons.jsx'

const QUOTES = [
  'Every child deserves a childhood. Together, we can build a foundation of love, education, and opportunity for orphans worldwide.',
  "We cannot change a child's past, but together, we can completely rewrite their future.",
  'Your support is more than a donation—it is the promise of a safe home, a quality education, and a brighter tomorrow.'
]

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [q, setQ] = useState(0)
  const { login, isAuthenticated } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = location.state?.from && location.state.from !== '/login' ? location.state.from : '/dashboard'

  useEffect(() => { document.title = 'Sign in · CareBridge AI' }, [])
  useEffect(() => { if (isAuthenticated) navigate(redirectTo, { replace: true }) }, [isAuthenticated, navigate, redirectTo])
  useEffect(() => { const t = setInterval(() => setQ((i) => (i + 1) % QUOTES.length), 6500); return () => clearInterval(t) }, [])

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      const profile = await login(email, password)
      toast.success(`Welcome back, ${profile.name}!`)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err.message || 'Could not sign in. Check your details and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_.85fr]">
      {/* Hero with the child photo */}
      <div className="relative hidden overflow-hidden lg:block">
        <img src="/images/child-portrait.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-[50%_18%]" />
        <div className="absolute inset-0 bg-gradient-to-br from-teal-900/80 via-teal-800/45 to-sky-900/70" />
        <div className="absolute inset-0 bg-gradient-to-t from-teal-900/90 via-transparent to-transparent" />
        <div className="relative flex h-full flex-col justify-between p-10 text-white">
          <Link to="/"><Logo size={44} light showTagline /></Link>
          <div>
            <p className="font-script text-5xl leading-tight drop-shadow">Every child<br />deserves a chance</p>
            <p key={q} className="animate-rise-in mt-6 max-w-lg text-[15px] leading-relaxed text-white/90">“{QUOTES[q]}”</p>
            <div className="mt-4 flex gap-1.5">{QUOTES.map((_, i) => <span key={i} className={`h-1.5 rounded-full transition-all ${i === q ? 'w-8 bg-white' : 'w-2 bg-white/40'}`} />)}</div>
            <div className="mt-8 grid max-w-xl grid-cols-4 gap-3">
              {[[IconChildren, 'Children', 'Safe & supported'], [IconDonations, 'Donors', 'Make an impact'], [IconPeople, 'Volunteers', 'Share your time'], [IconBuilding, 'NGOs', 'Create change']].map(([I, t, s]) => (
                <div key={t} className="rounded-2xl bg-white/12 p-3 ring-1 ring-white/20 backdrop-blur">
                  <I className="h-5 w-5 text-amber-200" /><p className="mt-2 text-xs font-semibold">{t}</p><p className="text-[10px] text-white/70">{s}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="bg-mesh flex items-center justify-center p-5 sm:p-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center justify-between lg:hidden"><Link to="/"><Logo size={38} /></Link></div>
          <div className="card reveal p-7 shadow-lift sm:p-8">
            <h1 className="font-display text-2xl font-bold text-teal-900">Welcome back!</h1>
            <p className="mt-1 text-sm text-ink-muted">Together we can make a difference.</p>

            <div className="mt-5 grid grid-cols-2 rounded-xl bg-teal-50 p-1 text-sm font-semibold">
              <span className="rounded-lg bg-white py-2 text-center text-teal-700 shadow-card" aria-current="page">Login</span>
              <Link to="/register" className="rounded-lg py-2 text-center text-ink-muted transition hover:text-teal-700">Sign up</Link>
            </div>

            {error && (
              <div role="alert" className="mt-5 flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100">
                <IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}{/Administrator sign-in/i.test(error) && <> <Link to="/admin/login" className="font-semibold underline">Go to Administrator sign in</Link></>}</span>
              </div>
            )}

            <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
              <Field label="Email">
                <div className="relative"><IconMail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                  <input className="field pl-10" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@organization.org" /></div>
              </Field>
              <Field label="Password">
                <div className="relative"><IconLock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
                  <input className="field pl-10 pr-11" type={show ? 'text' : 'password'} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Your password" />
                  <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-ink-muted hover:bg-bg" aria-label={show ? 'Hide password' : 'Show password'}>{show ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}</button></div>
              </Field>
              <div className="flex justify-end"><Link to="/forgot-password" className="text-sm font-semibold text-sky-600 hover:underline">Forgot password?</Link></div>
              <Button type="submit" loading={loading} disabled={!email || !password} className="w-full py-3">{loading ? 'Signing in…' : 'Login'}</Button>
            </form>

            <p className="mt-5 text-center text-sm text-ink-muted">New here? <Link to="/register" className="font-semibold text-teal-700 hover:underline">Create an account</Link></p>
          </div>
          <p className="mt-5 text-center text-sm text-ink-muted">Administrator? <Link to="/admin/login" className="font-semibold text-teal-700 hover:underline">Sign in to Administration</Link></p>
          <Link to="/" className="mt-3 flex items-center justify-center gap-2 text-sm font-medium text-ink-muted hover:text-teal-700"><IconHome className="h-4 w-4" /> Back to home</Link>
        </div>
      </div>
    </div>
  )
}
