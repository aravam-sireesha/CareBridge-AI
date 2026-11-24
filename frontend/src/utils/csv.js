// Client-side CSV helpers. Mirrors backend/app/services/csvsafe.py: cells that start with = + - @ (or tab/CR/LF)
// get a leading apostrophe so spreadsheets show them as text instead of running them as formulas.
const TRIGGERS = ['=', '+', '-', '@', '\t', '\r', '\n']
const NOISE = /^[\s\u00a0\u200b\ufeff]+/

export function csvSafe(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  const text = Array.isArray(value) ? value.join('; ') : String(value)
  const probe = text.replace(NOISE, '')
  return probe && TRIGGERS.includes(probe[0]) ? `'${text}` : text
}

const quote = (cell) => (/[",\r\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell)

export function toCsv(headers, rows) {
  const lines = [headers, ...rows].map((r) => r.map((c) => quote(csvSafe(c))).join(','))
  return `\ufeff${lines.join('\r\n')}\r\n`
}

export function saveTextFile(name, text, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
