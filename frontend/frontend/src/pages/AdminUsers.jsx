import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { useDebounced } from '../hooks/useDebounced.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, ConfirmDialog, EmptyState, ErrorState, Modal, PageHeader, Pagination, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconKey, IconSearch } from '../components/icons.jsx'

function ProfileModal({ user, onClose, onToggle }) {
  const audit = useAsync(() => api.adminUserAudit(user.id), [user.id])
  return (
    <Modal open onClose={onClose} wide title={user.name} subtitle={user.email}>
      <div className="mb-4 flex flex-wrap items-center gap-2"><StatusBadge status={user.role} /><StatusBadge status={user.is_active ? 'active' : 'inactive'} />{user.verification_status && <StatusBadge status={user.verification_status} />}{user.locked && <StatusBadge status="pending" />}</div>
      <p className="text-sm text-ink-muted">Registered {formatDate(user.created_at)} · last sign-in {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'not recorded'}{user.locked ? ' · temporarily locked after failed sign-ins' : ''}</p>
      {user.role !== 'admin' && user.id && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant={user.is_active ? 'danger' : 'primary'} onClick={() => onToggle(user)}>{user.is_active ? 'Deactivate account' : 'Reactivate account'}</Button>
          <Link to="/settings?tab=users" className="btn-ghost">Change role in Settings</Link>
        </div>
      )}
      {user.role === 'admin' && <p className="mt-4 rounded-xl bg-bg p-3 text-sm text-ink-muted">Administrator accounts are managed under <Link className="font-semibold text-teal-700 hover:underline" to="/admin/team">Administrators</Link>.</p>}
      <h3 className="mb-2 mt-6 text-sm font-semibold text-ink">Account security & audit history</h3>
      {audit.error ? <ErrorState message={audit.error} onRetry={audit.reload} /> : !audit.data ? <TableSkeleton rows={3} cols={2} /> : audit.data.length === 0 ? <p className="text-sm text-ink-muted">No recorded activity.</p> : (
        <ul className="max-h-64 space-y-2 overflow-y-auto">{audit.data.map((a, i) => <li key={i} className="rounded-xl bg-bg px-3 py-2 text-sm"><span className="font-semibold">{a.action.replace(/[._]/g, ' ')}</span> · {new Date(a.at).toLocaleString()}{a.ip ? ` · ${a.ip}` : ''}{a.by && a.by !== user.email ? ` · by ${a.by}` : ''}</li>)}</ul>
      )}
    </Modal>
  )
}

export default function AdminUsers() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [state, setState] = useState('')
  const [page, setPage] = useState(1)
  const [profile, setProfile] = useState(null)
  const [toggle, setToggle] = useState(null)
  const [busy, setBusy] = useState(false)
  const dq = useDebounced(q)
  const list = useAsync(() => api.adminUsers({ q: dq, role, state, page, page_size: 20 }), [dq, role, state, page])
  const d = list.data
  const reset = (fn) => (e) => { fn(e.target.value); setPage(1) }
  const confirm = async (reason) => {
    setBusy(true)
    try {
      await api.adminSetUserActive(toggle.id, !toggle.is_active, reason)
      toast.success(toggle.is_active ? 'Account deactivated and signed out everywhere.' : 'Account reactivated.')
      setToggle(null); setProfile(null); list.reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  return (
    <Layout title="Users & Roles">
      <PageHeader icon={IconKey} title="Users & Roles" subtitle="Find accounts, review their security history, and deactivate access. Passwords and tokens are never shown." />
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="relative block min-w-[16rem] flex-1 sm:max-w-sm"><span className="sr-only">Search users</span><IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
          <input className="field pl-10" placeholder="Search name or email" value={q} onChange={reset(setQ)} /></label>
        <label><span className="sr-only">Role</span><select className="field" value={role} onChange={reset(setRole)}><option value="">All roles</option><option value="admin">Administrators</option><option value="organization">Organizations</option><option value="donor">Donors</option><option value="volunteer">Volunteers</option></select></label>
        <label><span className="sr-only">Account status</span><select className="field" value={state} onChange={reset(setState)}><option value="">Any status</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
      </div>
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && !d ? <TableSkeleton rows={6} cols={5} /> : d.items.length === 0 ? <EmptyState icon={IconKey} title="No users match" text="Try clearing a filter." /> : (
        <div className="card overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-wide text-ink-muted"><tr><th className="px-4 py-3">ID</th><th className="px-4 py-3">Name</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Registered</th><th className="px-4 py-3">Last sign-in</th><th className="px-4 py-3"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody className="divide-y divide-line">{d.items.map((u) => (
            <tr key={u.id}><td className="px-4 py-3 text-ink-muted">{u.id}</td><td className="px-4 py-3"><p className="font-semibold text-ink">{u.name}</p><p className="text-xs text-ink-muted">{u.email}</p></td>
              <td className="px-4 py-3"><StatusBadge status={u.role} /></td><td className="px-4 py-3"><StatusBadge status={u.is_active ? 'active' : 'inactive'} /></td>
              <td className="px-4 py-3 text-ink-muted">{formatDate(u.created_at)}</td><td className="px-4 py-3 text-ink-muted">{u.last_login_at ? formatDate(u.last_login_at) : '—'}</td>
              <td className="px-4 py-3 text-right"><Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setProfile(u)} aria-label={`View ${u.name}`}>View</Button></td></tr>))}
          </tbody></table></div>
      )}
      {d && <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} label="users" />}
      {profile && !toggle && <ProfileModal user={profile} onClose={() => setProfile(null)} onToggle={setToggle} />}
      {toggle && <ConfirmDialog open title={toggle.is_active ? `Deactivate ${toggle.name}?` : `Reactivate ${toggle.name}?`}
        text={toggle.is_active ? 'They are signed out everywhere at once and cannot sign in until reactivated. Their records are kept.' : 'They will be able to sign in again.'}
        confirmLabel={toggle.is_active ? 'Deactivate' : 'Reactivate'} tone={toggle.is_active ? 'danger' : 'primary'} reasonLabel="Reason" reasonRequired={toggle.is_active} loading={busy} onConfirm={confirm} onCancel={() => setToggle(null)} />}
    </Layout>
  )
}
