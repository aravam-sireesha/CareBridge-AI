import { useEffect, useState } from 'react'

/** True while the media query matches. Without matchMedia (old browsers, tests) it reports `fallback`. */
export function useMediaQuery(query, fallback = false) {
  const get = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : fallback)
  const [matches, setMatches] = useState(get)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const mq = window.matchMedia(query)
    const on = () => setMatches(mq.matches)
    on()
    if (mq.addEventListener) { mq.addEventListener('change', on); return () => mq.removeEventListener('change', on) }
    mq.addListener?.(on)
    return () => mq.removeListener?.(on)
  }, [query])
  return matches
}
