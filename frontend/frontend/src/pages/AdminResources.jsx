import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import ResourceInventory from '../components/ResourceInventory.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Reasons, ScoreBar } from '../components/AdminParts.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, Field, Modal, PageHeader, Tabs } from '../components/ui.jsx'
import { IconDatabase, IconPlus, IconSpark } from '../components/icons.jsx'

const NEXT = { proposed: [['approved', 'Approve', 'primary'], ['rejected', 'Reject', 'danger']], approved: [['delivered', 'Mark delivered', 'primary'], ['cancelled', 'Cancel', 'ghost']] }

function ManualModal({ open, onClose, onSaved }) {
  const toast = useToast()
  const resources = useAsync(() => (open ? api.resources() : Promise.resolve([])), [open])
  const needs = useAsync(() => (open ? api.adminNeeds('?status=open') : Promise.resolve([])), [open])
  const [f, setF] = useState({ resource_id: '', need_id: '', quantity: 1 })
  const [saving, setSaving] = useState(false)
  const avail = (resources.data || []).filter((r) => r.status === 'available' && r.quantity_available > 0)
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try { await api.adminCreateAllocation({ resource_id: Number(f.resource_id), need_id: Number(f.need_id), quantity: Number(f.quantity) }); toast.success('Allocation proposed. Approve it in the list.'); onSaved(); onClose() }
    catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Allocate a resource to a need" subtitle="It is created as a proposal and still needs approval.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Resource"><select className="field" required value={f.resource_id} onChange={(e) => setF({ ...f, resource_id: e.target.value })}><option value="">Choose…</option>{avail.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.quantity_available} free)</option>)}</select></Field>
        <Field label="Need"><select className="field" required value={f.need_id} onChange={(e) => setF({ ...f, need_id: e.target.value })}><option value="">Choose…</option>{(needs.data || []).map((n) => <option key={n.id} value={n.id}>{n.category} · {n.organization_name} ({n.urgency})</option>)}</select></Field>
        <Field label="Quantity"><input className="field" type="number" min={1} required value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.resource_id || !f.need_id}>Propose allocation</Button></div>
      </form>
    </Modal>
  )
}

function Allocations() {
  const toast = useToast()
  const list = useAsync(() => api.adminAllocations(), [])
  const needs = useAsync(() => api.adminNeeds('?status=open'), [])
  const [needId, setNeedId] = useState('')
  const [busy, setBusy] = useState(false)
  const [manual, setManual] = useState(false)
  const [tab, setTab] = useState('proposed')
  const rows = list.data || []
  const groups = { proposed: rows.filter((r) => r.status === 'proposed'), approved: rows.filter((r) => r.status === 'approved'), delivered: rows.filter((r) => r.status === 'delivered'), other: rows.filter((r) => ['rejected', 'cancelled'].includes(r.status)) }
  const decide = async (a, decision) => {
    setBusy(true)
    try { await api.adminReviewAllocation(a.id, decision); toast.success(`Allocation ${decision}.`); list.reload({ silent: true }) } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const suggest = async () => {
    setBusy(true)
    try { const r = await api.adminSuggestResources(needId); toast.success(r.allocations.length ? `${r.allocations.length} allocation(s) available for this need.` : 'No available resource fits this need yet.'); list.reload({ silent: true }); setTab('proposed') }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <div className="card mb-5 flex flex-wrap items-end gap-3 p-4">
        <Field label="Let the AI find resources for a need" className="min-w-[16rem] flex-1"><select className="field" value={needId} onChange={(e) => setNeedId(e.target.value)}><option value="">Choose an open need…</option>{(needs.data || []).map((n) => <option key={n.id} value={n.id}>{n.category} · {n.organization_name} ({n.urgency}, qty {n.quantity})</option>)}</select></Field>
        <Button loading={busy} disabled={!needId} onClick={suggest}><IconSpark className="h-4 w-4" /> Suggest resources</Button>
        <Button variant="ghost" onClick={() => setManual(true)}><IconPlus className="h-4 w-4" /> Allocate manually</Button>
      </div>
      <Tabs tabs={[{ key: 'proposed', label: `To review (${groups.proposed.length})` }, { key: 'approved', label: `Approved (${groups.approved.length})` }, { key: 'delivered', label: `Delivered (${groups.delivered.length})` }, { key: 'other', label: `Closed (${groups.other.length})` }]} value={tab} onChange={setTab} />
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading ? <CardSkeleton rows={2} /> : groups[tab].length === 0 ? <EmptyState icon={IconDatabase} title="Nothing here" /> : (
        <div className="space-y-3">{groups[tab].map((a) => (
          <div key={a.id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold text-ink">{a.quantity} {a.unit || ''} × {a.resource_name} → {a.need_category}</p><p className="text-xs text-ink-muted">{a.organization_name} · {a.need_urgency} urgency · need quantity {a.need_quantity}</p></div><StatusBadge status={a.status} /></div>
            {a.score != null && <div className="mt-3 max-w-xs"><ScoreBar label="AI fit" value={a.score} /></div>}
            <Reasons items={a.reasons} />
            {NEXT[a.status] && <div className="mt-3 flex flex-wrap justify-end gap-2">{NEXT[a.status].map(([d, label, variant]) => <Button key={d} variant={variant} disabled={busy} className="px-3 py-1.5 text-xs" onClick={() => decide(a, d)}>{label}</Button>)}</div>}
          </div>))}</div>
      )}
      <ManualModal open={manual} onClose={() => setManual(false)} onSaved={() => list.reload({ silent: true })} />
    </>
  )
}

export default function AdminResources() {
  const [tab, setTab] = useState('inventory')
  return (
    <Layout title="Resources">
      <PageHeader icon={IconDatabase} tone="green" title="Resources & allocation" subtitle="Materials, services and funds from every organization, and the AI-proposed allocation of them to needs." />
      <Tabs tabs={[{ key: 'inventory', label: 'Inventory' }, { key: 'allocations', label: 'Allocations' }]} value={tab} onChange={setTab} />
      {tab === 'inventory' ? <ResourceInventory isAdmin /> : <Allocations />}
    </Layout>
  )
}
