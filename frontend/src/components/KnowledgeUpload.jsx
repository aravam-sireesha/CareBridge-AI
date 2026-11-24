import React, { useRef, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { ACCEPT, checkFile, checkText, describeResult, isBinary, prettySize, toBase64 } from '../lib/knowledgeUpload.js'

/** Upload a .txt or .md document into the assistant's knowledge. Safe to repeat: uploading the same file again changes nothing,
 *  and an edited file replaces only the sections that changed. Text that looks like instructions to the assistant is not saved. */
export default function KnowledgeUpload({ onDone }) {
  const { user } = useAuth()
  const input = useRef(null)
  const [file, setFile] = useState(null)
  const [phase, setPhase] = useState('idle')            // idle | reading | uploading | done | error
  const [message, setMessage] = useState('')
  const [result, setResult] = useState(null)
  const scope = user?.role === 'admin' ? 'the whole platform' : 'your organization only'
  const busy = phase === 'reading' || phase === 'uploading'

  const choose = (e) => {
    const f = e.target.files?.[0] || null
    setResult(null); setFile(null)
    const problem = f ? checkFile(f) : ''
    if (problem) { setPhase('error'); setMessage(problem); if (input.current) input.current.value = ''; return }
    setFile(f); setPhase('idle'); setMessage('')
  }
  const send = async () => {
    const early = checkFile(file); if (early) { setPhase('error'); setMessage(early); return }
    setPhase('reading'); setMessage('')
    let body
    try {
      if (isBinary(file)) body = { filename: file.name, content_base64: toBase64(await file.arrayBuffer()) }        // Word and PDF travel as bytes
      else {
        const text = await file.text(); const problem = checkText(text)
        if (problem) { setPhase('error'); setMessage(problem); return }
        body = { filename: file.name, content: text }
      }
    } catch { setPhase('error'); setMessage('This file could not be read. Try saving it again.'); return }
    setPhase('uploading')
    try { const r = await api.uploadKnowledge(body); setResult(describeResult(r)); setPhase('done'); onDone?.(r) }
    catch (err) { setPhase('error'); setMessage(err.message || 'The upload failed. Nothing was changed, and you can try again.') }
  }
  const reset = () => { setFile(null); setPhase('idle'); setMessage(''); setResult(null); if (input.current) input.current.value = '' }

  return (
    <section className="card mb-5 p-4" aria-labelledby="kb-upload-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="kb-upload-title" className="font-display text-base font-semibold text-ink">Upload a document</h2>
          <p className="mt-0.5 text-sm text-ink-muted">Word (.docx), PDF, plain text (.txt) or Markdown (.md). It is split by heading and added for {scope}. Uploading the same file again changes nothing.</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="btn-soft cursor-pointer">
          Choose a file
          <input ref={input} type="file" accept={ACCEPT} className="sr-only" onChange={choose} disabled={busy} aria-describedby="kb-upload-help" />
        </label>
        {file && <span className="text-sm text-ink" data-testid="chosen">{file.name} <span className="text-ink-muted">· {prettySize(file.size)}</span></span>}
        {file && <button type="button" className="btn-primary" onClick={send} disabled={busy}>{phase === 'reading' ? 'Reading the file…' : phase === 'uploading' ? 'Uploading…' : phase === 'done' ? 'Upload again' : 'Upload'}</button>}
        {(file || phase !== 'idle') && !busy && <button type="button" className="btn-ghost" onClick={reset}>Clear</button>}
      </div>
      <p id="kb-upload-help" className="mt-2 text-xs text-ink-muted">Scanned PDFs (pictures of pages) cannot be read. Documents are treated as reference material only: nothing inside them can change how the assistant behaves.</p>

      <div aria-live="polite">
        {busy && <p className="mt-3 text-sm text-ink-muted" role="status">{phase === 'reading' ? 'Reading the file…' : 'Uploading and indexing. This can take a moment for large files.'}</p>}
        {phase === 'error' && <div role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{message}{file && <button type="button" className="ml-2 font-semibold underline" onClick={send}>Try again</button>}</div>}
        {phase === 'done' && result && (
          <div className="mt-3 rounded-xl bg-green-50 p-3 text-sm text-green-800" role="status">
            <p className="font-semibold">{result.headline}</p>
            {result.detail && <p>{result.detail}.</p>}
          </div>
        )}
        {phase === 'done' && result?.flagged.length > 0 && (
          <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800" role="alert">
            <p className="font-semibold">{result.flagged.length === 1 ? '1 section was not saved' : `${result.flagged.length} sections were not saved`}</p>
            <p>These parts look like instructions aimed at the assistant, so they were left out. Review the wording, then upload again.</p>
            <ul className="mt-1 list-disc pl-5">{result.flagged.map((f) => <li key={f.part}>Part {f.part}{f.heading ? `: “${f.heading}”` : ''} ({f.patterns.join(', ')})</li>)}</ul>
          </div>
        )}
      </div>
    </section>
  )
}
