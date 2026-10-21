import { useEffect, useState } from 'react'

/** Returns `value` after it has stopped changing for `delay` ms (keeps search boxes from calling the API on every key). */
export function useDebounced(value, delay = 350) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), delay); return () => clearTimeout(t) }, [value, delay])
  return v
}
