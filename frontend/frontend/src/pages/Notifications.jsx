import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, EmptyState, ErrorState, PageHeader, Pagination, Pill, Section, TableSkeleton, Tabs } from '../components/ui.jsx'
import { IconBell } from '../components/icons.jsx'

const KINDS = [['', 'All categories'], ['verification', 'Verification'], ['donation', 'Donations'], ['need', 'Needs'], ['volunteer', 'Volunteering'], ['security', 'Security'], ['admin', 'Administration']]
const PREFS = [['in_app', 'Show notifications in the app'], ['verification', 'Verification updates'], ['donation', 'Donation updates'], ['need', 'Need updates'], ['volunteer', 'Volunteer activity'], ['admin', 'Administrative actions']]
const changed = () => window.dispatchEvent(new Event('cb:notifications-changed'))

function Preferences() {
  const toast = useToast()
  const prefs = useAsync(() => api.notificationPrefs(), [])
  const [busy, setBusy] = useState('')
  const p = prefs.data?.preferences
  const toggle = async (key) => {
    setBusy(key)
    try { prefs.setData(await api.saveNotificationPrefs({ [key]: !p[key] })); toast.success('Preference saved.') } catch (e) { toast.error(e.message) } finally { setBusy('') }
  }
  return (
    <Section title="Notification preferences">
      {prefs.error ? <ErrorState message={prefs.error} onRetry={prefs.reload} /> : !p ? <TableSkeleton rows={3} cols={1} /> : (
        <div className="card divide-y divide-line">
          {PREFS.map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm text-ink">
              <span>{label}</span><input type="checkbox" role="switch" checked={p[key]} disabled={busy === key} onChange={() => toggle(key)} />
            </label>
          ))}
          <p className="px-4 py-3 text-xs text-ink-muted">Important security alerts are always delivered. Email notifications are not available yet.</p>
        </div>
      )}
    </Section>
  )
}

export default function Notifications() {
  const toast = useToast()
  const [tab, setTab] = useState('all')
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const list = useAsync(() => api.notifications({ page, page_size: 15, kind, unread_only: tab === 'unread' ? 'true' : '' }), [page, kind, tab])
  const d = list.data
  const read = async (n) => { try { await api.markNotificationRead(n.id); list.reload({ silent: true }); changed() } catch (e) { toast.error(e.message) } }
  const readAll = async () => { try { await api.markAllNotificationsRead(); toast.success('All notifications marked as read.'); list.reload({ silent: true }); changed() } catch (e) { toast.error(e.message) } }
  return (
    <Layout title="Notifications">
      <PageHeader icon={IconBell} title="Notifications" subtitle="Updates about your account, donations, needs and verification."
        actions={<Button variant="ghost" onClick={readAll} disabled={!d?.unread} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25">Mark all as read</Button>} />
      <Tabs tabs={[{ key: 'all', label: 'All' }, { key: 'unread', label: `Unread${d ? ` (${d.unread})` : ''}` }]} value={tab} onChange={(k) => { setTab(k); setPage(1) }} />
      <label className="mb-4 block max-w-xs"><span className="sr-only">Category</span><select className="field" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && !d ? <TableSkeleton rows={4} cols={1} /> : d.items.length === 0 ? (
        <EmptyState icon={IconBell} title={tab === 'unread' ? 'You are all caught up' : 'No notifications yet'} text="New updates will appear here." />
      ) : (
        <ul className="card divide-y divide-line">
          {d.items.map((n) => (
            <li key={n.id} className={`flex flex-wrap items-start justify-between gap-3 px-4 py-3 ${n.is_read ? '' : 'bg-teal-50/60'}`}>
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">{!n.is_read && <span className="h-2 w-2 rounded-full bg-teal-700" aria-label="Unread" />}{n.title}<Pill tone="gray" className="capitalize">{n.kind}</Pill></p>
                {n.body && <p className="mt-0.5 break-words text-sm text-ink-muted">{n.body}</p>}
                <p className="mt-1 text-xs text-ink-muted">{new Date(n.created_at).toLocaleString()}{n.link && <> · <Link className="font-semibold text-teal-700 hover:underline" to={n.link} onClick={() => !n.is_read && read(n)}>Open</Link></>}</p>
              </div>
              {!n.is_read && <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => read(n)}>Mark as read</Button>}
            </li>
          ))}
        </ul>
      )}
      {d && <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} label="notifications" />}
      <div className="mt-10"><Preferences /></div>
    </Layout>
  )
}
