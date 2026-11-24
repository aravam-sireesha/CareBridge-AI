import React, { useEffect, useState } from 'react'
import StatusBadge from './StatusBadge.jsx'
import { Skeleton } from './ui.jsx'

const META_URL = '/images/hero/hero.json'

/** Validates the hero photo's metadata file. Returns null for anything that is not a real, complete record. */
export function parseHeroMeta(raw) {
  if (!raw || typeof raw !== 'object') return null
  const clean = (v) => (typeof v === 'string' && /^[\w./-]+$/.test(v) && !v.includes('..') ? v : null)
  const image = clean(raw.image)
  const alt = typeof raw.alt === 'string' ? raw.alt.trim() : ''
  if (!image || !alt) return null        // a photo without a description of it is not shown: accessibility is not optional
  return {
    image, alt, webp: clean(raw.webp), small: clean(raw.small), smallWebp: clean(raw.small_webp),
    width: Number(raw.width) || 1600, height: Number(raw.height) || 1200,
    credit: typeof raw.credit === 'string' ? raw.credit : '', license: typeof raw.license === 'string' ? raw.license : '',
    sourceUrl: /^https?:\/\//i.test(raw.source_url || '') ? raw.source_url : null
  }
}

/** The landing hero's right column. It shows the project's licensed photograph when `public/images/hero/hero.json` describes one.
 *  Otherwise it shows REAL open needs from the backend (or an honest empty state): never a stand-in picture. */
export default function HeroMedia({ needs, panelOnly = false }) {
  const [meta, setMeta] = useState(undefined)   // undefined = still checking, null = no photo configured
  useEffect(() => {
    if (panelOnly) { setMeta(null); return undefined }   // the photo is the page backdrop; this column shows only live needs
    let live = true
    fetch(META_URL, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (live) setMeta(parseHeroMeta(j)) })
      .catch(() => { if (live) setMeta(null) })   // dev servers answer unknown paths with HTML: that fails to parse and lands here
    return () => { live = false }
  }, [panelOnly])

  if (meta) {
    const base = (f) => `/images/hero/${f}`
    return (
      <figure className="lp-media">
        <picture>
          {meta.webp && <source type="image/webp" srcSet={`${meta.smallWebp ? `${base(meta.smallWebp)} 800w, ` : ''}${base(meta.webp)} ${meta.width}w`} sizes="(min-width: 1024px) 46vw, 100vw" />}
          <img src={base(meta.image)} srcSet={meta.small ? `${base(meta.small)} 800w, ${base(meta.image)} ${meta.width}w` : undefined} sizes="(min-width: 1024px) 46vw, 100vw"
            alt={meta.alt} width={meta.width} height={meta.height} fetchpriority="high" decoding="async" />
        </picture>
        {(meta.credit || meta.license) && (
          <figcaption className="lp-credit">
            {meta.sourceUrl ? <a href={meta.sourceUrl} target="_blank" rel="noopener noreferrer">{meta.credit || 'Photo source'}</a> : meta.credit}
            {meta.license ? ` · ${meta.license}` : ''}
          </figcaption>
        )}
      </figure>
    )
  }
  if (meta === undefined) return <div className="lp-media lp-media-skeleton" aria-hidden="true" />

  const items = (needs.data || []).slice(0, 3)
  return (
    <aside className="lp-panel" aria-label="Open needs right now">
      <p className="lp-panel-title">Open needs right now</p>
      {needs.loading && !needs.data ? <div className="space-y-3" aria-hidden="true">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        : needs.error ? <p className="lp-panel-empty">Needs can’t be loaded right now.</p>
        : items.length === 0 ? <p className="lp-panel-empty">No open needs from verified organizations at the moment.</p>
        : <ul className="space-y-3">{items.map((n) => (
          <li key={n.id} className="lp-panel-item">
            <div className="min-w-0"><p className="truncate font-semibold text-ink">{n.title}</p><p className="truncate text-xs text-ink-muted">{n.organization} · {n.category} · quantity {n.quantity}</p></div>
            <StatusBadge status={n.urgency} />
          </li>))}</ul>}
      <a href="#organizations" className="lp-panel-link">See all open needs</a>
    </aside>
  )
}
