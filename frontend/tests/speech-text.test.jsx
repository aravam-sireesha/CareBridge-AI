import { describe, it, expect } from 'vitest'
import { chunkForSpeech, speechText } from '../src/lib/speechText.js'

describe('speechText', () => {
  it('reads words, not Markdown symbols', () => {
    expect(speechText('## Pickup\n\n**Volunteers** collect items from the *donor*.')).toBe('Pickup. Volunteers collect items from the donor.')
  })
  it('keeps link text and drops addresses, images and code', () => {
    expect(speechText('See [the guide](https://x.org/a) now.')).toBe('See the guide now.')
    expect(speechText('![chart](a.png) Done.')).toBe('chart Done.')
    expect(speechText('Run `npm test` first.\n```\ncode here\n```\nThen stop.')).toBe('Run npm test first. Then stop.')
  })
  it('turns lists and tables into readable lines and drops citation markers', () => {
    expect(speechText('- Rice\n- Dal\n1. Oil')).toBe('Rice. Dal. Oil')
    expect(speechText('| Item | Qty |\n|---|---|\n| Rice | 40 |')).toBe('Item, Qty. Rice, 40')
    expect(speechText('Delivery needs approval [1] before pickup [2].')).toBe('Delivery needs approval before pickup.')
  })
  it('handles empty input', () => { expect(speechText('')).toBe(''); expect(speechText(null)).toBe('') })
})
describe('chunkForSpeech', () => {
  it('packs sentences up to the limit and never splits mid-sentence when it can avoid it', () => {
    const c = chunkForSpeech('One two three. Four five six. Seven eight nine.', 30)
    expect(c).toEqual(['One two three. Four five six.', 'Seven eight nine.'])
  })
  it('splits an overlong sentence at a space', () => {
    const c = chunkForSpeech('word '.repeat(100).trim() + '.', 60)
    expect(c.length > 5 && c.every((x) => x.length <= 60)).toBe(true)
    expect(c.join(' ').replace(/\s+/g, ' ')).toContain('word word word')
  })
  it('understands the Hindi/Telugu full stop and empty input', () => { expect(chunkForSpeech('पहला वाक्य। दूसरा वाक्य।', 12)).toEqual(['पहला वाक्य।', 'दूसरा वाक्य।']); expect(chunkForSpeech('')).toEqual([]) })
})
