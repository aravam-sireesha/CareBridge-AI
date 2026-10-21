import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { Button, Field, PasswordStrength } from '../components/ui.jsx'
import Logo from '../components/Logo.jsx'
import ChildPhotoPanel from '../components/ChildPhotoPanel.jsx'
import { ThemeToggle } from '../components/ProfileMenu.jsx'
import { IconAlert, IconEye, IconEyeOff, IconKey, IconLock, IconMail, IconShield } from '../components/icons.jsx'

function Shell({ title, subtitle, children, footer }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_.85fr]">
      <ChildPhotoPanel text="Every organization, donor and volunteer on CareBridge AI is coordinated by people who care. Sign in to keep that work safe and transparent." />
      <div className="bg-mesh flex items-center justify-center px-4 py-8 sm:p-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center justify-between"><Link to="/" aria-label="CareBridge AI home" className="lg:invisible"><Logo size={38} /></Link><ThemeToggle /></div>
          <div className="card reveal p-7 shadow-lift sm:p-8">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-teal-700 text-white shadow-card"><IconShield className="h-6 w-6" /></span>
            <h1 className="mt-4 font-display text-2xl font-bold text-teal-900">{title}</h1>
            <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>
            {children}
          </div>
          <div className="mt-5 space-y-2 text-center text-sm text-ink-muted">{footer}</div>
        </div>
      </div>
    </div>
  )
}

const ErrorBox = ({ error }) => error ? <div role="alert" className="mt-5 flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100"><IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div> : null

function PasswordInput({ value, onChange, show, setShow, placeholder, autoComplete, min }) {
  return (
    <div className="relative">
      <IconLock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
      <input className="field pl-10 pr-11" type={show ? 'text' : 'password'} required minLength={min} maxLength={128} autoComplete={autoComplete} value={value} onChange={onChange} placeholder={placeholder} />
      <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-ink-muted hover:bg-bg" aria-label={show ? 'Hide password' : 'Show password'}>{show ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}</button>
    </div>
  )
}

export function AdminLogin() {
  const { adminLogin, adminVerify, isAuthenticated, user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [mfaToken, setMfaToken] = useState('')   // set after the password step when two-step verification is on
  const [code, setCode] = useState('')
  useEffect(() => { document.title = 'Administrator sign in · CareBridge AI' }, [])
  useEffect(() => { if (isAuthenticated && user?.role === 'admin') navigate('/admin', { replace: true }) }, [isAuthenticated, user, navigate])

  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const profile = await adminLogin(email, password)
      if (profile.mfa_required) { setMfaToken(profile.mfa_token); setPassword(''); return }
      toast.success(`Welcome, ${profile.name}!`)
      navigate('/admin', { replace: true })
    } catch (err) { setError(err.message || 'Could not sign in.') } finally { setLoading(false) }
  }
  const verify = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const profile = await adminVerify(mfaToken, code)
      toast.success(`Welcome, ${profile.name}!`)
      navigate('/admin', { replace: true })
    } catch (err) {
      setError(err.message || 'Could not verify the code.')
      if (/expired|invalid verification/i.test(err.message || '')) { setMfaToken(''); setCode('') }
    } finally { setLoading(false) }
  }
  return (
    <Shell title="Administrator sign in" subtitle="Manage organization needs and review AI donor suggestions."
      footer={<><p>Administrator accounts are created during first-time setup or by an existing administrator.</p><p>Not an administrator? <Link to="/login" className="font-semibold text-sky-600 hover:underline">Use the normal sign in</Link></p></>}>
      <ErrorBox error={error} />
      {mfaToken ? (
        <form onSubmit={verify} className="mt-5 space-y-4" noValidate>
          <p className="rounded-xl bg-teal-50 p-3.5 text-sm text-teal-800">Your password is correct. Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
          <Field label="Verification code"><input className="field" inputMode="text" autoComplete="one-time-code" autoFocus required maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" /></Field>
          <Button type="submit" loading={loading} disabled={code.replace(/[\s-]/g, '').length < 6} className="w-full py-3">{loading ? 'Verifying…' : 'Verify and sign in'}</Button>
          <button type="button" onClick={() => { setMfaToken(''); setCode(''); setError('') }} className="w-full text-center text-sm font-semibold text-sky-600 hover:underline">Back to password</button>
        </form>
      ) : (
      <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
        <Field label="Email"><div className="relative"><IconMail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@carebridge.org" /></div></Field>
        <Field label="Password"><PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} show={show} setShow={setShow} placeholder="Your password" autoComplete="current-password" /></Field>
        <div className="flex justify-end"><Link to="/forgot-password" className="text-sm font-semibold text-sky-600 hover:underline">Forgot password?</Link></div>
        <Button type="submit" loading={loading} disabled={!email || !password} className="w-full py-3">{loading ? 'Signing in…' : 'Sign in as administrator'}</Button>
      </form>
      )}
    </Shell>
  )
}

/** First-time setup: creates the very first administrator with the one-time token from backend/.env. */
export function AdminSetup() {
  const toast = useToast()
  const navigate = useNavigate()
  const [open, setOpen] = useState(null)          // null = checking
  const [f, setF] = useState({ setup_token: '', full_name: '', email: '', designation: '', password: '', confirm_password: '' })
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))
  useEffect(() => { document.title = 'Administrator setup · CareBridge AI' }, [])
  useEffect(() => { api.adminSetupStatus().then((r) => setOpen(!!r.setup_open)).catch(() => setOpen(false)) }, [])

  const submit = async (e) => {
    e.preventDefault(); setError('')
    if (f.password !== f.confirm_password) { setError('The two passwords do not match.'); return }
    setLoading(true)
    try {
      await api.adminSetup({ ...f, designation: f.designation || null })
      toast.success('Administrator created. You can sign in now.')
      navigate('/admin/login', { replace: true })
    } catch (err) { setError(err.message || 'Could not create the administrator.') } finally { setLoading(false) }
  }

  return (
    <Shell title="Administrator setup" subtitle="Create the first administrator of this installation. This works once."
      footer={<p>Already set up? <Link to="/admin/login" className="font-semibold text-sky-600 hover:underline">Administrator sign in</Link></p>}>
      {open === null && <p className="mt-5 text-sm text-ink-muted">Checking setup status…</p>}
      {open === false && (
        <div role="status" className="mt-5 rounded-xl bg-amber-50 p-3.5 text-sm text-amber-900 ring-1 ring-amber-100">
          Setup is closed. Either an administrator already exists, or <code>ADMIN_SETUP_TOKEN</code> (24+ characters) is not set in <code>backend/.env</code>.
          Existing administrators add colleagues under Administration &gt; Administrators.
        </div>
      )}
      {open === true && (
        <>
          <ErrorBox error={error} />
          <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
            <Field label="Setup token" hint="The ADMIN_SETUP_TOKEN value from backend/.env"><input className="field" type="password" autoComplete="off" required maxLength={500} value={f.setup_token} onChange={set('setup_token')} /></Field>
            <Field label="Full name"><input className="field" autoComplete="name" required maxLength={200} value={f.full_name} onChange={set('full_name')} /></Field>
            <Field label="Email"><input className="field" type="email" autoComplete="username" required value={f.email} onChange={set('email')} placeholder="admin@carebridge.org" /></Field>
            <Field label="Designation (optional)"><input className="field" maxLength={200} value={f.designation} onChange={set('designation')} placeholder="Program Director" /></Field>
            <Field label="Password"><PasswordInput value={f.password} onChange={set('password')} show={show} setShow={setShow} placeholder="At least 12 characters" autoComplete="new-password" min={12} /></Field>
            <PasswordStrength password={f.password} />
            <Field label="Confirm password"><PasswordInput value={f.confirm_password} onChange={set('confirm_password')} show={show} setShow={setShow} placeholder="Repeat the password" autoComplete="new-password" min={12} /></Field>
            <Button type="submit" loading={loading} disabled={!f.setup_token || !f.email || !f.full_name || !f.password || !f.confirm_password} className="w-full py-3">{loading ? 'Creating…' : 'Create administrator'}</Button>
          </form>
        </>
      )}
    </Shell>
  )
}
