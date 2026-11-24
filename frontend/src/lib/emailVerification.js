// The server's refusal text when a pending account tries to sign in (backend/app/routers/auth.py VERIFY_FIRST).
export const needsVerification = (message) => /verify your email address/i.test(String(message || ''))
export const verifyLink = (email) => `/verify-email${email ? `?email=${encodeURIComponent(email)}` : ''}`
