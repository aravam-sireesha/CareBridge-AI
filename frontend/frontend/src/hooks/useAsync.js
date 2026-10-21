import { useCallback, useEffect, useRef, useState } from 'react'

/** Load data on mount with loading / error state and a reload function. */
export function useAsync(fn, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const reload = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    setError('')
    try {
      const result = await fnRef.current()
      if (alive.current) setData(result)
      return result
    } catch (e) {
      if (alive.current) setError(e.message || 'Request failed')
      return null
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    reload()
    return () => { alive.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, setData, loading, error, reload }
}
