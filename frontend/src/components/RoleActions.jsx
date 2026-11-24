import React from 'react'
import { Link } from 'react-router-dom'
import { DASHBOARD_ACTIONS } from '../lib/dashboardActions.js'
import { IconArrowRight, IconAssistant, IconDonations, IconHand, IconNeeds, IconPin, IconPlus } from './icons.jsx'

const ICONS = { plus: IconPlus, needs: IconNeeds, hand: IconHand, donations: IconDonations, pin: IconPin, assistant: IconAssistant }

/** The few things this role does most, as large links. The primary action uses the warm accent: one per screen. */
export default function RoleActions({ role }) {
  const actions = DASHBOARD_ACTIONS[role] || []
  if (!actions.length) return null
  return (
    <nav aria-label="Quick actions" className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {actions.map((a) => {
        const Icon = ICONS[a.icon] || IconArrowRight
        return (
          <Link key={a.to} to={a.to}
            className={`group flex items-start gap-3 rounded-2xl border p-4 transition-colors ${a.primary ? 'border-accent-100 bg-accent-50 hover:border-accent-500' : 'border-line bg-white hover:border-teal-300'}`}>
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${a.primary ? 'bg-accent-700 text-white' : 'bg-teal-50 text-teal-700'}`}><Icon className="h-[18px] w-[18px]" /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-ink">{a.title}</span>
              <span className="mt-0.5 block text-xs text-ink-muted">{a.text}</span>
            </span>
            <IconArrowRight className="mt-1 h-4 w-4 shrink-0 text-ink-muted group-hover:text-teal-700" />
          </Link>
        )
      })}
    </nav>
  )
}
