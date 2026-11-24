import { useEffect, useRef, useState } from 'react'
import { liveStatus, onLiveStatus, subscribeLive } from '../lib/liveEvents.js'

/** Run `handler(data, type, id)` for each live event of `type` (or '*' for all). The latest handler is always used. */
export function useLiveEvent(type, handler) {
  const ref = useRef(handler)
  useEffect(() => { ref.current = handler })
  useEffect(() => subscribeLive(type, (...args) => ref.current?.(...args)), [type])
}

/** 'open' while the live connection works; anything else means callers should keep their slower polling fallback. */
export function useLiveStatus() {
  const [status, setStatus] = useState(liveStatus())
  useEffect(() => onLiveStatus(setStatus), [])
  return status
}
