import React from 'react'
import { Link } from 'react-router-dom'
import Logo from './Logo.jsx'

/** Left-hand photo panel shown beside the sign-in / setup frame (same look as the main Login page). */
export default function ChildPhotoPanel({ headline = 'Every child deserves a chance', text }) {
  return (
    <div className="relative hidden overflow-hidden lg:block">
      <img src="/images/child-portrait.jpg" alt="" aria-hidden="true" className="absolute inset-0 h-full w-full object-cover object-[50%_18%]" />
      <div className="absolute inset-0 bg-teal-900/60" />
      <div className="absolute inset-0 bg-gradient-to-t from-teal-900/90 via-transparent to-transparent" />
      <div className="relative flex h-full flex-col justify-between p-10 text-white">
        <Link to="/" aria-label="CareBridge AI home"><Logo size={44} light showTagline /></Link>
        <div>
          <p className="font-script text-5xl leading-tight drop-shadow">{headline}</p>
          {text && <p className="mt-6 max-w-lg text-[15px] leading-relaxed text-white/90">{text}</p>}
        </div>
      </div>
    </div>
  )
}
