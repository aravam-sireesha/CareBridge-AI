import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, tokenStore } from '../api/client.js'

const AuthContext = createContext(null)

const readStoredUser = () => {
  try { return JSON.parse(localStorage.getItem('cb_user') || 'null') } catch { return null }
}

const toProfile = (u) => ({
  id: u.id, email: u.email, role: u.role,
  name: u.display_name || u.email, organization_id: u.organization_id ?? null,
  donor_id: u.donor_id ?? null, volunteer_id: u.volunteer_id ?? null
})

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (tokenStore.get() ? readStoredUser() : null))
  const [ready, setReady] = useState(!tokenStore.get())

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const finishLogin = useCallback((data) => {
    tokenStore.set(data.access_token)
    const profile = toProfile(data.user)
    localStorage.setItem('cb_user', JSON.stringify(profile))
    setUser(profile)
    return profile
  }, [])
  const login = useCallback(async (email, password) => finishLogin(await api.login(email.trim(), password)), [finishLogin])
  // Returns the profile, or { mfa_required, mfa_token } when the account uses two-step verification.
  const adminLogin = useCallback(async (email, password) => {
    const data = await api.adminLogin(email.trim(), password)
    return data.mfa_required ? { mfa_required: true, mfa_token: data.mfa_token } : finishLogin(data)
  }, [finishLogin])
  const adminVerify = useCallback(async (mfaToken, code) => finishLogin(await api.adminLoginVerify(mfaToken, code.trim())), [finishLogin])

  // Validate the stored token once at start-up so a stale session never shows a broken app.
  useEffect(() => {
    if (!tokenStore.get()) return
    api.me()
      .then((u) => { const p = toProfile(u); localStorage.setItem('cb_user', JSON.stringify(p)); setUser(p) })
      .catch((e) => { if (e.status === 401 || e.status === 404) logout() })
      .finally(() => setReady(true))
  }, [logout])

  useEffect(() => {
    const onUnauthorized = () => logout()
    window.addEventListener('cb:unauthorized', onUnauthorized)
    return () => window.removeEventListener('cb:unauthorized', onUnauthorized)
  }, [logout])

  const value = useMemo(() => ({ user, ready, login, adminLogin, adminVerify, logout, isAuthenticated: !!user }), [user, ready, login, adminLogin, adminVerify, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** Logs out and sends the person to the right sign-in page (administrators have their own). */
export function useLogout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return useCallback(async () => {
    const target = user?.role === 'admin' ? '/admin/login' : '/login'
    // Ask the server to reject this token from now on. A slow or failed call must never keep someone signed in.
    try { await Promise.race([api.adminLogout(), new Promise((resolve) => setTimeout(resolve, 2000))]) } catch { /* sign out anyway */ }
    logout()
    navigate(target, { replace: true })
  }, [user, logout, navigate])
}
