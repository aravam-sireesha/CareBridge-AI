import React, { useId } from 'react'

/** CareBridge AI logo: a heart held by a bridge arch, with a small AI spark. */
export function LogoMark({ size = 40, className = '' }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} role="img" aria-label="CareBridge AI logo">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#115E59" />
          <stop offset=".55" stopColor="#0F766E" />
          <stop offset="1" stopColor="#2563EB" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill={`url(#g${id})`} />
      <path d="M32 44.5C21 37.5 15.5 31.8 15.5 25.6c0-4.4 3.4-7.6 7.6-7.6 3.6 0 6.3 2 8.9 5.2 2.6-3.2 5.3-5.2 8.9-5.2 4.2 0 7.6 3.2 7.6 7.6 0 6.2-5.5 11.9-16.5 18.9z" fill="#fff" />
      <path d="M10 52c7-8.5 15-12 22-12s15 3.5 22 12" fill="none" stroke="#F6C76B" strokeWidth="3.4" strokeLinecap="round" />
      <path d="M48 9l1.5 3.6L53 14l-3.5 1.4L48 19l-1.5-3.6L43 14l3.5-1.4z" fill="#F6C76B" />
    </svg>
  )
}

export default function Logo({ size = 40, light = false, showTagline = false, compact = false, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} />
      <span className={compact ? 'sr-only' : 'leading-none'}>
        <span className={`block font-display text-[1.15em] font-bold tracking-tight ${light ? 'text-white' : 'text-teal-800'}`} style={{ fontSize: size * 0.5 }}>
          CareBridge <span className={light ? 'text-amber-100' : 'text-sky-600'}>AI</span>
        </span>
        {showTagline && (
          <span className={`mt-1 block text-[11px] font-medium ${light ? 'text-white/75' : 'text-ink-muted'}`}>
            Connecting Hearts, Fulfilling Needs.
          </span>
        )}
      </span>
    </span>
  )
}
