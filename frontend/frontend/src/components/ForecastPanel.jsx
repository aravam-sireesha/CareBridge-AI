import React from 'react'
import { Pill } from './ui.jsx'

const RISK = { high: 'red', medium: 'amber', low: 'green' }
const TREND = { rising: ['▲ rising', 'text-red-600'], falling: ['▼ falling', 'text-green-700'], steady: ['■ steady', 'text-ink-muted'] }

function Spark({ values }) {
  if (!values?.length) return null
  const w = 80, h = 24, max = Math.max(...values, 1)
  const pts = values.map((v, i) => `${values.length === 1 ? w / 2 : (i / (values.length - 1)) * w},${h - 2 - (v / max) * (h - 4)}`).join(' ')
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`History: ${values.join(', ')}`}><polyline points={pts} fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="stroke-teal-500" /></svg>
}

/** Predicted demand per category, compared with what is on hand. */
export default function ForecastPanel({ items = [], limit }) {
  const rows = limit ? items.slice(0, limit) : items
  if (!rows.length) return <p className="card p-5 text-sm text-ink-muted">Not enough need history yet. Forecasts appear once needs have been recorded over time.</p>
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {rows.map((f) => {
        const [trendLabel, trendClass] = TREND[f.trend] || TREND.steady
        return (
          <div key={f.category} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              <div><p className="text-sm font-semibold capitalize text-ink">{f.category}</p><p className={`text-xs font-semibold ${trendClass}`}>{trendLabel}</p></div>
              <Pill tone={RISK[f.risk]} className="capitalize">{f.risk} risk</Pill>
            </div>
            <div className="mt-2 flex items-end justify-between gap-3">
              <div><p className="font-display text-2xl font-bold text-teal-700">{f.forecast_units}<span className="ml-1 text-xs font-normal text-ink-muted">units next 30 days</span></p><p className="text-xs text-ink-muted">≈ {f.forecast_needs} request(s) · confidence {Math.round(f.confidence * 100)}%</p></div>
              <Spark values={f.history} />
            </div>
            <p className="mt-2 text-xs text-ink-muted">In stock {f.stock_units} · {f.matching_donors} donor(s) · {f.matching_volunteers} volunteer(s) match</p>
            {f.notes.length > 0 && <ul className="mt-2 space-y-1">{f.notes.map((n, i) => <li key={i} className="flex gap-2 text-xs text-ink-muted"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />{n}</li>)}</ul>}
            <p className="mt-2 text-[10px] text-ink-muted/80">{f.method}</p>
          </div>
        )
      })}
    </div>
  )
}
