import React, { useEffect, useState } from 'react'
import { parseHeroMeta } from './HeroMedia.jsx'

const META_URL = '/images/hero/hero.json'

/** The licensed hero photograph's description, or null when none has been added, or undefined while checking. */
export function useHeroMeta() {
  const [meta, setMeta] = useState(undefined)
  useEffect(() => {
    let live = true
    fetch(META_URL, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (live) setMeta(parseHeroMeta(j)) })
      .catch(() => { if (live) setMeta(null) })
    return () => { live = false }
  }, [])
  return meta
}

/** A fixed, full-viewport layer behind the landing page. Later sections are opaque, so they scroll OVER it.
 *  It is a real fixed element rather than `background-attachment: fixed`, which many phones ignore or render badly.
 *  With no licensed photograph the layer is a plain deep-teal surface: never a stand-in picture. Decorative (alt="");
 *  the photo credit is printed in the hero by <HeroCredit>. */
export default function HeroBackdrop({ meta }) {
  const base = (f) => `/images/hero/${f}`
  return (
    <div className="lp-backdrop" aria-hidden="true">
      {meta && (
        <picture>
          {meta.webp && <source type="image/webp" srcSet={`${meta.smallWebp ? `${base(meta.smallWebp)} 800w, ` : ''}${base(meta.webp)} ${meta.width}w`} sizes="100vw" />}
          <img src={base(meta.image)} srcSet={meta.small ? `${base(meta.small)} 800w, ${base(meta.image)} ${meta.width}w` : undefined} sizes="100vw"
            alt="" width={meta.width} height={meta.height} fetchpriority="high" decoding="async" />
        </picture>
      )}
      <div className="lp-backdrop-shade" />
    </div>
  )
}

/** Credit and licence for the photograph, shown in the hero as the licence requires. Renders nothing without a photo. */
export function HeroCredit({ meta }) {
  if (!meta || !(meta.credit || meta.license)) return null
  return (
    <p className="lp-backdrop-credit">
      {meta.sourceUrl ? <a href={meta.sourceUrl} target="_blank" rel="noopener noreferrer">{meta.credit || 'Photo source'}</a> : meta.credit}
      {meta.license ? ` · ${meta.license}` : ''}
    </p>
  )
}
