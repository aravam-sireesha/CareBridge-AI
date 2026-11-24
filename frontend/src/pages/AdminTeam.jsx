import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, ErrorState, Field, Modal, PageHeader, PasswordStrength, Pill, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconPeople, IconPlus } from '../components/icons.jsx'

export default function AdminTeam() {
  const toast = useToast()
  const team = useAsync(() => api.adminTeam(), [])
  const [open, setOpen] = useState(false)
  const blank = { full_name: '', email: '', phone: '', designation: '', password: '' }
  const [f, setF] = useState(blank)
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))

  const create = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      await api.adminAddAdmin({ full_name: f.full_name.trim(), email: f.email.trim(), password: f.password, phone: f.phone.trim() || undefined, designation: f.designation.trim() || undefined })
      toast.success('Administrator created. Share the password with them securely.'); setF(blank); setOpen(false); team.reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  const toggle = async (a) => {
    try { await api.adminSetActive(a.id, !a.is_active); toast.success(a.is_active ? 'Administrator deactivated.' : 'Administrator reactivated.'); team.reload({ silent: true }) } catch (err) { toast.error(err.message) }
  }
  return (
    <Layout title="Administrators">
      <PageHeader icon={IconPeople} tone="violet" title="Administrators" subtitle="Everyone who can manage organizations, needs, donors and AI suggestions."
        actions={<Button variant="ghost" onClick={() => setOpen(true)} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconPlus className="h-4 w-4" /> Add administrator</Button>} />
      {team.error ? <ErrorState message={team.error} onRetry={team.reload} /> : team.loading ? <TableSkeleton rows={3} cols={4} /> : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Administrator</th><th className="px-4 py-3">Designation</th><th className="px-4 py-3">Last sign in</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Action</th></tr></thead>
          <tbody>{(team.data || []).map((a) => (
            <tr key={a.id} className="border-b border-line last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5"><p className="font-semibold text-ink">{a.full_name}{a.is_you && <Pill tone="sky" className="ml-2">you</Pill>}</p><p className="text-xs text-ink-muted">{a.email}{a.phone ? ` · ${a.phone}` : ''}</p></td>
              <td className="px-4 py-3.5 text-ink-muted">{a.designation || '–'}</td>
              <td className="px-4 py-3.5 text-ink-muted">{a.last_login_at ? formatDate(a.last_login_at) : 'Never'}</td>
              <td className="px-4 py-3.5"><Pill tone={a.is_active ? 'green' : 'gray'}>{a.is_active ? 'Active' : 'Deactivated'}</Pill></td>
              <td className="px-4 py-3.5 text-right"><Button variant={a.is_active ? 'danger' : 'primary'} className="px-3 py-1.5 text-xs" disabled={a.is_you} onClick={() => toggle(a)}>{a.is_active ? 'Deactivate' : 'Reactivate'}</Button></td>
            </tr>))}</tbody></table></div></div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Add an administrator" subtitle="They can sign in at /admin/login straight away. No invite code is needed when an administrator adds them.">
        <form onSubmit={create} className="space-y-4">
          <Field label="Full name"><input className="field" required maxLength={200} value={f.full_name} onChange={set('full_name')} /></Field>
          <Field label="Email"><input className="field" type="email" required value={f.email} onChange={set('email')} /></Field>
          <div className="grid gap-4 sm:grid-cols-2"><Field label="Mobile"><input className="field" type="tel" value={f.phone} onChange={set('phone')} /></Field><Field label="Designation"><input className="field" value={f.designation} onChange={set('designation')} /></Field></div>
          <Field label="Temporary password" hint="At least 12 characters. Ask them to change it after the first sign in."><input className="field" type="text" required minLength={12} maxLength={128} autoComplete="off" value={f.password} onChange={set('password')} /><PasswordStrength password={f.password} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={saving} disabled={f.password.length < 12 || !f.full_name.trim() || !f.email}>Create administrator</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}
