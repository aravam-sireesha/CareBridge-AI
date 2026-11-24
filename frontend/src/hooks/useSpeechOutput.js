import { useCallback, useEffect, useRef, useState } from 'react'
import { BCP47 } from './useSpeechInput.js'
import { chunkForSpeech, speechText } from '../lib/speechText.js'

let owner = null           // only one answer is read aloud at a time
let resetOwner = null      // tells the previous speaker its voice was taken over, so its buttons go back to "Listen"

/** Read an answer aloud with the browser's own speech engine (no audio leaves the device, no paid service).
 *  Nothing is spoken until the person presses Listen. `supported` is false where the browser has no speech synthesis. */
export function useSpeechOutput({ language = 'en' } = {}) {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined
  const supported = Boolean(synth) && typeof window.SpeechSynthesisUtterance !== 'undefined'
  const id = useRef(Symbol('speech')).current
  const [state, setState] = useState('idle')          // idle | speaking | paused
  const [error, setError] = useState('')
  const queue = useRef(0)

  const stop = useCallback(() => { if (owner === id) { owner = null; resetOwner = null; synth?.cancel() } queue.current = 0; setState('idle') }, [synth, id])
  useEffect(() => () => { if (owner === id) { owner = null; resetOwner = null; synth?.cancel() } }, [synth, id])      // leaving the screen stops the voice

  const speak = useCallback((markdown) => {
    if (!supported) { setError('Reading aloud is not supported in this browser.'); return }
    const lang = BCP47[language] || 'en-IN'; const prefix = lang.split('-')[0]
    const voices = synth.getVoices ? synth.getVoices() : []
    if (voices.length && !voices.some((v) => v.lang && v.lang.toLowerCase().startsWith(prefix))) {
      setError('This device has no voice for the selected language, so the answer is not read aloud (an English voice would mispronounce it).'); return
    }
    const chunks = chunkForSpeech(speechText(markdown))
    if (!chunks.length) { setError('There is nothing to read aloud.'); return }
    setError('')
    if (owner && owner !== id && resetOwner) resetOwner()          // someone else was speaking: put their buttons back
    synth.cancel(); owner = id; resetOwner = () => { queue.current = 0; setState('idle') }; queue.current = chunks.length
    try {
    chunks.forEach((text, i) => {
      const u = new window.SpeechSynthesisUtterance(text); u.lang = lang
      const match = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(prefix)); if (match) u.voice = match
      u.onend = () => { queue.current -= 1; if (owner === id && queue.current <= 0) { owner = null; resetOwner = null; setState('idle') } }
      u.onerror = (e) => { if (e && (e.error === 'canceled' || e.error === 'interrupted')) return; setError('The voice stopped unexpectedly.'); stop() }
      synth.speak(u)
    })
    } catch {                                                 // a failing speech engine must never break the chat
      setError('The voice could not start on this device.'); stop(); return
    }
    setState('speaking')
  }, [supported, synth, language, id, stop])

  const pause = useCallback(() => { if (owner === id) { synth.pause(); setState('paused') } }, [synth, id])
  const resume = useCallback(() => { if (owner === id) { synth.resume(); setState('speaking') } }, [synth, id])
  return { supported, state, error, speak, pause, resume, stop }
}
