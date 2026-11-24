import React from 'react'

/** The assistant's mark: a small teal circle with a sparkle. Quiet by design; it never animates. */
export default function BotAvatar({ size = 28, className = '' }) {
  return (
    <span className={`ai-avatar ${className}`} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size * 0.58} height={size * 0.58} fill="currentColor"><path d="M12 2.5l1.9 5.6 5.6 1.9-5.6 1.9L12 17.5l-1.9-5.6-5.6-1.9 5.6-1.9z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" opacity=".85" /></svg>
    </span>
  )
}
