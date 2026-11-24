import React, { useState } from 'react'
import DocumentsPanel from './DocumentsPanel.jsx'

/** Administrators choose an organization or volunteer by id and review their documents. Every file opened is recorded in the audit log. */
export default function AdminDocuments() {
  const [ownerType, setOwnerType] = useState('organization')
  const [idText, setIdText] = useState('')
  const [shown, setShown] = useState(null)
  const id = Number(idText)
  const valid = Number.isInteger(id) && id > 0
  return (
    <div className="space-y-4">
      <form className="card flex flex-wrap items-end gap-3 p-4" onSubmit={(e) => { e.preventDefault(); if (valid) setShown({ ownerType, ownerId: id }) }} aria-label="Find documents">
        <label className="text-xs font-semibold text-ink-muted">Whose documents
          <select className="field mt-1 block" value={ownerType} onChange={(e) => setOwnerType(e.target.value)}><option value="organization">Organization</option><option value="volunteer">Volunteer</option></select></label>
        <label className="text-xs font-semibold text-ink-muted">Record number
          <input className="field mt-1 block" inputMode="numeric" value={idText} onChange={(e) => setIdText(e.target.value.replace(/\D/g, '').slice(0, 9))} /></label>
        <button type="submit" className="btn-primary" disabled={!valid}>Show documents</button>
      </form>
      {shown && <DocumentsPanel key={`${shown.ownerType}-${shown.ownerId}`} ownerType={shown.ownerType} ownerId={shown.ownerId} reviewer canUpload={false} />}
    </div>
  )
}
