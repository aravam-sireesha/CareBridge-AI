// Server-Sent Events parser for fetch() streams. EventSource cannot send an Authorization header or a POST body,
// so the app reads the response stream itself and feeds the chunks to this parser.
export function createSseParser(onEvent) {
  let buf = ''
  return {
    push(chunk) {
      buf = (buf + chunk).replace(/\r\n/g, '\n')
      let i
      while ((i = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, i)
        buf = buf.slice(i + 2)
        let event = 'message'
        const data = []
        let id = null
        for (const line of frame.split('\n')) {
          if (line.startsWith(':')) continue            // comment / keep-alive
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('id:')) id = line.slice(3).trim()
          else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
        }
        if (!data.length) continue
        const raw = data.join('\n')
        let payload
        try { payload = JSON.parse(raw) } catch { payload = raw }
        if (id) onEvent(event, payload, id)           // the id is passed only when the server sent one (replay uses it)
        else onEvent(event, payload)
      }
    }
  }
}
