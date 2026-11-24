import { describe, it, expect } from 'vitest'
import { buildPayload, groupOf, journeyProgress, localToUtcIso, fieldFor } from '../src/lib/deliveryUi.js'

describe('buildPayload', () => {
  it('requires a reason of at least 3 characters', () => {
    expect(buildPayload('reject', ['reason'], { reason: ' ' }).ok).toBe(false)
    expect(buildPayload('reject', ['reason'], { reason: 'Too high' })).toEqual({ ok: true, payload: { reason: 'Too high' }, errors: {} })
  })
  it('turns ids and quantities into integers and rejects junk', () => {
    expect(buildPayload('offer', ['volunteer_id'], { volunteer_id: '9' }).payload).toEqual({ volunteer_id: 9 })
    expect(buildPayload('offer', ['volunteer_id'], { volunteer_id: '' }).ok).toBe(false)
    expect(buildPayload('confirm_receipt', ['received_quantity'], { received_quantity: '0' }).payload.received_quantity).toBe(0)
    for (const bad of ['', 'abc', '-1', '2.5']) expect(buildPayload('confirm_receipt', ['received_quantity'], { received_quantity: bad }).ok).toBe(false)
  })
  it('proof of delivery is required for deliver', () => {
    expect(buildPayload('deliver', ['note'], { note: 'ok' }).ok).toBe(false)
    expect(buildPayload('deliver', ['note'], { note: 'Handed to the warden' }).payload.note).toBe('Handed to the warden')
  })
  it('a receipt with a different quantity needs a note, and the note is actually sent (regression)', () => {
    const miss = buildPayload('confirm_receipt', ['received_quantity'], { received_quantity: '30', __expected: 40 })
    expect(miss.ok).toBe(false); expect(miss.errors.note).toMatch(/explain/)
    const ok = buildPayload('confirm_receipt', ['received_quantity'], { received_quantity: '30', note: ' Ten bags torn ', __expected: 40 })
    expect(ok.ok).toBe(true); expect(ok.payload).toEqual({ received_quantity: 30, note: 'Ten bags torn' })
    expect(buildPayload('confirm_receipt', ['received_quantity'], { received_quantity: '40', __expected: 40 }).payload).toEqual({ received_quantity: 40 })
    expect(JSON.stringify(ok.payload)).not.toContain('__expected')
  })
  it('pickup time becomes a UTC instant', () => {
    expect(localToUtcIso('2026-10-30T09:30')).toMatch(/^2026-10-30T\d\d:\d\d:00\.000Z$/)
    expect(localToUtcIso('nope')).toBe(null)
    expect(buildPayload('schedule_pickup', ['pickup_at'], { pickup_at: '' }).ok).toBe(false)
  })
  it('resolution must be one of the offered choices', () => {
    expect(buildPayload('resolve_exception', ['resolution'], { resolution: 'delete' }).ok).toBe(false)
    expect(buildPayload('resolve_exception', ['resolution'], { resolution: 'resume', note: 'Fixed' }).payload).toEqual({ resolution: 'resume', note: 'Fixed' })
  })
})

describe('grouping and progress', () => {
  it('puts deliveries waiting on the person first, finished ones last', () => {
    expect(groupOf({ status: 'offered', allowed_actions: [{ action: 'accept' }] })).toBe('action')
    expect(groupOf({ status: 'in_transit', allowed_actions: [] })).toBe('progress')
    expect(groupOf({ status: 'receipt_confirmed', allowed_actions: [] })).toBe('done')
    expect(groupOf({ status: 'cancelled', allowed_actions: [] })).toBe('done')
  })
  it('progress never claims steps for cancelled, rejected or exception deliveries', () => {
    for (const s of ['cancelled', 'rejected', 'exception']) expect(journeyProgress(s)).toBe(-1)
    expect(journeyProgress('approved')).toBe(1); expect(journeyProgress('receipt_confirmed')).toBe(6)
  })
  it('action-specific labels override the defaults', () => {
    expect(fieldFor('deliver', 'note').label).toBe('Proof of delivery')
    expect(fieldFor('reject', 'reason').label).toBe('Reason')
  })
})
