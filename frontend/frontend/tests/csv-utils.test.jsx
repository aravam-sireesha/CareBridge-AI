import { describe, it, expect } from 'vitest'
import { csvSafe, toCsv } from '../src/utils/csv.js'

describe('csv utils', () => {
  it('defuses formula payloads, including hidden leading characters', () => {
    for (const p of ['=1+1', '+SUM(A1)', '-2+3', '@SUM(1,1)', '\t=1', '  =1+1', '\u00a0=1', '\u200b=1']) expect(csvSafe(p)).toBe(`'${p}`)
  })
  it('leaves ordinary text and numbers alone', () => {
    expect(csvSafe('Hope Home')).toBe('Hope Home'); expect(csvSafe(-5)).toBe('-5'); expect(csvSafe(null)).toBe(''); expect(csvSafe(['a', 'b'])).toBe('a; b')
  })
  it('quotes cells that contain commas, quotes or newlines', () => {
    expect(toCsv(['a', 'b'], [['x,y', 'say "hi"'], ['l1\nl2', '=evil()']])).toBe('\ufeffa,b\r\n"x,y","say ""hi"""\r\n"l1\nl2",\'=evil()\r\n')
  })
})
