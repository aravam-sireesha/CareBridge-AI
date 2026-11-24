import React, { useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, ConfirmDialog, ErrorState, Field, PageHeader, Section } from '../components/ui.jsx'
import { IconDownload, IconUpload } from '../components/icons.jsx'
import { saveTextFile, toCsv } from '../utils/csv.js'

const MAX_BYTES = 1_000_000
const Count = ({ n, label, tone }) => <div className="card px-4 py-3"><p className={`font-display text-2xl font-bold ${tone}`}>{n}</p><p className="text-xs text-ink-muted">{label}</p></div>

export default function BulkUpload() {
  const { user } = useAuth()
  const toast = useToast()
  const input = useRef(null)
  const isAdmin = user?.role === 'admin'
  const orgs = useAsync(() => (isAdmin ? api.adminOrganizations() : Promise.resolve(null)), [isAdmin])
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [defaultOrg, setDefaultOrg] = useState('')
  const [strict, setStrict] = useState(false)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [drag, setDrag] = useState(false)
  const orgList = Array.isArray(orgs.data) ? orgs.data : orgs.data?.items || []
  const body = () => ({ filename: file?.name, csv: text, default_organization_id: defaultOrg ? Number(defaultOrg) : null, strict })

  const pick = async (f) => {
    setPreview(null); setResult(null); setError('')
    if (!f) return
    if (!/\.csv$/i.test(f.name)) return setError('Please choose a .csv file. Excel files are not supported yet: in Excel use File > Save As > CSV.')
    if (f.size > MAX_BYTES) return setError('That file is larger than 1 MB. Split it into smaller files (up to 500 needs each).')
    if (f.size === 0) return setError('That file is empty.')
    setFile(f); setText(await f.text())
  }
  const validate = async () => {
    setBusy('validate'); setError(''); setResult(null)
    try { setPreview(await api.validateBulkNeeds(body())) } catch (e) { setError(e.message); setPreview(null) } finally { setBusy('') }
  }
  const run = async () => {
    setBusy('import'); setError('')
    try {
      const r = await api.importBulkNeeds(body())
      setResult(r); setPreview(null); setConfirm(false)
      toast.success(`${r.counts.created} need(s) created.`)
      window.dispatchEvent(new Event('cb:notifications-changed'))
    } catch (e) { setError(e.message); setConfirm(false) } finally { setBusy('') }
  }
  const errorReport = (data) => {
    const rows = data.rows.filter((r) => r.status === 'rejected' || r.status === 'skipped').map((r) => [r.row, r.line, r.status, r.reason || (r.errors || []).join(' ')])
    saveTextFile('carebridge-upload-issues.csv', toCsv(['Row', 'File line', 'Outcome', 'Reason'], rows))
  }
  const shown = result || preview
  const issues = shown ? shown.rows.filter((r) => r.status === 'rejected' || r.status === 'skipped').length : 0

  return (
    <Layout title="Needs & Bulk Upload">
      <PageHeader icon={IconUpload} title="Bulk upload needs" subtitle="Add many needs at once from a CSV file. You see exactly what will happen before anything is saved." />
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Section title="1. Prepare your file">
          <div className="card space-y-3 p-5 text-sm text-ink-muted">
            <p>Required columns: <strong className="text-ink">category</strong> and <strong className="text-ink">quantity</strong>. Optional: title, urgency (low, medium, high, critical), description, required_by (YYYY-MM-DD), location, beneficiaries{isAdmin ? ', organization_id' : ''}.</p>
            <p>Up to 500 needs and 1 MB per file. Comma-separated CSV only.</p>
            <Button variant="ghost" onClick={() => api.downloadNeedTemplate().catch((e) => toast.error(e.message))}><IconDownload className="h-4 w-4" /> Download sample CSV</Button>
          </div>
        </Section>
        <Section title="2. Choose the file">
          <div className="card p-5">
            <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]) }}
              className={`rounded-2xl border-2 border-dashed p-8 text-center transition ${drag ? 'border-teal-500 bg-teal-50' : 'border-line'}`}>
              <IconUpload className="mx-auto h-7 w-7 text-teal-700" />
              <p className="mt-2 text-sm text-ink">Drag a CSV file here, or</p>
              <Button variant="soft" className="mt-2" onClick={() => input.current?.click()}>Choose file</Button>
              <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label="CSV file" onChange={(e) => pick(e.target.files?.[0])} />
              {file && <p className="mt-3 text-sm font-semibold text-ink">{file.name} <span className="font-normal text-ink-muted">({Math.ceil(file.size / 1024)} KB)</span></p>}
            </div>
            {isAdmin && (
              <Field label="Default organization" className="mt-4" hint="Used for rows that leave organization_id empty.">
                <select className="field" value={defaultOrg} onChange={(e) => setDefaultOrg(e.target.value)}><option value="">None (every row must name one)</option>{orgList.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
              </Field>
            )}
            <label className="mt-4 flex items-start gap-2 text-sm text-ink"><input type="checkbox" className="mt-1" checked={strict} onChange={(e) => setStrict(e.target.checked)} /><span>Import nothing if any row has an error <span className="text-ink-muted">(all or nothing)</span></span></label>
            <div className="mt-4"><Button loading={busy === 'validate'} disabled={!text} onClick={validate}>Check file</Button></div>
          </div>
        </Section>
      </div>
      {orgs.error && isAdmin && <div className="mt-4"><ErrorState message={`Organizations could not be loaded. ${orgs.error}`} onRetry={orgs.reload} /></div>}
      {error && <p role="alert" className="mt-5 rounded-xl bg-red-50 p-3.5 text-sm text-red-700 ring-1 ring-red-100">{error}</p>}

      {shown && (
        <div className="mt-8">
          <h2 className="mb-3 font-display text-lg font-semibold text-teal-800">{result ? '3. Result' : '3. Preview (nothing saved yet)'}</h2>
          <div className="grid gap-3 sm:grid-cols-4">
            <Count n={shown.total} label="rows in file" tone="text-ink" />
            <Count n={result ? shown.counts.created : shown.counts.ready} label={result ? 'created' : 'ready to import'} tone="text-green-700" />
            <Count n={shown.counts.rejected} label="rejected (errors)" tone="text-red-700" />
            <Count n={shown.counts.skipped} label="skipped (duplicates)" tone="text-amber-700" />
          </div>
          {(shown.ignored_columns?.length > 0) && <p className="mt-3 text-sm text-amber-800">Ignored columns: {shown.ignored_columns.join(', ')}.</p>}
          {(shown.warnings || []).map((w) => <p key={w} role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{w}</p>)}
          <div className="card mt-4 overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-ink-muted"><tr><th className="px-4 py-3">Row</th><th className="px-4 py-3">Outcome</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">Qty</th><th className="px-4 py-3">Urgency</th><th className="px-4 py-3">Details</th></tr></thead>
            <tbody className="divide-y divide-line">{shown.rows.slice(0, 200).map((r) => (
              <tr key={r.row}><td className="px-4 py-2.5 text-ink-muted">{r.row}</td><td className="px-4 py-2.5"><StatusBadge status={r.status} /></td><td className="px-4 py-2.5">{r.preview.category || '—'}</td><td className="px-4 py-2.5">{r.preview.quantity ?? '—'}</td><td className="px-4 py-2.5 capitalize">{r.preview.urgency || '—'}</td>
                <td className="px-4 py-2.5 text-xs text-ink-muted">{r.need_id ? `Need #${r.need_id}` : r.reason || ''}</td></tr>))}
            </tbody></table></div>
          {shown.rows.length > 200 && <p className="mt-2 text-xs text-ink-muted">Showing the first 200 rows. The issue report below includes every problem row.</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            {!result && <Button disabled={!shown.counts.ready || (strict && shown.counts.rejected > 0)} onClick={() => setConfirm(true)}>Import {shown.counts.ready} need(s)</Button>}
            {issues > 0 && <Button variant="ghost" onClick={() => errorReport(shown)}><IconDownload className="h-4 w-4" /> Download issue report</Button>}
          </div>
        </div>
      )}
      <ConfirmDialog open={confirm} title="Import these needs?" text={`${preview?.counts.ready || 0} need(s) will be created. ${preview?.counts.rejected || 0} row(s) with errors and ${preview?.counts.skipped || 0} duplicate(s) will not be imported. The server checks everything again before saving.`}
        confirmLabel="Import" loading={busy === 'import'} onConfirm={run} onCancel={() => setConfirm(false)} />
    </Layout>
  )
}
