import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { ToastProvider } from '../src/context/ToastContext.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { MemoryRouter } from 'react-router-dom'
import Donations from '../src/pages/Donations.jsx'
import Needs from '../src/pages/Needs.jsx'

const json = (v) => ({ ok: true, status: 200, text: async () => JSON.stringify(v), json: async () => v })
describe('Donations and Needs pages on the shared table', () => {
  it('Donations lists records with status badges, and Needs opens a record from ?open=', async () => {
    localStorage.setItem('cb_token', 't'); localStorage.setItem('cb_user', JSON.stringify({ id: 1, email: 'o@x.org', role: 'organization', name: 'Priya', organization_id: 1 }))
    global.fetch = async (url) => {
      const p = String(url).replace(/^\/api/, '').split('?')[0]
      if (p === '/auth/me') return json({ id: 1, email: 'o@x.org', role: 'organization', display_name: 'Priya', organization_id: 1 })
      if (p === '/donations/' || p === '/donations') return json([{ id: 5, donor_id: 1, need_id: 1, amount: 500, resource_description: 'Rice', timestamp: '2026-10-01T10:00:00', donor_name: 'Asha', need_name: 'Food', status: 'pending' }])
      if (p === '/needs/' || p === '/needs') return json([{ id: 4, category: 'Clothing', quantity: 40, urgency: 'critical', status: 'open', organization_name: 'Hope Home', title: 'Winter blankets', description: 'For the dormitory', created_at: '2026-10-01T10:00:00' }])
      if (p === '/donors/' || p === '/donors') return json([])
      return json({})
    }
    const { unmount } = render(<MemoryRouter><ToastProvider><AuthProvider><Donations /></AuthProvider></ToastProvider></MemoryRouter>)
    expect(await screen.findByText('Asha')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('pending')).toBeInTheDocument()
    unmount()
    window.history.pushState({}, '', '/needs?open=4')
    render(<MemoryRouter><ToastProvider><AuthProvider><Needs /></AuthProvider></ToastProvider></MemoryRouter>)
    expect(await screen.findByRole('dialog', { name: /winter blankets \(#4\)/i })).toHaveTextContent('For the dormitory')
    window.history.pushState({}, '', '/')
  })
})
