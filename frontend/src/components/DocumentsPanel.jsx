import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { KIND_LABELS, REVIEW_TEXT, checkFile, fileToBase64, formatSize } from '../lib/documents.js'

const TONE = { pending: 'bg-amber-50 text-amber-800', approved: 'bg-green-50 text-green-700', rejected: 'bg-red-50 text-red-700' }

/** Documents for one record (an organization, a volunteer). "Uploaded" and "verified" are different: every file is reviewed by an administrator,
 *  and approving a file does not by itself verify anyone. `reviewer` adds the administrator's Accept / Reject controls. */
export default function DocumentsPanel({ ownerType, ownerId, reviewer = false, canUpload = true }) {
  const kinds = KIND_LABELS[ownerType] || {}
  const [docs, setDocs] = useState(null)
  const [error, setError] = useState('')
  const [kind, setKind] = useState(Object.keys(kinds)[0] || '')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState({})
  const file = useRef(null)

  const load = useCallback(async () => {
    try { setDocs((await api.documentsList(ownerType, ownerId)).documents || []); setError('') } catch (e) { setError(e.message); setDocs([]) }
  }, [ownerType, ownerId])
  useEffect(() => { setDocs(null); load() }, [load])

  const run = async (fn) => { setBusy(true); setError(''); try { await fn(); await load() } catch (e) { setError(e.message) } finally { setBusy(false) } }

  const upload = (e) => {
    e.preventDefault()
    const f = file.current?.files?.[0]
    const problem = checkFile(f)
    if (problem) { setError(problem); return }
    run(async () => {
      await api.documentUpload({ owner_type: ownerType, owner_id: ownerId, kind, filename: f.name, content_type: f.type, data_base64: await fileToBase64(f) })
      file.current.value = ''
    })
  }
  const open = (d) => run(async () => { const { url } = await api.documentUrl(d.id); window.open(url, '_blank', 'noopener,noreferrer') })     // a short-lived link; opening is logged
  const remove = (d) => run(() => api.documentDelete(d.id))
  const decide = (d, decision) => {
    const reason = (note[d.id] || '').trim()
    if (decision === 'rejected' && !reason) { setError('Please say why the document is not accepted.'); return }
    run(() => api.documentReview(d.id, decision, reason || undefined))
  }

  return (
    <div className="card space-y-4 p-4 text-sm text-ink">
      <p className="text-xs text-ink-muted">Documents are kept privately and shown only through short-lived links. Uploading a document does not verify anyone: an administrator reviews each one{reviewer ? ', and accepting a document does not by itself verify the organization or volunteer.' : '.'}</p>
      {canUpload && Object.keys(kinds).length > 0 && (
        <form onSubmit={upload} className="flex flex-wrap items-end gap-3" aria-label="Upload a document">
          <label className="text-xs font-semibold text-ink-muted">Type
            <select className="field mt-1 block" value={kind} onChange={(e) => setKind(e.target.value)}>{Object.entries(kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="text-xs font-semibold text-ink-muted">File (PDF, JPEG, PNG or WebP, up to 5 MB)
            <input ref={file} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" className="field mt-1 block" /></label>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Working…' : 'Upload'}</button>
        </form>
      )}
      {error && <p className="text-red-700" role="alert">{error}</p>}
      {docs === null ? <p role="status">Loading documents…</p> : docs.length === 0 ? <p className="text-ink-muted">No documents yet.</p> : (
        <ul className="divide-y divide-line">
          {docs.map((d) => (
            <li key={d.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0"><p className="font-semibold">{kinds[d.kind] || d.kind}</p><p className="truncate text-xs text-ink-muted">{d.original_name} · {formatSize(d.size_bytes)}</p></div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${TONE[d.review_status] || ''}`}>{REVIEW_TEXT[d.review_status] || d.review_status}</span>
              </div>
              {d.review_note && <p className="text-xs text-ink-muted">Reviewer\u2019s note: {d.review_note}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="btn-ghost" onClick={() => open(d)} disabled={busy}>Open</button>
                {d.review_status !== 'approved' && !reviewer && <button type="button" className="btn-ghost" onClick={() => remove(d)} disabled={busy}>Remove</button>}
                {reviewer && (
                  <>
                    <input aria-label={`Reason for document ${d.id}`} className="field" placeholder="Reason (needed to reject)" value={note[d.id] || ''} onChange={(e) => setNote((n) => ({ ...n, [d.id]: e.target.value }))} maxLength={300} />
                    <button type="button" className="btn-primary" onClick={() => decide(d, 'approved')} disabled={busy || d.review_status === 'approved'}>Accept</button>
                    <button type="button" className="btn-ghost" onClick={() => decide(d, 'rejected')} disabled={busy}>Reject</button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
