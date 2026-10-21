import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, useLogout } from '../context/AuthContext.jsx'
import { useTheme } from '../context/ThemeContext.jsx'
import StatusBadge from './StatusBadge.jsx'
import { IconLogout, IconMoon, IconMonitor, IconSettings, IconSun, IconUser } from './icons.jsx'

export const THEME_OPTIONS = [
  { key: 'light', label: 'Light', icon: IconSun },
  { key: 'dark', label: 'Dark', icon: IconMoon },
  { key: 'system', label: 'System', icon: IconMonitor }
]

/** Segmented Light / Dark / System control, shared by the profile menu and Settings. */
export function ThemeSwitch({ className = '' }) {
  const { mode, setMode } = useTheme()
  return (
    <div role="radiogroup" aria-label="Theme" className={`grid grid-cols-3 gap-1 rounded-xl bg-teal-50 p-1 ${className}`}>
      {THEME_OPTIONS.map(({ key, label, icon: Icon }) => (
        <button key={key} type="button" role="radio" aria-checked={mode === key} onClick={() => setMode(key)}
          className={`flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold transition ${mode === key ? 'bg-white text-teal-700 shadow-card' : 'text-ink-muted hover:text-teal-700'}`}>
          <Icon className="h-3.5 w-3.5" />{label}
        </button>
      ))}
    </div>
  )
}

/** Header sun/moon button: flips between light and dark. */
export function ThemeToggle({ className = 'rounded-xl p-2.5 text-ink-muted transition hover:bg-teal-50 hover:text-teal-700' }) {
  const { resolved, toggle } = useTheme()
  const dark = resolved === 'dark'
  return (
    <button type="button" onClick={toggle} title={dark ? 'Switch to light mode' : 'Switch to dark mode'} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className={className}>
      {dark ? <IconSun /> : <IconMoon />}
    </button>
  )
}

export default function ProfileMenu() {
  const { user } = useAuth()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const name = user?.name || 'User'
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label="Open profile menu"
        className="flex items-center gap-2.5 rounded-full bg-white py-1 pl-1 pr-3 ring-1 ring-line transition hover:ring-teal-300">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-teal-500 to-sky-600 text-sm font-bold text-white">{name.charAt(0).toUpperCase()}</span>
        <span className="hidden max-w-[10rem] truncate text-sm font-semibold text-ink sm:block">{name}</span>
      </button>
      {open && (
        <div role="menu" className="animate-pop absolute right-0 top-full z-50 mt-2 w-72 rounded-2xl border border-line bg-white p-3 shadow-lift">
          <div className="flex items-center gap-3 px-1 pb-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-gradient-to-br from-teal-500 to-sky-600 font-display text-lg font-bold text-white">{name.charAt(0).toUpperCase()}</span>
            <div className="min-w-0"><p className="truncate text-sm font-semibold text-ink">{name}</p><p className="truncate text-xs text-ink-muted">{user?.email}</p><div className="mt-1"><StatusBadge status={user?.role} /></div></div>
          </div>
          <div className="space-y-0.5 border-t border-line pt-2">
            <Link role="menuitem" to="/settings?tab=profile" onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-teal-50 hover:text-teal-700"><IconUser className="h-4 w-4" />My profile</Link>
            <Link role="menuitem" to="/settings?tab=appearance" onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-teal-50 hover:text-teal-700"><IconSettings className="h-4 w-4" />Settings</Link>
          </div>
          <div className="mt-2 border-t border-line pt-3"><p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/70">Theme</p><ThemeSwitch /></div>
          <button role="menuitem" type="button" onClick={() => { setOpen(false); logout() }}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-sm font-semibold text-red-600 transition hover:bg-red-100"><IconLogout className="h-4 w-4" />Log out</button>
        </div>
      )}
    </div>
  )
}
