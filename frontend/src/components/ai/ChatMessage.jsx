import React from 'react'
import { useSpeechOutput } from '../../hooks/useSpeechOutput.js'
import { useToast } from '../../context/ToastContext.jsx'
import { IconCopy } from '../icons.jsx'
import BotAvatar from './BotAvatar.jsx'
import Evidence from './Evidence.jsx'
import Markdown from './Markdown.jsx'
import { IconAlertTri, IconRetry, IconThumbDown, IconThumbUp } from './icons.jsx'

export function UserMessage({ msg }) {
  return <div className="flex justify-end"><div className="ai-user-bubble">{msg.text}</div></div>
}

/** One assistant reply, shown the way chat apps do: just the answer, quiet actions underneath, sources only when there are some.
 *  Notes appear only for real problems (an unreachable model, figures that could not be verified, an interrupted answer). */
export function AssistantMessage({ msg, isLast, onFeedback, onRetry, disabled, language = 'en' }) {
  const toast = useToast()
  const voice = useSpeechOutput({ language })
  const meta = msg.meta
  const citations = (msg.sources?.knowledge || []).map((s) => s.title)
  const copy = async () => {
    try { await navigator.clipboard.writeText(msg.text || ''); toast.success('Copied') } catch { toast.error('Could not copy. Select the text and copy it manually.') }
  }
  const ungrounded = meta?.validation?.ungrounded_numbers || []
  const note = msg.stopped ? 'You stopped this answer.' : msg.interrupted ? 'The connection ended before the answer finished.' : meta?.validation?.interrupted ? 'The connection to the language model dropped, so this answer is incomplete.' : meta?.notice
  const typing = msg.streaming && !msg.text
  return (
    <div className="flex gap-3">
      <BotAvatar size={28} className="mt-0.5" />
      <div className="ai-answer" aria-live={msg.streaming ? 'polite' : undefined} aria-busy={msg.streaming ? 'true' : undefined}>
        {typing && (msg.stage?.label
          ? <p className="ai-stage-line" role="status"><span className="ai-dots" aria-hidden="true"><span /><span /><span /></span>{msg.stage.label}…</p>
          : <p className="ai-stage-line" role="status"><span className="ai-dots" aria-hidden="true"><span /><span /><span /></span><span className="ai-sr">Thinking</span></p>)}
        {msg.text && <Markdown text={msg.text} citations={citations} />}
        {msg.streaming && msg.text && <span className="ai-caret" aria-hidden="true" />}
        {msg.error && <p className={`ai-note bad mt-2 flex items-start gap-2`} role="alert"><IconAlertTri className="mt-0.5 h-4 w-4 shrink-0" />{msg.errorText}</p>}
        {voice.error && <p className="ai-note mt-2" role="status">{voice.error}</p>}
        {!msg.streaming && !msg.error && !msg.text && <p className="ai-muted text-sm">No answer was produced.</p>}
        {!msg.streaming && note && <p className="ai-note mt-2">{note}</p>}
        {!msg.streaming && ungrounded.length > 0 && <p className="ai-note mt-2" role="status">Please double-check these figures, which were not found in the data: {ungrounded.join(', ')}.</p>}
        {!msg.streaming && <Evidence sources={msg.sources} />}
        {!msg.streaming && (msg.text || msg.error) && (
          <div className="ai-actions">
            {msg.text && <button type="button" className="ai-icon-btn" onClick={copy} aria-label="Copy answer" title="Copy"><IconCopy className="h-4 w-4" /></button>}
            {msg.text && voice.supported && (voice.state === 'idle'
              ? <button type="button" className="ai-icon-btn px-2 text-xs font-semibold" onClick={() => voice.speak(msg.text)}>Listen</button>
              : <>
                {voice.state === 'speaking' ? <button type="button" className="ai-icon-btn px-2 text-xs font-semibold" onClick={voice.pause}>Pause</button> : <button type="button" className="ai-icon-btn px-2 text-xs font-semibold" onClick={voice.resume}>Resume</button>}
                <button type="button" className="ai-icon-btn px-2 text-xs font-semibold" onClick={voice.stop}>Stop</button>
              </>)}
            {msg.id && !msg.error && <>
              <button type="button" className="ai-icon-btn" aria-pressed={msg.feedback === 'up'} onClick={() => onFeedback(msg, 'up')} aria-label="Good answer" title="Good answer"><IconThumbUp className="h-4 w-4" /></button>
              <button type="button" className="ai-icon-btn" aria-pressed={msg.feedback === 'down'} onClick={() => onFeedback(msg, 'down')} aria-label="Poor answer" title="Poor answer"><IconThumbDown className="h-4 w-4" /></button>
            </>}
            {isLast && onRetry && <button type="button" className="ai-icon-btn" onClick={onRetry} disabled={disabled} aria-label="Try again" title="Try again"><IconRetry className="h-4 w-4" /></button>}
          </div>
        )}
      </div>
    </div>
  )
}
