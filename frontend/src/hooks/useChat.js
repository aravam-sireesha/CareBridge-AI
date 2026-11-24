import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamPost } from '../api/client.js'

const fromServer = (m) => ({ key: `s-${m.id}`, id: m.id, role: m.role, text: m.content, sources: m.sources, meta: m.meta, feedback: m.feedback, at: m.created_at })

/** Chat state: conversation list, the open thread, and one streamed answer at a time.
 *  Events from POST /chat/stream: conversation, status, sources, token, done, error. */
export function useChat({ language = 'en' } = {}) {
  const languageRef = useRef(language)
  languageRef.current = language
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [loadingThread, setLoadingThread] = useState(false)
  const [listError, setListError] = useState(null)
  const [query, setQuery] = useState('')
  const queryRef = useRef('')
  const activeRef = useRef(null)
  const abortRef = useRef(null)
  const busyRef = useRef(false)
  const mounted = useRef(true)

  const refreshList = useCallback(() => api.chatConversations(queryRef.current).then((rows) => { if (mounted.current) { setConversations(rows || []); setListError(null) } }).catch((e) => { if (mounted.current) setListError(e.message) }), [])

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; abortRef.current?.abort() } }, [])

  // conversation search: debounced, matches titles and message text on the server (only the user's own conversations)
  useEffect(() => {
    queryRef.current = query.trim()
    const t = setTimeout(() => { refreshList() }, query ? 250 : 0)
    return () => clearTimeout(t)
  }, [query, refreshList])

  const stop = useCallback(() => { abortRef.current?.abort() }, [])

  const send = useCallback(async (text, { regenerate = false } = {}) => {
    const q = (text || '').trim()
    if (!q || busyRef.current) return false          // one question at a time: prevents duplicate submissions
    busyRef.current = true
    setBusy(true)
    const ctl = new AbortController()
    abortRef.current = ctl
    const stamp = Date.now()
    const key = `live-${stamp}`
    const now = new Date().toISOString()
    setMessages((m) => [...(regenerate ? m.slice(0, m.map((x) => x.role).lastIndexOf('user') + 1) : [...m, { key: `u-${stamp}`, role: 'user', text: q, at: now }]), { key, role: 'assistant', text: '', streaming: true, stage: { stage: 'connecting', label: 'Connecting' }, sources: null, meta: null, at: now }])
    const patch = (fn) => setMessages((m) => m.map((x) => (x.key === key ? (typeof fn === 'function' ? fn(x) : { ...x, ...fn }) : x)))
    let finished = false
    try {
      await streamPost('/chat/stream', { message: q, conversation_id: activeRef.current, regenerate, language: languageRef.current }, {
        signal: ctl.signal,
        onEvent: (name, d) => {
          if (name === 'conversation') {
            activeRef.current = d.conversation_id
            setActiveId(d.conversation_id)
            setConversations((list) => (list.some((c) => c.id === d.conversation_id) ? list : [{ id: d.conversation_id, title: d.title, updated_at: now }, ...list]))
          } else if (name === 'status') patch({ stage: d })
          else if (name === 'sources') patch({ sources: d })
          else if (name === 'token') patch((x) => ({ ...x, text: x.text + d.t, stage: null }))
          else if (name === 'done') { finished = true; patch((x) => ({ ...x, streaming: false, stage: null, id: d.message_id, meta: d })) }
          else if (name === 'error') { finished = true; patch((x) => ({ ...x, streaming: false, stage: null, error: true, errorText: d.message, partial: !!x.text })) }
        }
      })
      if (!finished) patch((x) => ({ ...x, streaming: false, stage: null, interrupted: true }))   // the connection ended without a final event
    } catch (e) {
      if (e?.name === 'AbortError') patch((x) => ({ ...x, streaming: false, stage: null, stopped: true }))
      else patch((x) => ({ ...x, streaming: false, stage: null, error: true, errorText: e.message, partial: !!x.text }))
    } finally {
      busyRef.current = false
      abortRef.current = null
      if (mounted.current) { setBusy(false); refreshList() }
    }
    return true
  }, [refreshList])

  const select = useCallback(async (id) => {
    abortRef.current?.abort()
    setLoadingThread(true)
    try {
      const conv = await api.chatConversation(id)
      activeRef.current = id
      setActiveId(id)
      setMessages((conv.messages || []).map(fromServer))
    } catch (e) {
      setListError(e.message)
    } finally { setLoadingThread(false) }
  }, [])

  const newChat = useCallback(() => {
    abortRef.current?.abort()
    activeRef.current = null
    setActiveId(null)
    setMessages([])
  }, [])

  const remove = useCallback(async (id) => {
    await api.chatDelete(id)
    setConversations((list) => list.filter((c) => c.id !== id))
    if (activeRef.current === id) newChat()
  }, [newChat])

  const rename = useCallback(async (id, title) => {
    const res = await api.chatRename(id, title)
    setConversations((list) => list.map((c) => (c.id === id ? { ...c, title: res.title } : c)))
  }, [])

  const feedback = useCallback(async (msg, value) => {
    if (!msg.id || msg.streaming) return
    const next = msg.feedback === value ? null : value
    setMessages((m) => m.map((x) => (x.key === msg.key ? { ...x, feedback: next } : x)))
    try { await api.chatFeedback(msg.id, next) } catch { setMessages((m) => m.map((x) => (x.key === msg.key ? { ...x, feedback: msg.feedback } : x))) }
  }, [])

  return { query, setQuery, conversations, activeId, messages, busy, loadingThread, listError, send, stop, select, newChat, remove, rename, feedback }
}
