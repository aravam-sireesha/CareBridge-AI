import React, { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth, useLogout } from '../context/AuthContext.jsx'
import { useTheme } from '../context/ThemeContext.jsx'
import SecurityTab from '../components/SecurityTab.jsx'
import { ThemeSwitch } from '../components/ProfileMenu.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import KnowledgeModal from '../components/KnowledgeModal.jsx'
import { Button, ErrorState, Field, Modal, PageHeader, Pill, Skeleton, TableSkeleton, Tabs, formatDate } from '../components/ui.jsx'
import { IconBook, IconBuilding, IconCheck, IconCopy, IconDatabase, IconKey, IconLogout, IconMoon, IconPeople, IconSettings, IconSun, IconX } from '../components/icons.jsx'

function LogoutCard() {
  const logout = useLogout()
  return (
    <div className="card mt-5 flex max-w-xl flex-wrap items-center justify-between gap-3 p-5">
      <div><p className="text-sm font-semibold text-ink">Sign out</p><p className="text-xs text-ink-muted">End your session on this device. You can sign in again at any time.</p></div>
      <Button variant="danger" onClick={logout}><IconLogout className="h-4 w-4" /> Log out</Button>
    </div>
  )
}

function ProfileTab() {
  const { user } = useAuth()
  const rows = [['Name', user.name], ['Email', user.email], ['Role', <StatusBadge key="r" status={user.role} />], ['Organization ID', user.organization_id ?? '–'], ['Donor ID', user.donor_id ?? '–'], ['Volunteer ID', user.volunteer_id ?? '–']]
  return (
    <>
    <div className="card max-w-xl p-6">
      <div className="mb-5 flex items-center gap-4"><span className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-teal-500 to-sky-600 font-display text-2xl font-bold text-white">{user.name.charAt(0).toUpperCase()}</span><div><p className="font-display text-lg font-semibold">{user.name}</p><p className="text-sm text-ink-muted">{user.email}</p></div></div>
      <dl className="divide-y divide-line">{rows.map(([k, v]) => <div key={k} className="flex items-center justify-between py-3 text-sm"><dt className="text-ink-muted">{k}</dt><dd className="font-semibold text-ink">{v}</dd></div>)}</dl>
    </div>
    <LogoutCard />
    </>
  )
}

function AppearanceTab() {
  const { mode, resolved } = useTheme()
  const label = mode === 'system' ? `System (currently ${resolved})` : mode === 'dark' ? 'Dark' : 'Light'
  return (
    <>
      <div className="card max-w-xl p-6">
        <div className="mb-4 flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-teal-50 text-teal-700">{resolved === 'dark' ? <IconMoon /> : <IconSun />}</span>
          <div><p className="font-display text-base font-semibold text-ink">Theme</p><p className="text-xs text-ink-muted">Current: {label}. Saved on this device.</p></div>
        </div>
        <ThemeSwitch />
        <p className="mt-3 text-xs text-ink-muted">Dark mode lowers glare in low light. “System” follows your device setting automatically.</p>
      </div>
      <LogoutCard />
    </>
  )
}

function UsersTab() {
  const toast = useToast()
  const { user: me } = useAuth()
  const { data, loading, error, reload } = useAsync(() => api.listUsers(), [])
  const [code, setCode] = useState(null)
  const changeRole = async (u, role) => { try { await api.setUserRole(u.id, role); toast.success('Role updated.'); reload({ silent: true }) } catch (e) { toast.error(e.message) } }
  const issue = async (u) => { try { setCode(await api.issueResetCode(u.id)) } catch (e) { toast.error(e.message) } }
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <TableSkeleton rows={4} cols={4} />
  return (
    <>
      <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
        <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Account</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Joined</th><th className="px-4 py-3 text-right">Actions</th></tr></thead>
        <tbody>{data.map((u) => (
          <tr key={u.id} className="border-b border-line last:border-0 hover:bg-teal-50/40">
            <td className="px-4 py-3.5"><p className="font-semibold text-ink">{u.display_name}</p><p className="text-xs text-ink-muted">{u.email}</p></td>
            <td className="px-4 py-3.5"><select aria-label="Role" disabled={u.id === me.id} value={u.role} onChange={(e) => changeRole(u, e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold capitalize">{['admin', 'organization', 'donor', 'volunteer'].map((r) => <option key={r}>{r}</option>)}</select></td>
            <td className="px-4 py-3.5 text-ink-muted">{formatDate(u.created_at)}</td>
            <td className="px-4 py-3.5 text-right"><Button variant="soft" className="px-3 py-1.5 text-xs" onClick={() => issue(u)}><IconKey className="h-3.5 w-3.5" /> Reset code</Button></td>
          </tr>))}</tbody></table></div></div>
      <Modal open={!!code} onClose={() => setCode(null)} title="One-time reset code" subtitle={code ? `For ${code.email}. Shown only once; expires in ${code.expires_in_minutes} minutes.` : ''}>
        {code && <><div className="break-all rounded-xl bg-bg p-4 font-mono text-[13px] text-ink">{code.token}</div>
          <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => { navigator.clipboard?.writeText(code.token); toast.success('Code copied.') }}><IconCopy className="h-4 w-4" /> Copy</Button><Button onClick={() => setCode(null)}>Done</Button></div>
          <p className="mt-3 text-xs text-ink-muted">Give this code to the account owner. They enter it on the “Forgot password” page.</p></>}
      </Modal>
    </>
  )
}

function OrganizationsTab() {
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.listOrganizations(), [])
  const toggle = async (o) => { try { await api.verifyOrganization(o.id, !o.verified); toast.success(o.verified ? 'Verification removed.' : 'Organization verified. Its needs are now visible to donors and volunteers.'); reload({ silent: true }) } catch (e) { toast.error(e.message) } }
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <TableSkeleton rows={4} cols={3} />
  return (
    <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[560px] text-sm">
      <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Organization</th><th className="px-4 py-3">Contact</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Action</th></tr></thead>
      <tbody>{data.map((o) => (
        <tr key={o.id} className="border-b border-line last:border-0 hover:bg-teal-50/40">
          <td className="px-4 py-3.5 font-semibold text-ink">{o.name}</td><td className="px-4 py-3.5 text-ink-muted">{o.contact || '–'}</td>
          <td className="px-4 py-3.5"><StatusBadge status={o.verified ? 'verified' : 'unverified'} /></td>
          <td className="px-4 py-3.5 text-right"><Button variant={o.verified ? 'danger' : 'primary'} className="px-3 py-1.5 text-xs" onClick={() => toggle(o)}>{o.verified ? <><IconX className="h-3.5 w-3.5" />Unverify</> : <><IconCheck className="h-3.5 w-3.5" />Verify</>}</Button></td>
        </tr>))}</tbody></table></div></div>
  )
}

function KnowledgeTab() {
  const toast = useToast()
  const kb = useAsync(() => api.listKnowledge(), [])
  const status = useAsync(() => api.assistantStatus(), [])
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [f, setF] = useState({ title: '', content: '', source: '' })
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try { await api.addKnowledge({ title: f.title, content: f.content, source: f.source || null }); toast.success('Entry saved and indexed.'); setOpen(false); setF({ title: '', content: '', source: '' }); kb.reload({ silent: true }); status.reload({ silent: true }) }
    catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  const reindex = async () => { setReindexing(true); try { const r = await api.reindexKnowledge(); toast.success(`${r.embedded} entries indexed.`); status.reload({ silent: true }) } catch (e) { toast.error(e.message) } finally { setReindexing(false) } }
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">{status.data ? `${status.data.embedded_entries} of ${status.data.knowledge_entries} entries are searchable by the assistant.` : ' '}</p>
        <div className="flex gap-2"><Button variant="ghost" loading={reindexing} onClick={reindex}>Index new entries</Button><Button onClick={() => setOpen(true)}>Add entry</Button></div>
      </div>
      {kb.error ? <ErrorState message={kb.error} onRetry={kb.reload} /> : kb.loading ? <TableSkeleton rows={4} cols={3} /> : (
        <div className="space-y-3">{(kb.data || []).map((k) => <div key={k.id} className="card p-4"><div className="flex items-start justify-between gap-3"><p className="font-semibold text-ink">{k.title}</p>{k.source && <Pill tone="sky">{k.source}</Pill>}</div><p className="mt-1.5 line-clamp-2 text-sm text-ink-muted">{k.content}</p></div>)}
          {!kb.data?.length && <p className="card p-6 text-center text-sm text-ink-muted">No entries yet.</p>}</div>
      )}
      <KnowledgeModal open={open} onClose={() => setOpen(false)} onSaved={() => { kb.reload({ silent: true }); status.reload({ silent: true }) }} />
    </>
  )
}

function SystemTab() {
  const { data, loading, error, reload } = useAsync(() => api.health(), [])
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <Skeleton className="h-64 w-full" />
  const ok = data.database.connected, schema = data.schema
  const checks = [
    ['PostgreSQL connection', ok, ok ? `Connected (${data.database.dialect})` : data.database.error],
    ['Database schema matches the code', schema?.ok, schema?.ok ? `Alembic revision ${schema.alembic_version || 'n/a'}` : schema ? (schema.fix + ' Missing: ' + JSON.stringify(schema.missing_columns) + (schema.missing_tables.length ? ' tables: ' + schema.missing_tables.join(', ') : '')) : 'Unknown'],
    ['SECRET_KEY configured', data.secret_key_configured, data.secret_key_configured ? 'Login tokens can be signed' : 'Add SECRET_KEY to backend/.env'],
    ['Career model loaded', data.models?.career_recommender, ''], ['Fraud model loaded', data.models?.fraud_detector, ''],
    ['RAG knowledge indexed', data.assistant?.embedded_entries > 0, data.assistant ? `${data.assistant.embedded_entries}/${data.assistant.knowledge_entries} entries · ${data.assistant.mode?.replace('_', ' ')}` : '']
  ]
  return (
    <>
      <div className="card divide-y divide-line">{checks.map(([l, good, note]) => (
        <div key={l} className="flex items-start gap-3 p-4"><span className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-white ${good ? 'bg-green-500' : 'bg-red-500'}`}>{good ? <IconCheck className="h-3.5 w-3.5" /> : <IconX className="h-3.5 w-3.5" />}</span><div><p className="text-sm font-semibold text-ink">{l}</p>{note && <p className="text-xs text-ink-muted">{note}</p>}</div></div>))}</div>
      {data.row_counts && <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{Object.entries(data.row_counts).map(([k, v]) => <div key={k} className="card p-4"><p className="text-xs capitalize text-ink-muted">{k.replace('_', ' ')}</p><p className="font-display text-2xl font-bold text-teal-700">{v}</p></div>)}</div>}
      <Button variant="ghost" className="mt-4" onClick={reload}>Re-check</Button>
    </>
  )
}

export default function Settings() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const isAdmin = user.role === 'admin'
  const logout = useLogout()
  const tabs = [{ key: 'profile', label: 'Profile', icon: IconSettings }, { key: 'appearance', label: 'Appearance', icon: IconMoon }, { key: 'security', label: 'Security', icon: IconKey }]
  if (isAdmin) tabs.push({ key: 'users', label: 'Users', icon: IconPeople }, { key: 'orgs', label: 'Organizations', icon: IconBuilding }, { key: 'knowledge', label: 'Knowledge base', icon: IconBook }, { key: 'system', label: 'System & database', icon: IconDatabase })
  const tab = tabs.some((t) => t.key === params.get('tab')) ? params.get('tab') : 'profile'
  return (
    <Layout title="Settings">
      <PageHeader icon={IconSettings} title="Settings" subtitle={isAdmin ? 'Manage accounts, organizations, the assistant knowledge base and system health.' : 'Your account details and appearance.'}
        actions={<button type="button" onClick={logout} className="btn bg-white/15 text-white hover:bg-white/25"><IconLogout className="h-4 w-4" /> Log out</button>} />
      {tabs.length > 1 && <Tabs tabs={tabs} value={tab} onChange={(k) => setParams({ tab: k })} />}
      {tab === 'profile' && <ProfileTab />}{tab === 'appearance' && <AppearanceTab />}{tab === 'security' && <SecurityTab />}{tab === 'users' && <UsersTab />}{tab === 'orgs' && <OrganizationsTab />}{tab === 'knowledge' && <KnowledgeTab />}{tab === 'system' && <SystemTab />}
    </Layout>
  )
}
