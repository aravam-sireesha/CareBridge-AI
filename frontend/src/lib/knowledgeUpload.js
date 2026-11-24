// Checks done in the browser before a knowledge file is sent. The SERVER repeats every check (extension, size, binary content,
// instruction-like text); these exist so people get an instant, specific message instead of a failed upload.
export const MAX_CHARS = 1_000_000
export const MAX_BYTES = 10_000_000   // Word and PDF files
export const ACCEPT = '.txt,.md,.markdown,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const TEXT_EXTENSIONS = ['.txt', '.md', '.markdown']
const BINARY_EXTENSIONS = ['.docx', '.pdf']
const UNSUPPORTED = { '.doc': 'Old Word (.doc)', '.rtf': 'Rich Text', '.odt': 'OpenDocument', '.xls': 'Excel', '.xlsx': 'Excel', '.ppt': 'PowerPoint', '.pptx': 'PowerPoint' }

export const isBinary = (file) => BINARY_EXTENSIONS.includes(extensionOf(file && file.name))
export const extensionOf = (name) => { const m = /\.[A-Za-z0-9]+$/.exec(String(name || '')); return m ? m[0].toLowerCase() : '' }
export const prettySize = (bytes) => (bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1048576).toFixed(1)} MB`)

/** Returns '' when the file may be uploaded, otherwise a sentence that says what to do. */
export function checkFile(file) {
  if (!file) return 'Choose a file first.'
  const ext = extensionOf(file.name)
  if (UNSUPPORTED[ext]) return `${UNSUPPORTED[ext]} files are not supported. Save the document as Word (.docx), PDF, plain text (.txt) or Markdown (.md) and upload that.`
  if (![...TEXT_EXTENSIONS, ...BINARY_EXTENSIONS].includes(ext)) return 'Only plain text (.txt), Markdown (.md), Word (.docx) and PDF files can be uploaded.'
  if (file.size === 0) return 'This file is empty.'
  if (BINARY_EXTENSIONS.includes(ext) && file.size > MAX_BYTES) return `This file is too large (${prettySize(file.size)}). The limit is 10 MB.`
  if (!BINARY_EXTENSIONS.includes(ext) && file.size > MAX_CHARS * 4) return `This file is too large (${prettySize(file.size)}). The limit is about 1 million characters.`
  return ''
}

/** After reading: problems that need the text itself. */
export function checkText(text) {
  if (typeof text !== 'string' || !text.trim()) return 'This file has no readable text.'
  if (text.length > MAX_CHARS) return `This file is too long (${text.length.toLocaleString('en-IN')} characters). The limit is ${MAX_CHARS.toLocaleString('en-IN')}.`
  if (text.includes('\u0000')) return 'This does not look like a text file.'
  return ''
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`
/** Turns the server's answer into plain sentences. */
export function describeResult(r) {
  const parts = []
  if (r.added) parts.push(`${plural(r.added, 'section', 'sections')} added`)
  if (r.removed) parts.push(`${plural(r.removed, 'old section', 'old sections')} replaced`)
  if (r.unchanged) parts.push(`${plural(r.unchanged, 'section', 'sections')} unchanged`)
  const headline = !r.added && !r.removed ? 'Nothing changed: this file was already up to date.' : 'Knowledge updated.'
  return { headline, detail: parts.join(', '), flagged: r.flagged || [] }
}

/** ArrayBuffer -> base64 text, in slices so a large file does not overflow the call stack. */
export function toBase64(buffer) {
  const bytes = new Uint8Array(buffer); let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary)
}
