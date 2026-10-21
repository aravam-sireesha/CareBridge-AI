import React, { useId } from 'react'

/** Smooth area/line chart for a single series. data: [{label, value}] */
export function AreaChart({ data, height = 190, format = (v) => v }) {
  const id = useId().replace(/:/g, '')
  const w = 520, h = height, pad = { l: 28, r: 28, t: 16, b: 28 }
  const max = Math.max(...data.map((d) => d.value), 1)
  const step = (w - pad.l - pad.r) / Math.max(data.length - 1, 1)
  const pts = data.map((d, i) => [pad.l + i * step, pad.t + (1 - d.value / max) * (h - pad.t - pad.b)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${pts.at(-1)[0]},${h - pad.b} L${pts[0][0]},${h - pad.b} Z`
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label="Trend chart">
      <defs>
        <linearGradient id={`a${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1E877F" stopOpacity=".38" /><stop offset="1" stopColor="#1E877F" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((t) => <line key={t} x1={pad.l} x2={w - pad.r} y1={pad.t + t * (h - pad.t - pad.b)} y2={pad.t + t * (h - pad.t - pad.b)} stroke="#DCE7E5" strokeDasharray="3 5" />)}
      <path d={area} fill={`url(#a${id})`} />
      <path d={line} fill="none" stroke="#1E877F" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p[0]} cy={p[1]} r="4.5" fill="#fff" stroke="#2468A0" strokeWidth="2.5"><title>{`${data[i].label}: ${format(data[i].value)}`}</title></circle>
          <text x={p[0]} y={h - 8} textAnchor="middle" fontSize="11" fill="#587270">{data[i].label}</text>
        </g>
      ))}
    </svg>
  )
}

export function Donut({ segments, size = 150, center }) {
  const total = segments.reduce((s, x) => s + x.value, 0)
  const r = 54, c = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg width={size} height={size} viewBox="0 0 140 140" role="img" aria-label="Distribution chart">
        <circle cx="70" cy="70" r={r} fill="none" stroke="#EAF6F4" strokeWidth="16" />
        {total > 0 && segments.map((s) => {
          const len = (s.value / total) * c
          const el = <circle key={s.label} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth="16" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" strokeLinecap="butt"><title>{`${s.label}: ${s.value}`}</title></circle>
          offset += len
          return el
        })}
        <text x="70" y="68" textAnchor="middle" className="font-display" fontSize="24" fontWeight="700" fill="#12292B">{center ?? total}</text>
        <text x="70" y="86" textAnchor="middle" fontSize="10" fill="#587270">total</text>
      </svg>
      <ul className="space-y-2 text-sm">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ background: s.color }} />
            <span className="capitalize text-ink">{s.label}</span>
            <span className="font-semibold text-ink-muted">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function HBars({ items, color = '#2468A0' }) {
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <ul className="space-y-3">
      {items.map((it, i) => (
        <li key={it.category}>
          <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-ink">{it.category}</span><span className="text-ink-muted">{it.count}</span></div>
          <div className="h-2.5 overflow-hidden rounded-full bg-teal-50">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(it.count / max) * 100}%`, background: `linear-gradient(90deg, #1E877F, ${color})`, opacity: 1 - i * 0.08 }} />
          </div>
        </li>
      ))}
    </ul>
  )
}
