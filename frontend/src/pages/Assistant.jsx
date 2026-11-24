import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { useChat } from '../hooks/useChat.js'
import { useSpeechInput } from '../hooks/useSpeechInput.js'
import Layout from '../components/Layout.jsx'
import BotAvatar from '../components/ai/BotAvatar.jsx'
import { AssistantMessage, UserMessage } from '../components/ai/ChatMessage.jsx'
import { IconArrowUp, IconMenuLines, IconMic, IconPencil, IconStop, IconTrash } from '../components/ai/icons.jsx'
import { IconPlus, IconX } from '../components/icons.jsx'

const LANGUAGES = [['en', 'English'], ['te', 'తెలుగు (Telugu)'], ['hi', 'हिन्दी (Hindi)'], ['ta', 'தமிழ் (Tamil)'], ['kn', 'ಕನ್ನಡ (Kannada)'], ['ml', 'മലയാളം (Malayalam)'], ['mr', 'मराठी (Marathi)'], ['bn', 'বাংলা (Bengali)'], ['gu', 'ગુજરાતી (Gujarati)'], ['pa', 'ਪੰਜਾਬੀ (Punjabi)'], ['ur', 'اردو (Urdu)'], ['es', 'Español'], ['fr', 'Français'], ['de', 'Deutsch'], ['pt', 'Português'], ['ar', 'العربية'], ['zh', '中文'], ['ja', '日本語']]
const LANG_KEY = 'cb_chat_language'

const PROMPTS = {
  admin: ['Which needs are most urgent right now?', 'Summarize pending organization verifications.', 'Find donation requests that require attention.', 'Explain how CareBridge AI matches donors to needs.', 'What is artificial intelligence?'],
  organization: ['Which of our needs are most urgent right now?', 'How many donations are pending delivery?', 'Explain how CareBridge AI matches donors to needs.', 'How can our organization improve?', 'What is artificial intelligence?'],
  donor: ['Which needs could I support first?', 'How are donations tracked?', 'Explain how CareBridge AI matches donors to needs.', 'What is artificial intelligence?'],
  volunteer: ['How does volunteering work on CareBridge?', 'What is the volunteer background check policy?', 'What is artificial intelligence?']
}

function ThreadItem({ c, active, onOpen, onRename, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(c.title)
  const [confirm, setConfirm] = useState(false)
  if (editing) {
    return (
      <form onSubmit={(e) => { e.preventDefault(); const t = title.trim(); if (t) onRename(c.id, t); setEditing(false) }}>
        <input autoFocus className="ai-search" value={title} maxLength={120} aria-label="Conversation title" onChange={(e) => setTitle(e.target.value)} onBlur={() => setEditing(false)} onKeyDown={(e) => e.key === 'Escape' && setEditing(false)} />
      </form>
    )
  }
  if (confirm) {
    return (
      <div className="rounded-lg border p-2 text-xs" style={{ borderColor: 'var(--ai-line)' }} role="group" aria-label={`Delete ${c.title}?`}>
        <p className="mb-2">Delete this conversation?</p>
        <span className="flex gap-2"><button type="button" className="ai-primary !px-3 !py-1 !text-xs" onClick={() => onDelete(c.id)}>Delete</button><button type="button" className="ai-ghost !px-3 !py-1 !text-xs" onClick={() => setConfirm(false)}>Cancel</button></span>
      </div>
    )
  }
  return (
    <div className="group flex items-center">
      <button type="button" className="ai-thread min-w-0 flex-1" aria-current={active} onClick={() => onOpen(c.id)} title={c.title}><span className="truncate">{c.title}</span></button>
      <span className="flex shrink-0 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
        <button type="button" className="ai-icon-btn !h-7 !w-7" aria-label={`Rename ${c.title}`} onClick={() => { setTitle(c.title); setEditing(true) }}><IconPencil className="h-3.5 w-3.5" /></button>
        <button type="button" className="ai-icon-btn !h-7 !w-7" aria-label={`Delete ${c.title}`} onClick={() => setConfirm(true)}><IconTrash className="h-3.5 w-3.5" /></button>
      </span>
    </div>
  )
}

export default function Assistant() {
  const { user } = useAuth()
  const toast = useToast()
  const [language, setLanguage] = useState(() => { try { const v = sessionStorage.getItem(LANG_KEY); return LANGUAGES.some(([c]) => c === v) ? v : 'en' } catch { return 'en' } })
  const chat = useChat({ language })
  const pickLanguage = (code) => { setLanguage(code); try { sessionStorage.setItem(LANG_KEY, code) } catch { /* private mode */ } }
  const status = useAsync(() => (user.role === 'admin' ? api.chatStatus().catch(() => null) : Promise.resolve(null)), [user.role])
  const [text, setText] = useState('')
  const [sideOpen, setSideOpen] = useState(() => typeof window === 'undefined' || window.innerWidth >= 1024)
  const scrollRef = useRef(null)
  const stick = useRef(true)
  const inputRef = useRef(null)
  const empty = chat.messages.length === 0
  const baseText = useRef('')
  const voice = useSpeechInput({ language, onText: (t) => { setText(`${baseText.current}${baseText.current && t ? ' ' : ''}${t}`); requestAnimationFrame(resize) } })
  const toggleVoice = () => { if (voice.listening) voice.stop(); else { baseText.current = text.trim(); voice.start() } }

  // keep the newest text in view while it streams, unless the reader scrolled up
  useEffect(() => { const el = scrollRef.current; if (el && stick.current) el.scrollTop = el.scrollHeight }, [chat.messages])
  const onScroll = () => { const el = scrollRef.current; if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90 }
  const resize = () => { const el = inputRef.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(Math.max(el.scrollHeight, 28), 160)}px` } }
  const narrow = () => typeof window !== 'undefined' && window.innerWidth < 1024

  const submit = useCallback(async (q) => {
    const value = (q ?? text).trim()
    if (!value || chat.busy) return
    setText(''); stick.current = true
    requestAnimationFrame(resize)
    await chat.send(value)
    inputRef.current?.focus()
  }, [chat, text])
  const retry = useCallback(() => {
    const last = [...chat.messages].reverse().find((m) => m.role === 'user')
    if (last && !chat.busy) { stick.current = true; chat.send(last.text, { regenerate: true }) }
  }, [chat])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && chat.busy) chat.stop() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [chat])

  const lastAssistant = [...chat.messages].reverse().find((m) => m.role === 'assistant')
  const remove = async (id) => { try { await chat.remove(id) } catch (e) { toast.error(e.message) } }
  const rename = async (id, t) => { try { await chat.rename(id, t) } catch (e) { toast.error(e.message) } }
  const title = chat.conversations.find((c) => c.id === chat.activeId)?.title || 'New chat'
  const noModel = status.data && status.data.llm_configured === false

  return (
    <Layout title="AI assistant" fullScreen>
      <div className="ai-root ai-full">
        {sideOpen && <button type="button" className="ai-scrim ai-mobile-only" aria-label="Close conversations" onClick={() => setSideOpen(false)} />}
        <aside className="ai-side" data-open={sideOpen} aria-label="Conversations">
          <div className="flex items-center gap-2 p-3">
            <button type="button" className="ai-ghost flex-1 !justify-start" onClick={() => { chat.newChat(); chat.setQuery(''); if (narrow()) setSideOpen(false); inputRef.current?.focus() }}><IconPlus className="h-4 w-4" />New chat</button>
            <button type="button" className="ai-icon-btn" aria-label="Hide conversations" onClick={() => setSideOpen(false)}><IconX className="h-4 w-4" /></button>
          </div>
          <div className="px-3 pb-2"><input type="search" className="ai-search" placeholder="Search conversations" aria-label="Search conversations" value={chat.query} onChange={(e) => chat.setQuery(e.target.value)} /></div>
          <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2" aria-label="Chat history">
            {chat.listError && <p className="ai-note bad m-1">{chat.listError}</p>}
            {chat.conversations.length === 0 && !chat.listError && <p className="ai-faint px-3 py-2 text-xs">{chat.query ? 'No conversations match.' : 'Your conversations will appear here.'}</p>}
            {chat.conversations.map((c) => <ThreadItem key={c.id} c={c} active={c.id === chat.activeId} onOpen={(id) => { chat.select(id); if (narrow()) setSideOpen(false) }} onRename={rename} onDelete={remove} />)}
          </nav>
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t px-4 py-3 text-xs" style={{ borderColor: 'var(--ai-line)' }}>
            <Link to="/agent" className="ai-muted hover:underline">AI agent</Link>
            <Link to="/assistant/knowledge" className="ai-muted hover:underline">Knowledge &amp; insights</Link>
            {user.role === 'admin' && <Link to="/admin/llm" className="ai-muted hover:underline">Model settings</Link>}
          </div>
        </aside>

        <section className="ai-chat" aria-label="Chat">
          <header className="ai-chat-head">
            {!sideOpen && <button type="button" className="ai-icon-btn" aria-label="Show conversations" onClick={() => setSideOpen(true)}><IconMenuLines className="h-5 w-5" /></button>}
            <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h1>
            <label className="sr-only" htmlFor="chat-language">Answer language</label>
            <select id="chat-language" value={language} onChange={(e) => pickLanguage(e.target.value)} className="max-w-[9.5rem] rounded-lg border bg-transparent px-2 py-1 text-xs" style={{ borderColor: 'var(--ai-line)', color: 'var(--ai-ink)' }} title="Language of the answers">
              {LANGUAGES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
          </header>
          {noModel && (
            <p className="ai-note mx-4 mt-3 rounded-lg" role="status">No language model is connected, so general questions cannot be answered yet. <Link to="/admin/llm" className="font-semibold underline">Set one up</Link>. Questions about your CareBridge data still work.</p>
          )}

          <div ref={scrollRef} onScroll={onScroll} className="ai-scroll" tabIndex={-1}>
            <div className="ai-lane">
              {empty && !chat.loadingThread && (
                <div className="flex flex-col items-center pt-6 text-center sm:pt-14">
                  <BotAvatar size={44} />
                  <h2 className="mt-4 font-display text-2xl font-semibold">How can I help you today?</h2>
                  <p className="ai-muted mt-2 max-w-md text-sm">Ask a general question, or ask about your CareBridge data. Every answer that uses your data lists its sources.</p>
                  <div className="mt-6 grid w-full max-w-xl gap-2 sm:grid-cols-2">
                    {(PROMPTS[user.role] || PROMPTS.volunteer).map((q) => <button key={q} type="button" className="ai-prompt" onClick={() => submit(q)}>{q}</button>)}
                  </div>
                </div>
              )}
              {chat.loadingThread && <p className="ai-muted py-10 text-center text-sm" role="status">Loading conversation…</p>}
              <div className="space-y-6 pb-4" role="log" aria-label="Conversation">
                {chat.messages.map((m) => m.role === 'user'
                  ? <UserMessage key={m.key} msg={m} />
                  : <AssistantMessage key={m.key} msg={m} isLast={m === lastAssistant} disabled={chat.busy} language={language} onFeedback={chat.feedback} onRetry={retry} />)}
              </div>
            </div>
          </div>

          <div className="ai-composer-wrap">
            <form className="ai-composer" onSubmit={(e) => { e.preventDefault(); submit() }}>
              <div className="flex items-end gap-2">
                <textarea ref={inputRef} rows={1} value={text} maxLength={4000} aria-label="Your question" placeholder="Message CareBridge AI" onChange={(e) => { setText(e.target.value); resize() }}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
                <button type="button" className="ai-icon-btn !h-9 !w-9 shrink-0" aria-pressed={voice.listening} onClick={toggleVoice} aria-label={voice.listening ? 'Stop voice input' : 'Start voice input'} title={voice.supported ? (voice.listening ? 'Stop listening' : 'Speak instead of typing') : 'Voice input is not supported in this browser'}><IconMic className="h-[18px] w-[18px]" /></button>
                {chat.busy
                  ? <button type="button" className="ai-send" onClick={chat.stop} aria-label="Stop generating" title="Stop (Esc)"><IconStop className="h-4 w-4" /></button>
                  : <button type="submit" className="ai-send" disabled={!text.trim()} aria-label="Send"><IconArrowUp className="h-[18px] w-[18px]" /></button>}
              </div>
            </form>
            {voice.listening && <p className="ai-faint mt-2 text-center text-xs" role="status">Listening… speak now, then press the microphone again to stop.</p>}
            {voice.error && <p className="ai-note mx-auto mt-2 max-w-xl" role="alert">{voice.error}</p>}
            <p className="ai-faint mt-2 text-center text-[11px]">CareBridge AI can make mistakes. Check important details. Every answer is a recommendation; administrators decide.</p>
          </div>
        </section>
      </div>
    </Layout>
  )
}
