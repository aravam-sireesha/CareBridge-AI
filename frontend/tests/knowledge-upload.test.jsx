import { describe, it, expect } from 'vitest'
import { MAX_CHARS, checkFile, checkText, describeResult, extensionOf, isBinary, prettySize, toBase64 } from '../src/lib/knowledgeUpload.js'

describe('knowledge upload checks', () => {
  it('accepts text and markdown, in any letter case', () => {
    for (const name of ['policy.md', 'Notes.TXT', 'guide.markdown']) expect(checkFile({ name, size: 100 })).toBe('')
  })
  it('accepts Word and PDF files up to 10 MB', () => {
    expect(checkFile({ name: 'handbook.docx', size: 5_000_000 })).toBe(''); expect(checkFile({ name: 'Guide.PDF', size: 10_000_000 })).toBe('')
    expect(checkFile({ name: 'big.pdf', size: 10_000_001 })).toMatch(/too large.*10 MB/)
  })
  it('explains legacy formats are not supported and says what to do', () => {
    expect(checkFile({ name: 'old.doc', size: 10 })).toMatch(/Old Word \(\.doc\) files are not supported/); expect(checkFile({ name: 'old.doc', size: 10 })).toMatch(/\.docx/)
    expect(checkFile({ name: 'a.xlsx', size: 10 })).toMatch(/Excel files are not supported/)
  })
  it('refuses other file types, empty files, missing files and huge text files', () => {
    expect(checkFile({ name: 'run.exe', size: 10 })).toMatch(/Only plain text/)
    expect(checkFile({ name: 'noextension', size: 10 })).toMatch(/Only plain text/)
    expect(checkFile({ name: 'a.md', size: 0 })).toMatch(/empty/)
    expect(checkFile(null)).toMatch(/Choose a file/)
    expect(checkFile({ name: 'a.md', size: MAX_CHARS * 4 + 1 })).toMatch(/too large/)
  })
  it('knows which files travel as bytes and encodes them exactly', () => {
    expect(isBinary({ name: 'a.PDF' })).toBe(true); expect(isBinary({ name: 'a.docx' })).toBe(true); expect(isBinary({ name: 'a.md' })).toBe(false)
    const bytes = new Uint8Array(70000).map((_, i) => i % 256)
    expect(toBase64(bytes.buffer)).toBe(Buffer.from(bytes).toString('base64'))          // a large file does not overflow the stack
  })
  it('checks the text itself', () => {
    expect(checkText('')).toMatch(/no readable text/); expect(checkText('   \n ')).toMatch(/no readable text/)
    expect(checkText('a'.repeat(MAX_CHARS + 1))).toMatch(/too long/)
    expect(checkText('bin\u0000ary')).toMatch(/does not look like a text file/)
    expect(checkText('A normal policy paragraph.')).toBe('')
  })
  it('helpers', () => { expect(extensionOf('a.b.MD')).toBe('.md'); expect(extensionOf('x')).toBe(''); expect(prettySize(500)).toBe('500 B'); expect(prettySize(2048)).toBe('2 KB') })
  it('describes the outcome in plain words', () => {
    expect(describeResult({ added: 2, removed: 0, unchanged: 0, flagged: [] })).toEqual({ headline: 'Knowledge updated.', detail: '2 sections added', flagged: [] })
    expect(describeResult({ added: 1, removed: 1, unchanged: 3 }).detail).toBe('1 section added, 1 old section replaced, 3 sections unchanged')
    expect(describeResult({ added: 0, removed: 0, unchanged: 3 }).headline).toBe('Nothing changed: this file was already up to date.')
  })
})
