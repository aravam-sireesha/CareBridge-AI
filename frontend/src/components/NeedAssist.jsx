import React, { useState } from 'react'
import { api } from '../api/client.js'
import { IconSparkle } from './ai/icons.jsx'

const FIELDS = [['category', 'Category'], ['urgency', 'Urgency'], ['title', 'Title'], ['description', 'Description']]

/** Optional helper for the need form. The person describes the need in their own words; suggestions appear in a separate panel and
 *  nothing reaches the form until they press "Use" on that one suggestion. Suggestions never submit anything. */
export default function NeedAssist({ onUse }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [used, setUsed] = useState({})

  const ask = async () => {
    setBusy(true); setError(null); setResult(null); setUsed({})
    try { setResult(await api.needAssist(text.trim())) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const sug = result?.suggestions
  const use = (key, value) => { onUse(key, value); setUsed((u) => ({ ...u, [key]: true })) }

  return (
    <details className="rounded-xl border border-line p-3">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-ink"><IconSparkle className="h-4 w-4 text-teal-700" />Get help filling this in <span className="text-xs font-normal text-ink-muted">(optional)</span></summary>
      <div className="mt-3 space-y-3">
        <label className="block text-xs font-medium text-ink-muted" htmlFor="need-assist-text">Describe the need in your own words</label>
        <textarea id="need-assist-text" rows={3} maxLength={2000} className="field" value={text} onChange={(e) => setText(e.target.value)} placeholder="For example: We urgently need 40 winter blankets for the children by Friday." />
        <button type="button" className="btn-soft" onClick={ask} disabled={busy || text.trim().length < 10}>{busy ? 'Thinking…' : 'Suggest details'}</button>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        {sug && (
          <div className="space-y-2 rounded-lg bg-bg p-3" aria-label="Suggestions">
            <p className="text-xs text-ink-muted">{result.source === 'model' ? 'Suggested by the language model. Check each one before using it.' : result.notice}</p>
            {FIELDS.filter(([k]) => sug[k]).map(([k, label]) => (
              <div key={k} className="flex items-start justify-between gap-3 border-t border-line pt-2 text-sm first:border-0 first:pt-0">
                <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{label}</p><p className="break-words text-ink">{sug[k]}</p></div>
                <button type="button" className="btn-soft shrink-0" disabled={used[k]} onClick={() => use(k, sug[k])} aria-label={`Use suggested ${label.toLowerCase()}`}>{used[k] ? 'Used' : 'Use'}</button>
              </div>
            ))}
            {sug.missing?.length > 0 && <div className="border-t border-line pt-2 text-sm"><p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Still missing</p><ul className="mt-1 list-disc pl-5 text-ink">{sug.missing.map((m) => <li key={m}>{m}</li>)}</ul></div>}
            <button type="button" className="text-xs font-semibold text-ink-muted hover:underline" onClick={() => setResult(null)}>Dismiss suggestions</button>
          </div>
        )}
      </div>
    </details>
  )
}
