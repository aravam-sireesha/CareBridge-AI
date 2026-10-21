import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { Button, Field, PasswordStrength } from '../components/ui.jsx'
import Logo from '../components/Logo.jsx'
import { IconBuilding, IconDonations, IconPeople, IconAlert, IconEye, IconEyeOff, IconCheck } from '../components/icons.jsx'

const ROLES = [
  { key: 'organization', label: 'Organization', hint: 'NGO, orphanage or school', icon: IconBuilding, tone: 'text-teal-700 bg-teal-50' },
  { key: 'donor', label: 'Donor', hint: 'Give money or resources', icon: IconDonations, tone: 'text-rose-600 bg-rose-50' },
  { key: 'volunteer', label: 'Volunteer', hint: 'Share time and skills', icon: IconPeople, tone: 'text-sky-700 bg-sky-50' }
]

export default function Register() {
  const [params] = useSearchParams()
  const initial = ROLES.some((r) => r.key === params.get('role')) ? params.get('role') : 'organization'
  const [role, setRole] = useState(initial)
  const [f, setF] = useState({ email: '', password: '', confirm: '', organization_name: '', name: '', contact: '', location: '', preferences: '', skills: '', availability: '' })
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const toast = useToast()
  const navigate = useNavigate()
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))

  useEffect(() => { document.title = 'Create account · CareBridge AI' }, [])

  const mismatch = f.confirm && f.password !== f.confirm
  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (f.password !== f.confirm) return setError('The two passwords do not match.')
    const payload = { email: f.email.trim(), password: f.password, role, contact: f.contact.trim() || undefined }
    if (role === 'organization') payload.organization_name = f.organization_name.trim()
    else payload.name = f.name.trim()
    if (f.location.trim()) payload.location = f.location.trim()
    if (role === 'donor' && f.preferences.trim()) payload.preferences = f.preferences.trim()
    if (role === 'volunteer') {
      if (f.skills.trim()) payload.skills = f.skills.trim()
      if (f.availability.trim()) payload.availability = f.availability.trim()
    }
    setLoading(true)
    try {
      await api.register(payload)
      toast.success('Account created. Please sign in.')
      navigate('/login')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-mesh min-h-screen px-4 py-8 sm:py-12">
      <div className="mx-auto max-w-2xl">
        <div className="mb-6 flex items-center justify-between"><Link to="/"><Logo size={40} /></Link><Link to="/login" className="btn-ghost">I have an account</Link></div>
        <form onSubmit={submit} className="card reveal p-6 shadow-lift sm:p-9">
          <h1 className="font-display text-2xl font-bold text-teal-900">Create your account</h1>
          <p className="mt-1 text-sm text-ink-muted">Choose how you want to help. Your details are stored securely in the CareBridge database.</p>

          <div className="mt-6 grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Account type">
            {ROLES.map((r) => (
              <button type="button" key={r.key} role="radio" aria-checked={role === r.key} onClick={() => setRole(r.key)}
                className={`relative rounded-2xl border-2 p-4 text-left transition ${role === r.key ? 'border-teal-500 bg-teal-50/50 shadow-card' : 'border-line bg-white hover:border-teal-300'}`}>
                {role === r.key && <span className="absolute right-3 top-3 grid h-5 w-5 place-items-center rounded-full bg-teal-600 text-white"><IconCheck className="h-3 w-3" /></span>}
                <span className={`grid h-10 w-10 place-items-center rounded-xl ${r.tone}`}><r.icon /></span>
                <p className="mt-3 text-sm font-semibold text-ink">{r.label}</p><p className="text-xs text-ink-muted">{r.hint}</p>
              </button>
            ))}
          </div>

          {error && <div role="alert" className="mt-5 flex items-start gap-2.5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100"><IconAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{error}</span></div>}

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {role === 'organization'
              ? <Field label="Organization name" className="sm:col-span-2"><input className="field" required maxLength={200} value={f.organization_name} onChange={set('organization_name')} placeholder="Hope Children's Home" /></Field>
              : <Field label="Full name" className="sm:col-span-2"><input className="field" required maxLength={200} value={f.name} onChange={set('name')} placeholder="Your full name" /></Field>}
            <Field label="Email"><input className="field" type="email" required autoComplete="email" value={f.email} onChange={set('email')} placeholder="you@example.org" /></Field>
            <Field label="Mobile / contact"><input className="field" type="tel" maxLength={300} value={f.contact} onChange={set('contact')} placeholder="+91 98765 43210" /></Field>
            <Field label="Location"><input className="field" maxLength={200} value={f.location} onChange={set('location')} placeholder="City, State" /></Field>
            {role === 'donor' && <Field label="What would you like to support?"><input className="field" maxLength={2000} value={f.preferences} onChange={set('preferences')} placeholder="education, food, health" /></Field>}
            {role === 'volunteer' && <>
              <Field label="Skills"><input className="field" maxLength={2000} value={f.skills} onChange={set('skills')} placeholder="tutoring, mentoring, first aid" /></Field>
              <Field label="Availability"><input className="field" maxLength={300} value={f.availability} onChange={set('availability')} placeholder="weekends, evenings" /></Field>
            </>}
            <Field label="Password" className="sm:col-span-2">
              <div className="relative">
                <input className="field pr-11" type={show ? 'text' : 'password'} required minLength={12} maxLength={128} autoComplete="new-password" value={f.password} onChange={set('password')} placeholder="At least 12 characters" />
                <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-ink-muted hover:bg-bg" aria-label={show ? 'Hide password' : 'Show password'}>{show ? <IconEyeOff className="h-4 w-4" /> : <IconEye className="h-4 w-4" />}</button>
              </div>
              <PasswordStrength password={f.password} />
            </Field>
            <Field label="Confirm password" className="sm:col-span-2" error={mismatch ? 'Passwords do not match' : ''}>
              <input className="field" type={show ? 'text' : 'password'} required autoComplete="new-password" value={f.confirm} onChange={set('confirm')} placeholder="Repeat your password" />
            </Field>
          </div>

          <Button type="submit" loading={loading} disabled={f.password.length < 12 || mismatch} className="mt-7 w-full py-3">{loading ? 'Creating account…' : 'Create account'}</Button>
          <p className="mt-4 text-center text-xs text-ink-muted">New organizations are reviewed by an administrator before their needs become visible to donors and volunteers.</p>
        </form>
      </div>
    </div>
  )
}
