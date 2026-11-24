import { useCallback, useEffect, useRef, useState } from 'react'

export const BCP47 = { en: 'en-IN', te: 'te-IN', hi: 'hi-IN', ta: 'ta-IN', kn: 'kn-IN', ml: 'ml-IN', mr: 'mr-IN', bn: 'bn-IN', gu: 'gu-IN', pa: 'pa-IN', ur: 'ur-IN', es: 'es-ES', fr: 'fr-FR', de: 'de-DE', pt: 'pt-BR', ar: 'ar-SA', zh: 'zh-CN', ja: 'ja-JP' }

export function speechMessage(code) {
  return ({
    'not-allowed': 'Microphone permission was denied. Allow it in your browser settings, or type your question instead.',
    'service-not-allowed': 'Microphone permission was denied. Allow it in your browser settings, or type your question instead.',
    'no-speech': 'No speech was heard. Press the microphone and try again, or type your question.',
    'audio-capture': 'No microphone was found. Connect one, or type your question instead.',
    network: 'Speech recognition needs an internet connection. Type your question instead.',
    'language-not-supported': 'This browser cannot recognise the selected language by voice. Type your question instead.'
  })[code] || 'Voice input stopped unexpectedly. You can type your question instead.'
}

/** Browser speech recognition. `supported` is false when the browser has none (Firefox, some mobile browsers): the caller shows a message and keeps typing available.
 *  Recognised text goes to `onText(text, isFinal)`; nothing is sent anywhere until the person presses Send. */
export function useSpeechInput({ language = 'en', onText }) {
  const Ctor = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : undefined
  const [listening, setListening] = useState(false)
  const [error, setError] = useState(null)
  const recRef = useRef(null)
  const cb = useRef(onText)
  cb.current = onText

  const stop = useCallback(() => { try { recRef.current?.stop() } catch { /* already stopped */ } }, [])
  const start = useCallback(() => {
    if (!Ctor) { setError('Voice input is not supported in this browser. Type your question instead.'); return }
    setError(null)
    const rec = new Ctor()
    rec.lang = BCP47[language] || 'en-IN'
    rec.interimResults = true
    rec.continuous = false
    rec.onresult = (e) => {
      let text = ''
      let final = false
      for (let i = 0; i < e.results.length; i++) { text += e.results[i][0].transcript; if (e.results[i].isFinal) final = true }
      cb.current?.(text, final)
    }
    rec.onerror = (e) => { setError(speechMessage(e.error)); setListening(false) }
    rec.onend = () => setListening(false)
    recRef.current = rec
    try { rec.start(); setListening(true) } catch { setError(speechMessage()); setListening(false) }
  }, [Ctor, language])

  useEffect(() => () => { try { recRef.current?.abort() } catch { /* ignore */ } }, [])
  return { supported: Boolean(Ctor), listening, error, start, stop, clearError: () => setError(null) }
}
