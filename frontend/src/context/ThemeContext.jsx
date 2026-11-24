import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const KEY = 'cb_theme'
const MODES = ['light', 'dark', 'system']

const systemPrefersDark = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
const readMode = () => { try { const m = localStorage.getItem(KEY); return MODES.includes(m) ? m : 'system' } catch { return 'system' } }

function applyTheme(mode) {
  const dark = mode === 'dark' || (mode === 'system' && systemPrefersDark())
  const root = document.documentElement
  root.classList.toggle('dark', dark)
  root.style.colorScheme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0A1415' : '#0B5654')
  return dark
}

// Safe default so components (and tests) work even without the provider.
const ThemeContext = createContext({ mode: 'system', resolved: 'light', setMode: () => {}, toggle: () => {} })

export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(readMode)
  const [resolved, setResolved] = useState(() => (applyTheme(readMode()) ? 'dark' : 'light'))

  const setMode = useCallback((m) => {
    if (!MODES.includes(m)) return
    try { localStorage.setItem(KEY, m) } catch { /* private mode: still apply for this session */ }
    setModeState(m)
  }, [])

  useEffect(() => { setResolved(applyTheme(mode) ? 'dark' : 'light') }, [mode])

  // Follow the operating system while "System" is selected.
  useEffect(() => {
    if (mode !== 'system' || !window.matchMedia) return undefined
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setResolved(applyTheme('system') ? 'dark' : 'light')
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [mode])

  const toggle = useCallback(() => setMode(resolved === 'dark' ? 'light' : 'dark'), [resolved, setMode])
  const value = useMemo(() => ({ mode, resolved, setMode, toggle }), [mode, resolved, setMode, toggle])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)
