import React, { useState } from 'react'
import { api, tokenStore } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { Button, Field, PasswordStrength, Pill } from './ui.jsx'
import { IconCopy, IconKey, IconShield } from './icons.jsx'

function Card({ icon: Icon, title, text, children }) {
  return (
    <div className="card max-w-xl p-6">
      <div className="mb-4 flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-xl bg-teal-50 text-teal-700"><Icon /></span><div><p className="font-display text-base font-semibold text-ink">{title}</p><p className="text-xs text-ink-muted">{text}</p></div></div>
      {children}
    </div>
  )
}

function PasswordCard() {
  const toast = useToast()
  const [f, setF] = useState({ current: '', next: '', confirm: '' })
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const mismatch = f.confirm && f.next !== f.confirm
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      const r = await api.changePassword(f.current, f.next)
      tokenStore.set(r.access_token)
      toast.success('Password changed. Your other devices were signed out.')
      setF({ current: '', next: '', confirm: '' })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  const type = show ? 'text' : 'password'
  return (
    <Card icon={IconKey} title="Change password" text="Use at least 12 characters and mix upper case, lower case, numbers and symbols.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Current password"><input className="field" aria-label="Current password" type={type} required autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
        <Field label="New password"><input className="field" aria-label="New password" type={type} required minLength={12} maxLength={128} autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} /><PasswordStrength password={f.next} /></Field>
        <Field label="Confirm new password" error={mismatch ? 'Passwords do not match' : ''}><input className="field" aria-label="Confirm new password" type={type} required autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></Field>
        <div className="flex items-center justify-between gap-3"><label className="flex items-center gap-2 text-xs text-ink-muted"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />Show passwords</label>
          <Button type="submit" loading={saving} disabled={!f.current || f.next.length < 12 || !!mismatch || !f.confirm}>Change password</Button></div>
      </form>
    </Card>
  )
}

function SessionsCard() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try { const r = await api.logoutAll(); tokenStore.set(r.access_token); toast.success('Signed out of all other devices.') } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  return (
    <Card icon={IconShield} title="Signed-in devices" text="Lost a phone or used a shared computer? End every other session. This device stays signed in.">
      <Button variant="danger" loading={busy} onClick={run}>Sign out of all other devices</Button>
    </Card>
  )
}

function Codes({ codes, onDone }) {
  const toast = useToast()
  const text = codes.join('\n')
  const copy = async () => { try { await navigator.clipboard.writeText(text); toast.success('Recovery codes copied.') } catch { toast.error('Could not copy. Select and copy them by hand.') } }
  const download = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([`CareBridge AI recovery codes\nEach code works once.\n\n${text}\n`], { type: 'text/plain' })); a.download = 'carebridge-recovery-codes.txt'; a.click(); URL.revokeObjectURL(a.href) }
  return (
    <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-semibold text-amber-800">Save your recovery codes now</p>
      <p className="mt-1 text-xs text-amber-800">If you lose your phone, each of these codes lets you sign in once. They are shown only this one time.</p>
      <ul className="mt-3 grid grid-cols-2 gap-2 font-mono text-sm text-ink">{codes.map((c) => <li key={c} className="rounded-lg bg-white px-3 py-1.5 ring-1 ring-line">{c}</li>)}</ul>
      <div className="mt-3 flex flex-wrap gap-2"><Button variant="ghost" onClick={copy}><IconCopy className="h-4 w-4" />Copy</Button><Button variant="ghost" onClick={download}>Download</Button><Button onClick={onDone}>I have saved them</Button></div>
    </div>
  )
}

function TwoFactorCard() {
  const toast = useToast()
  const status = useAsync(() => api.twoFaStatus(), [])
  const [setup, setSetup] = useState(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [off, setOff] = useState({ open: false, password: '', code: '' })
  const [regen, setRegen] = useState({ open: false, password: '' })
  const enabled = status.data?.enabled

  const act = async (fn) => { setBusy(true); try { await fn() } catch (e) { toast.error(e.message) } finally { setBusy(false) } }
  const start = () => act(async () => { setSetup(await api.twoFaSetup()); setCode('') })
  const enable = (e) => { e.preventDefault(); act(async () => { const r = await api.twoFaEnable(code.trim()); setCodes(r.recovery_codes); setSetup(null); status.reload({ silent: true }); toast.success('Two-step verification is on.') }) }
  const disable = (e) => { e.preventDefault(); act(async () => { await api.twoFaDisable(off.password, off.code.trim()); setOff({ open: false, password: '', code: '' }); status.reload({ silent: true }); toast.success('Two-step verification is off.') }) }
  const newCodes = (e) => { e.preventDefault(); act(async () => { const r = await api.twoFaRecoveryCodes(regen.password); setCodes(r.recovery_codes); setRegen({ open: false, password: '' }); status.reload({ silent: true }) }) }
  const spaced = (s) => s.replace(/(.{4})/g, '$1 ').trim()

  return (
    <Card icon={IconShield} title="Two-step verification" text="Administrators control children's data, so a code from your phone is required on every sign-in.">
      <div className="mb-4 flex items-center gap-2"><Pill tone={enabled ? 'green' : 'amber'}>{status.loading ? 'Checking…' : enabled ? 'On' : 'Off'}</Pill>{enabled && <span className="text-xs text-ink-muted">{status.data.recovery_codes_left} recovery code(s) left</span>}</div>
      {codes && <Codes codes={codes} onDone={() => setCodes(null)} />}
      {!enabled && !setup && !codes && <Button loading={busy} onClick={start}>Set up two-step verification</Button>}
      {!enabled && setup && (
        <form onSubmit={enable} className="space-y-4">
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-ink-muted"><li>Install an authenticator app (Google Authenticator, Microsoft Authenticator, Authy…).</li><li>Add an account and enter this key (or tap the link on your phone).</li><li>Type the 6-digit code the app shows.</li></ol>
          <div className="rounded-xl bg-bg p-3"><p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Setup key</p><p className="mt-1 break-all font-mono text-base font-semibold text-ink" data-testid="setup-key">{spaced(setup.secret)}</p><a className="mt-1 inline-block text-xs font-semibold text-sky-600 hover:underline" href={setup.otpauth_uri}>Open in authenticator app</a></div>
          <Field label="6-digit code"><input className="field" inputMode="numeric" autoComplete="one-time-code" maxLength={8} required value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" /></Field>
          <div className="flex gap-2"><Button type="button" variant="ghost" onClick={() => setSetup(null)}>Cancel</Button><Button type="submit" loading={busy} disabled={code.replace(/\s/g, '').length < 6}>Turn on</Button></div>
        </form>
      )}
      {enabled && !codes && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => setRegen({ open: !regen.open, password: '' })}>New recovery codes</Button><Button variant="danger" onClick={() => setOff({ open: !off.open, password: '', code: '' })}>Turn off</Button></div>
          {regen.open && <form onSubmit={newCodes} className="space-y-3 rounded-xl bg-bg p-3"><Field label="Confirm with your password"><input className="field" type="password" required autoComplete="current-password" value={regen.password} onChange={(e) => setRegen({ ...regen, password: e.target.value })} /></Field><Button type="submit" loading={busy} disabled={!regen.password}>Create new codes</Button></form>}
          {off.open && <form onSubmit={disable} className="space-y-3 rounded-xl bg-bg p-3"><Field label="Password"><input className="field" type="password" required autoComplete="current-password" value={off.password} onChange={(e) => setOff({ ...off, password: e.target.value })} /></Field><Field label="Current code or recovery code"><input className="field" required value={off.code} onChange={(e) => setOff({ ...off, code: e.target.value })} /></Field><Button type="submit" variant="danger" loading={busy} disabled={!off.password || !off.code}>Turn off two-step verification</Button></form>}
        </div>
      )}
    </Card>
  )
}

export default function SecurityTab() {
  const { user } = useAuth()
  return <div className="space-y-5"><PasswordCard /><SessionsCard />{user?.role === 'admin' && <TwoFactorCard />}</div>
}
