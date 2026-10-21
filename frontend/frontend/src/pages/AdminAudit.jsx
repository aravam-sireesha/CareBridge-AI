import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, EmptyState, ErrorState, Field, PageHeader, Pill, TableSkeleton } from '../components/ui.jsx'
import { IconShield } from '../components/icons.jsx'

const PAGE = 25
const tone = (a) => (a.includes('failed') || a.includes('locked') || a.includes('fraud') || a.includes('deleted') || a.includes('deactivated') ? 'red'
  : a.startsWith('auth.') || a.includes('2fa') || a.includes('login') ? 'sky' : a.includes('verified') || a.includes('approved') || a.includes('delivered') ? 'green' : 'teal')
export const prettyAction = (a) => a.replace(/[._]/g, ' ').replace(/^./, (c) => c.toUpperCase())
const when = (v) => (v ? new Date(v.endsWith('Z') ? v : `${v}Z`).toLocaleString() : '–')
const detail = (d) => (d ? Object.entries(d).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ') : '')

export default function AdminAudit() {
  const [action, setAction] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const q = new URLSearchParams({ limit: PAGE, offset })
  if (action) q.set('action', action)
  if (search.trim()) q.set('search', search.trim())
  const log = useAsync(() => api.adminAudit(`?${q.toString()}`), [action, search, offset])
  const d = log.data
  const groups = [...new Set((d?.actions || []).map((a) => a.split('.')[0]))]
  return (
    <Layout title="Audit trail">
      <PageHeader icon={IconShield} tone="teal" title="Audit trail" subtitle="A permanent record of sign-ins, security events and every decision an administrator makes. Entries cannot be edited or deleted." />
      <div className="card mb-5 grid gap-3 p-4 sm:grid-cols-2">
        <Field label="Type of event"><select className="field capitalize" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0) }}><option value="">All events</option>{groups.map((g) => <option key={g} value={g}>{g}</option>)}</select></Field>
        <Field label="Search by person or event"><input className="field" value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0) }} placeholder="name@example.org or “login”" /></Field>
      </div>
      {log.error ? <ErrorState message={log.error} onRetry={log.reload} /> : log.loading && !d ? <TableSkeleton rows={6} cols={5} /> : !d?.items.length ? <EmptyState icon={IconShield} title="No events match" /> : (
        <>
          <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-sm">
            <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">When</th><th className="px-4 py-3">Who</th><th className="px-4 py-3">Event</th><th className="px-4 py-3">Details</th><th className="px-4 py-3">From</th></tr></thead>
            <tbody>{d.items.map((r) => (
              <tr key={r.id} className="border-b border-line align-top last:border-0 hover:bg-teal-50/40">
                <td className="whitespace-nowrap px-4 py-3 text-xs text-ink-muted">{when(r.created_at)}</td>
                <td className="px-4 py-3"><p className="text-ink">{r.actor_email || 'Not signed in'}</p>{r.actor_role && <p className="text-[11px] capitalize text-ink-muted">{r.actor_role}</p>}</td>
                <td className="px-4 py-3"><Pill tone={tone(r.action)}>{prettyAction(r.action)}</Pill>{r.entity_type && <p className="mt-1 text-[11px] text-ink-muted">{r.entity_type.replace(/_/g, ' ')} #{r.entity_id}</p>}</td>
                <td className="px-4 py-3 text-xs text-ink-muted">{detail(r.detail)}</td>
                <td className="px-4 py-3 text-xs text-ink-muted">{r.ip || '–'}</td>
              </tr>))}</tbody></table></div></div>
          <div className="mt-4 flex items-center justify-between text-sm text-ink-muted"><span>{offset + 1}–{offset + d.items.length} of {d.total}</span>
            <div className="flex gap-2"><Button variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Button><Button variant="ghost" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>Older</Button></div></div>
        </>
      )}
    </Layout>
  )
}
