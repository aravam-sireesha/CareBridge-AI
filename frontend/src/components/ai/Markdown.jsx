import React from 'react'

// A small, dependency-free markdown renderer for assistant answers. It builds React elements directly and never sets innerHTML,
// so text from a model or a database can never inject markup. Supported: headings, paragraphs, bold/italic, `code`, fenced code,
// bullet and numbered lists, blockquotes, tables, horizontal rules, http(s) links, and [1]-style citation chips.

const INLINE_PATTERN = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))|(\[(\d{1,2})\](?!\())|(\*[^*\s][^*\n]*?\*)/g

export function renderInline(text, { citations = [], keyPrefix = 'i' } = {}) {
  const out = []
  let last = 0
  let m
  let n = 0
  const INLINE = new RegExp(INLINE_PATTERN.source, 'g')   // a fresh regex per call: the bold branch recurses, and a shared one would lose its position
  while ((m = INLINE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const key = `${keyPrefix}${n++}`
    if (m[1]) out.push(<code key={key} className="ai-md-code">{m[1].slice(1, -1)}</code>)
    else if (m[2]) out.push(<strong key={key}>{renderInline(m[2].slice(2, -2), { citations, keyPrefix: `${key}b` })}</strong>)
    else if (m[3]) out.push(<a key={key} href={m[5]} target="_blank" rel="noopener noreferrer nofollow" className="ai-md-link">{m[4]}</a>)
    else if (m[6]) {
      const idx = Number(m[7])
      const title = citations[idx - 1]
      out.push(<sup key={key} className="ai-cite" title={title ? `Source ${idx}: ${title}` : `Source ${idx}`}>{idx}</sup>)
    } else if (m[8]) out.push(<em key={key}>{m[8].slice(1, -1)}</em>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const splitRow = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
const isSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)

export function parseBlocks(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    const fence = /^```(\w*)\s*$/.exec(line)
    if (fence) {
      const body = []
      i++
      while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++])
      i++ // closing fence (or end of a still-streaming block)
      blocks.push({ type: 'code', text: body.join('\n') })
      continue
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) { blocks.push({ type: 'heading', level: Math.min(h[1].length + 1, 5), text: h[2] }); i++; continue }
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) { blocks.push({ type: 'hr' }); i++; continue }
    if (line.includes('|') && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = splitRow(line)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]))
      blocks.push({ type: 'table', head, rows })
      continue
    }
    if (/^\s*>\s?/.test(line)) {
      const q = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ''))
      blocks.push({ type: 'quote', text: q.join(' ') })
      continue
    }
    const ul = /^\s*[-*•]\s+(.*)$/
    const ol = /^\s*\d+[.)]\s+(.*)$/
    if (ul.test(line) || ol.test(line)) {
      const ordered = ol.test(line)
      const re = ordered ? ol : ul
      const items = []
      while (i < lines.length && re.test(lines[i])) items.push(re.exec(lines[i++])[1])
      blocks.push({ type: ordered ? 'ol' : 'ul', items })
      continue
    }
    const para = [line]
    i++
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*•]\s+|\s*\d+[.)]\s+|\s*>)/.test(lines[i]) && !(lines[i].includes('|') && i + 1 < lines.length && isSep(lines[i + 1]))) para.push(lines[i++])
    blocks.push({ type: 'p', text: para.join('\n') })
  }
  return blocks
}

export default function Markdown({ text, citations = [], className = '' }) {
  const blocks = React.useMemo(() => parseBlocks(text), [text])
  const inline = (t, k) => renderInline(t, { citations, keyPrefix: k })
  return (
    <div className={`ai-md ${className}`}>
      {blocks.map((b, i) => {
        const k = `b${i}`
        switch (b.type) {
          case 'heading': return React.createElement(`h${b.level}`, { key: k, className: 'ai-md-h' }, inline(b.text, k))
          case 'code': return <pre key={k} className="ai-md-pre"><code>{b.text}</code></pre>
          case 'hr': return <hr key={k} className="ai-md-hr" />
          case 'quote': return <blockquote key={k} className="ai-md-quote">{inline(b.text, k)}</blockquote>
          case 'ul': return <ul key={k} className="ai-md-ul">{b.items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ul>
          case 'ol': return <ol key={k} className="ai-md-ol">{b.items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>)}</ol>
          case 'table': return (
            <div key={k} className="ai-md-table-wrap"><table className="ai-md-table">
              <thead><tr>{b.head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
              <tbody>{b.rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
            </table></div>
          )
          default: return <p key={k} className="ai-md-p">{b.text.split('\n').flatMap((line, j, arr) => (j < arr.length - 1 ? [...inline(line, `${k}-${j}`), <br key={`${k}br${j}`} />] : inline(line, `${k}-${j}`)))}</p>
        }
      })}
    </div>
  )
}
