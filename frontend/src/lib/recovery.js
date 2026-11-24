// Small pure helpers for the password-recovery screen.
export const STEPS = ['Email', 'Code', 'New password']

/** Digits only, so "123 456" and "123-456" both work. */
export const digitsOnly = (v) => String(v ?? '').replace(/\D/g, '')

/** "0:45" style countdown text. */
export function countdownText(seconds) {
  const s = Math.max(0, Math.ceil(Number(seconds) || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Mirrors the server's minimum (12 characters) plus a matching confirmation. Returns the first problem or ''. */
export function passwordProblem(password, confirm) {
  if (!password) return 'Enter a new password.'
  if (password.length < 12) return 'Use at least 12 characters.'
  if (password.length > 128) return 'Use at most 128 characters.'
  if (confirm !== password) return 'The two passwords do not match.'
  return ''
}

export const looksLikeEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v || '').trim())
