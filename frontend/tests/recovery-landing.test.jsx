import { describe, it, expect } from 'vitest'
import { countdownText, digitsOnly, looksLikeEmail, passwordProblem } from '../src/lib/recovery.js'
import { heroActions } from '../src/lib/landingActions.js'

describe('recovery helpers', () => {
  it('keeps digits only', () => { expect(digitsOnly('Your code is 654 321')).toBe('654321'); expect(digitsOnly(null)).toBe('') })
  it('formats the countdown', () => { expect(countdownText(0)).toBe('0:00'); expect(countdownText(59.2)).toBe('1:00'); expect(countdownText(75)).toBe('1:15'); expect(countdownText(-4)).toBe('0:00') })
  it('checks the email shape', () => { expect(looksLikeEmail(' a@b.org ')).toBe(true); expect(looksLikeEmail('a@b')).toBe(false); expect(looksLikeEmail('')).toBe(false) })
  it('validates a new password the way the server does', () => {
    expect(passwordProblem('', '')).toMatch(/Enter/)
    expect(passwordProblem('short', 'short')).toMatch(/12/)
    expect(passwordProblem('a'.repeat(129), 'a'.repeat(129))).toMatch(/128/)
    expect(passwordProblem('N3w-Strong-Pass-9921', 'different')).toMatch(/match/)
    expect(passwordProblem('N3w-Strong-Pass-9921', 'N3w-Strong-Pass-9921')).toBe('')
  })
})

describe('landing hero actions', () => {
  it('shows visitors the four choices from the brief', () => {
    expect(heroActions(false).map((a) => a.label)).toEqual(['Donate Resources', 'Become a Volunteer', 'Find Support', 'Sign In'])
  })
  it('shows signed-in people only what fits their role, never Sign In', () => {
    for (const role of ['organization', 'donor', 'volunteer', 'admin']) {
      const labels = heroActions(true, role).map((a) => a.label)
      expect(labels.some((l) => /Sign In|Find Support/.test(l))).toBe(false)
      expect(labels[0]).toMatch(/dashboard/i)
    }
    expect(heroActions(true, 'admin')).toHaveLength(1)
  })
  it('sends each public role to the matching registration form', () => {
    const to = heroActions(false).map((a) => a.to)
    expect(to).toContain('/register?role=organization'); expect(to).toContain('/register?role=donor'); expect(to).toContain('/register?role=volunteer')
  })
})
