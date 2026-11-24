import React from 'react'
import { LiveSourceCard } from '../LiveAnalysis.jsx'
import { IconChevronDown } from './icons.jsx'

/** Sources for a CareBridge answer, collapsed by default. General answers have none, so no panel appears. */
export default function Evidence({ sources }) {
  if (!sources) return null
  const kb = sources.knowledge || []
  const live = [...(sources.live || []), ...(sources.records || [])]
  const total = kb.length + live.length
  if (!total) return null
  return (
    <details className="ai-evidence mt-3">
      <summary>Sources ({total})<IconChevronDown className="chev h-3.5 w-3.5" /></summary>
      <div className="mt-2 space-y-2">
        {kb.map((s, i) => (
          <div key={s.id ?? i} className="ai-source">
            <p className="flex items-center gap-2 text-[13px] font-semibold"><span className="ai-source-n">{i + 1}</span>{s.title || 'Knowledge entry'}</p>
            <p className="ai-muted mt-1 text-[13px] leading-relaxed">{s.content}</p>
            {s.source && <p className="ai-faint mt-1 text-[11px]">{s.source}</p>}
          </div>
        ))}
        {live.map((s, i) => <LiveSourceCard key={`l${i}`} s={s} />)}
      </div>
    </details>
  )
}
