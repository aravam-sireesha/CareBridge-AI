import React from 'react'

const make = (paths, size = 18) => (props) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths}</svg>
)

export const IconStop = make(<rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none" />)
export const IconArrowUp = make(<><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></>)
export const IconThumbUp = make(<><path d="M7 11v9H4v-9z" /><path d="M7 11l4-8a2 2 0 012 2v4h5.5a2 2 0 012 2.3l-1.2 6A2 2 0 0117.3 19H7" /></>)
export const IconThumbDown = make(<><path d="M17 13V4h3v9z" /><path d="M17 13l-4 8a2 2 0 01-2-2v-4H5.5a2 2 0 01-2-2.3l1.2-6A2 2 0 016.7 5H17" /></>)
export const IconTrash = make(<><path d="M4 7h16" /><path d="M10 11v6M14 11v6" /><path d="M6 7l1 13h10l1-13" /><path d="M9 7V4h6v3" /></>)
export const IconPencil = make(<><path d="M4 20l1-4L16.5 4.5a2 2 0 012.8 2.8L7.8 18.8z" /><path d="M14 7l3 3" /></>)
export const IconChevronDown = make(<path d="M6 9l6 6 6-6" />)
export const IconPlay = make(<path d="M7 4.5v15l12-7.5z" fill="currentColor" />)
export const IconDownload = make(<><path d="M12 4v11" /><path d="M7 11l5 5 5-5" /><path d="M5 20h14" /></>)
export const IconClock = make(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>)
export const IconShieldCheck = make(<><path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5L16 9.5" /></>)
export const IconSparkle = make(<><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 15l.7 2.1L22 18l-2.3.9L19 21l-.7-2.1L16 18l2.3-.9z" /></>)
export const IconMenuLines = make(<><path d="M4 7h16" /><path d="M4 12h10" /><path d="M4 17h16" /></>)
export const IconWrench = make(<path d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8 6.2 21l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />)
export const IconAlertTri = make(<><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18h.01" /></>)
export const IconRetry = make(<><path d="M3 12a9 9 0 109-9" /><path d="M3 4v5h5" /></>)
export const IconMic = make(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0" /><path d="M12 18v3" /></>)
