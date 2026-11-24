// The server's refusal text when a pending account tries to sign in (backend/app/routers/auth.py VERIFY_PHONE_FIRST).
export const needsPhoneVerification = (message) => /verify your mobile number/i.test(String(message || ''))
export const phoneVerifyLink = (email) => `/verify-phone${email ? `?email=${encodeURIComponent(email)}` : ''}`

// Dial codes offered at sign-up. The server validates the final number (Indian numbers: 10 digits starting 6-9).
export const COUNTRY_CODES = [
  { code: '+91', label: 'India (+91)' }, { code: '+1', label: 'USA / Canada (+1)' }, { code: '+44', label: 'United Kingdom (+44)' },
  { code: '+971', label: 'UAE (+971)' }, { code: '+65', label: 'Singapore (+65)' }, { code: '+61', label: 'Australia (+61)' },
  { code: '+49', label: 'Germany (+49)' }, { code: '+977', label: 'Nepal (+977)' }, { code: '+880', label: 'Bangladesh (+880)' }, { code: '+94', label: 'Sri Lanka (+94)' }
]
