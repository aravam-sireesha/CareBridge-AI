// Turns an assistant answer (Markdown) into text that sounds right when read aloud, in pieces small enough for speech engines.
const LINK = /!?\[([^\]]*)\]\([^)]*\)/g

/** Markdown -> plain sentences. Tables become comma-separated lines; links keep their words, not their addresses. */
export function speechText(markdown) {
  return String(markdown || '')
    .replace(/```[\s\S]*?```/g, ' ')                     // code blocks are not read aloud
    .replace(/`([^`]*)`/g, '$1')
    .replace(LINK, '$1')
    .replace(/<[^>]+>/g, ' ')
    .replace(/^\s*\|?\s*:?-{2,}:?(\s*\|\s*:?-{2,}:?)*\s*\|?\s*$/gm, '')   // table divider rows
    .replace(/[ \t]*\|[ \t]*/g, ', ')                 // table cells (spaces and tabs only, so rows stay on their own lines)
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')                   // heading marks
    .replace(/^\s*[-*+]\s+/gm, '')                        // bullet marks
    .replace(/^\s*\d+[.)]\s+/gm, '')
    .replace(/\[(\d{1,2})\]|【\d+】/g, '')                  // citation markers such as [1]
    .replace(/[*_~]{1,3}([^*_~\n]+)[*_~]{1,3}/g, '$1')
    .replace(/[ \t]+/g, ' ')
    .replace(/(^|\n),\s*/g, '$1').replace(/,\s*(\n|$)/g, '$1')
    .replace(/\n{2,}/g, '. ').replace(/\n/g, '. ')
    .replace(/\.(\s*\.)+/g, '.').replace(/\s+([.,;!?])/g, '$1').trim()
}

/** Split into chunks of at most `max` characters at sentence ends (some engines stop speaking long utterances). */
export function chunkForSpeech(text, max = 220) {
  const sentences = String(text || '').match(/[^.!?।]+[.!?।]*\s*/g) || []
  const chunks = []; let cur = ''
  for (const raw of sentences) {
    let s = raw.trim(); if (!s) continue
    while (s.length > max) { const cut = s.lastIndexOf(' ', max); const at = cut > max / 2 ? cut : max; if (cur) { chunks.push(cur); cur = '' } chunks.push(s.slice(0, at).trim()); s = s.slice(at).trim() }
    if (cur && (cur + ' ' + s).length > max) { chunks.push(cur); cur = s } else cur = cur ? `${cur} ${s}` : s
  }
  if (cur) chunks.push(cur)
  return chunks
}
