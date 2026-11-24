import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { Button, EmptyState, ErrorState, Field, Modal, Pill, TableSkeleton } from './ui.jsx'
import { IconDatabase, IconEdit, IconPlus, IconTrash } from './icons.jsx'

const KINDS = ['material', 'service', 'funds']
const blank = { name: '', kind: 'material', category: '', quantity_total: 1, unit: '', description: '', status: 'available', organization_id: '' }

function ResourceForm({ open, resource, orgs, isAdmin, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(blank)
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open) setF(resource ? { ...blank, ...resource, category: resource.category || '', unit: resource.unit || '', description: resource.description || '', organization_id: resource.organization_id ? String(resource.organization_id) : '' } : blank) }, [open, resource])
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    const body = { name: f.name.trim(), kind: f.kind, category: f.category.trim() || null, quantity_total: Number(f.quantity_total), unit: f.unit.trim() || null, description: f.description.trim() || null }
    try {
      if (resource) await api.updateResource(resource.id, { ...body, status: f.status })
      else await api.createResource({ ...body, ...(isAdmin && f.organization_id ? { organization_id: Number(f.organization_id) } : {}) })
      toast.success(resource ? 'Resource updated.' : 'Resource added.'); onSaved(); onClose()
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title={resource ? 'Edit resource' : 'Add a resource'} subtitle="Resources are matched to needs by category, so use words like books, food, health or education.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="field" required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Class 8 textbook set" /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Type"><select className="field capitalize" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select></Field>
          <Field label="Category"><input className="field" maxLength={200} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} placeholder="books" /></Field>
          <Field label="Total quantity"><input className="field" type="number" min={0} required value={f.quantity_total} onChange={(e) => setF({ ...f, quantity_total: e.target.value })} /></Field>
          <Field label="Unit"><input className="field" maxLength={50} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} placeholder="sets, kg, hours" /></Field>
        </div>
        {isAdmin && !resource && <Field label="Held by organization" hint="Optional."><select className="field" value={f.organization_id} onChange={(e) => setF({ ...f, organization_id: e.target.value })}><option value="">Platform / partner</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>}
        {resource && <Field label="Availability"><select className="field capitalize" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option>available</option><option>unavailable</option></select></Field>}
        <Field label="Description"><textarea className="field" rows={2} maxLength={2000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.name.trim()}>{resource ? 'Save changes' : 'Add resource'}</Button></div>
      </form>
    </Modal>
  )
}

/** Resource list with add / edit / delete. Administrators see every organization's; organizations only their own. */
export default function ResourceInventory({ isAdmin = false, onChanged }) {
  const toast = useToast()
  const list = useAsync(() => api.resources(), [])
  const orgs = useAsync(() => (isAdmin ? api.adminOrganizations() : Promise.resolve([])), [isAdmin])
  const [editing, setEditing] = useState(undefined)
  const rows = list.data || []
  const remove = async (r) => {
    if (!window.confirm(`Delete the resource "${r.name}"?`)) return
    try { await api.deleteResource(r.id); toast.success('Resource deleted.'); list.reload({ silent: true }); onChanged?.() } catch (e) { toast.error(e.message) }
  }
  return (
    <>
      <div className="mb-4 flex items-center justify-between gap-3"><p className="text-sm text-ink-muted">{rows.length} resource(s). {rows.reduce((a, r) => a + r.quantity_available, 0)} unit(s) free.</p><Button onClick={() => setEditing(null)}><IconPlus className="h-4 w-4" /> Add resource</Button></div>
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading ? <TableSkeleton rows={4} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconDatabase} title="No resources yet" text="Add the materials, services or funds that can be given to children's needs." />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Resource</th>{isAdmin && <th className="px-4 py-3">Held by</th>}<th className="px-4 py-3">Category</th><th className="px-4 py-3">Stock</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id} className="border-b border-line align-top last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5"><p className="font-semibold text-ink">{r.name}</p><p className="text-xs capitalize text-ink-muted">{r.kind}{r.description ? ` · ${r.description}` : ''}</p></td>
              {isAdmin && <td className="px-4 py-3.5 text-ink-muted">{r.organization_name || 'Platform / partner'}</td>}
              <td className="px-4 py-3.5 text-ink-muted">{r.category || '–'}</td>
              <td className="px-4 py-3.5"><p className="font-semibold text-ink">{r.quantity_available} <span className="font-normal text-ink-muted">/ {r.quantity_total} {r.unit || ''}</span></p>{r.allocated > 0 && <p className="text-xs text-ink-muted">{r.allocated} allocated</p>}</td>
              <td className="px-4 py-3.5"><Pill tone={r.status === 'available' ? 'green' : 'gray'} className="capitalize">{r.status}</Pill></td>
              <td className="px-4 py-3.5 text-right"><div className="flex justify-end gap-1.5"><Button variant="ghost" className="px-2.5 py-1.5 text-xs" aria-label={`Edit ${r.name}`} onClick={() => setEditing(r)}><IconEdit className="h-3.5 w-3.5" /></Button><Button variant="danger" className="px-2.5 py-1.5 text-xs" aria-label={`Delete ${r.name}`} onClick={() => remove(r)}><IconTrash className="h-3.5 w-3.5" /></Button></div></td>
            </tr>))}</tbody></table></div></div>
      )}
      <ResourceForm open={editing !== undefined} resource={editing || null} orgs={orgs.data || []} isAdmin={isAdmin} onClose={() => setEditing(undefined)} onSaved={() => { list.reload({ silent: true }); onChanged?.() }} />
    </>
  )
}
