import { describe, it, expect } from 'vitest'
import { emptySlot, parseCapacity, slotProblems, summarize } from '../src/lib/availabilityUi.js'

describe('slot checks', () => {
  it('accepts sensible schedules', () => { expect(slotProblems([{ weekday: 5, start: '09:00', end: '13:00' }, { weekday: 0, start: '09:00', end: '12:00' }, { weekday: 0, start: '12:00', end: '14:00' }])).toEqual([]) })
  it('names the slot and the problem', () => {
    expect(slotProblems([{ weekday: 1, start: '18:00', end: '09:00' }])[0]).toMatch(/Slot 1 \(Tuesday\): the end must be after the start/)
    expect(slotProblems([{ weekday: 1, start: '09:00', end: '09:10' }])[0]).toMatch(/at least 15 minutes/)
    expect(slotProblems([{ weekday: 1, start: '', end: '09:10' }])[0]).toMatch(/enter both times/)
  })
  it('finds overlaps on the same day only', () => {
    expect(slotProblems([{ weekday: 2, start: '09:00', end: '12:00' }, { weekday: 2, start: '11:00', end: '14:00' }])[0]).toMatch(/Wednesday: two of your slots overlap/)
    expect(slotProblems([{ weekday: 2, start: '09:00', end: '12:00' }, { weekday: 3, start: '11:00', end: '14:00' }])).toEqual([])
  })
  it('limits the number of slots', () => { expect(slotProblems(Array.from({ length: 29 }, () => emptySlot(0)))[0]).toMatch(/28/) })
})
describe('summary and capacity', () => {
  it('summarises in week order', () => { expect(summarize([{ weekday: 5, start: '10:00', end: '14:00' }, { weekday: 0, start: '09:00', end: '17:00' }])).toBe('Mon 09:00-17:00, Sat 10:00-14:00'); expect(summarize([])).toBe('No schedule saved') })
  it('parses capacity', () => {
    expect(parseCapacity('')).toEqual({ ok: true, value: null }); expect(parseCapacity(' 40 ')).toEqual({ ok: true, value: 40 }); expect(parseCapacity('2.5').value).toBe(2.5)
    for (const bad of ['abc', '0', '-3', '6000']) expect(parseCapacity(bad).ok).toBe(false)
  })
})
