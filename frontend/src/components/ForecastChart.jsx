import React from 'react'

const W = 640, H = 260, PAD = { l: 40, r: 24, t: 16, b: 38 }

/** Monthly history as a line, the forecast as a dashed segment and point, and the empirical range (when the backend supplied one) as a vertical bar.
 *  Nothing is drawn that the data does not contain: with no `band` there is no range. */
export default function ForecastChart({ history, forecast, category }) {
  const pts = history.map((p, i) => ({ x: i, y: p.value, label: p.label }))
  const fx = pts.length
  const band = forecast.band
  const top = Math.max(1, ...pts.map((p) => p.y), forecast.value, band?.upper ?? 0)
  const max = Math.ceil(top * 1.15)
  const sx = (i) => PAD.l + (i / Math.max(1, fx)) * (W - PAD.l - PAD.r)
  const sy = (v) => H - PAD.b - (v / max) * (H - PAD.t - PAD.b)
  const ticks = [0, Math.round(max / 2), max].filter((t, i, a) => a.indexOf(t) === i)
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  const summary = `${category}: ${pts.length} periods of history, from ${pts[0]?.label} to ${last?.label}. Forecast for ${forecast.label}: ${forecast.value}${band ? `, typically between ${band.lower} and ${band.upper}` : ''}.`
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={summary}>
        {ticks.map((t) => <g key={t}><line x1={PAD.l} x2={W - PAD.r} y1={sy(t)} y2={sy(t)} stroke="currentColor" strokeOpacity="0.12" /><text x={PAD.l - 8} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="currentColor" fillOpacity="0.6">{t}</text></g>)}
        {band && <g aria-hidden="true"><line x1={sx(fx)} x2={sx(fx)} y1={sy(band.upper)} y2={sy(band.lower)} stroke="#0f766e" strokeOpacity="0.35" strokeWidth="10" strokeLinecap="round" />
          <line x1={sx(fx) - 6} x2={sx(fx) + 6} y1={sy(band.upper)} y2={sy(band.upper)} stroke="#0f766e" /><line x1={sx(fx) - 6} x2={sx(fx) + 6} y1={sy(band.lower)} y2={sy(band.lower)} stroke="#0f766e" /></g>}
        <path d={line} fill="none" stroke="#0f766e" strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p) => <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r="3" fill="#0f766e"><title>{`${p.label}: ${p.y}`}</title></circle>)}
        {last && <line x1={sx(last.x)} y1={sy(last.y)} x2={sx(fx)} y2={sy(forecast.value)} stroke="#d97706" strokeWidth="2" strokeDasharray="5 4" />}
        <circle cx={sx(fx)} cy={sy(forecast.value)} r="5" fill="#d97706"><title>{`${forecast.label} forecast: ${forecast.value}`}</title></circle>
        {[...pts.map((p) => [p.x, p.label]), [fx, forecast.label]].filter((_, i, a) => a.length <= 7 || i % Math.ceil(a.length / 6) === 0 || i === a.length - 1).map(([i, l]) => <text key={i} x={sx(i)} y={H - 14} textAnchor="middle" fontSize="11" fill="currentColor" fillOpacity="0.6">{l}</text>)}
      </svg>
      <figcaption className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-teal-700" />Recorded</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-600" />Forecast</span>
        {band && <span className="inline-flex items-center gap-1.5"><span className="h-3 w-1.5 rounded bg-teal-700/40" />Typical error range</span>}
      </figcaption>
    </figure>
  )
}
