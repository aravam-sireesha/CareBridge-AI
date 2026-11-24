import { describe, expect, it } from 'vitest'
import { COUNTRY_CODES, needsPhoneVerification, phoneVerifyLink } from '../src/lib/phoneVerification.js'
import { needsVerification } from '../src/lib/emailVerification.js'

describe('phone verification helpers', () => {
  it('recognises the server refusal for an unverified mobile number, and not the e-mail one', () => {
    expect(needsPhoneVerification('Please verify your mobile number before signing in.')).toBe(true)
    expect(needsPhoneVerification('Please verify your email address before signing in.')).toBe(false)
    expect(needsVerification('Please verify your mobile number before signing in.')).toBe(false)
    expect(needsPhoneVerification(undefined)).toBe(false)
  })

  it('builds a verify link that carries only the e-mail address (never the phone number)', () => {
    expect(phoneVerifyLink('a+b@x.org')).toBe('/verify-phone?email=a%2Bb%40x.org')
    expect(phoneVerifyLink('')).toBe('/verify-phone')
  })

  it('offers India first, with unique dial codes', () => {
    expect(COUNTRY_CODES[0].code).toBe('+91')
    expect(new Set(COUNTRY_CODES.map((c) => c.code)).size).toBe(COUNTRY_CODES.length)
  })
})
