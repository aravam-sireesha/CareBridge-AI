import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

// Needs the demo data from scripts/seed_demo.py and these accounts (see README).
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL || 'admin@carebridge-demo.org', password: process.env.E2E_ADMIN_PASSWORD || 'AdminPass12345!' }
const DONOR = { email: process.env.E2E_DONOR_EMAIL || 'asha@demo.org', password: process.env.E2E_DONOR_PASSWORD || 'AshaPass12345!' }
const wait = { timeout: 15000 }
const mount = (path) => render(<MemoryRouter initialEntries={[path]}><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></MemoryRouter>)

async function login(user, c) {
  await user.type(screen.getByPlaceholderText(/you@organization.org/i), c.email)
  await user.type(screen.getByPlaceholderText(/your password/i), c.password)
  await user.click(screen.getByRole('button', { name: /^login$/i }))
  await screen.findByText(/Good (morning|afternoon|evening)/i, {}, wait)
}

describe('AI modules through the UI (live backend + PostgreSQL)', () => {
  it('admin: career profile -> recommendations -> decision are stored', async () => {
    const user = userEvent.setup()
    mount('/login'); await login(user, ADMIN)
    await user.click(screen.getAllByRole('link', { name: /career guidance/i })[0])
    await screen.findByText(/three suggested career paths/i, {}, wait)
    await user.click(await screen.findByRole('button', { name: /(create|edit) career profile/i }, wait))
    const dlg = await screen.findByRole('dialog')
    await user.click(within(dlg).getByRole('button', { name: /save profile/i }))
    await screen.findByRole('button', { name: /generate recommendations/i }, wait)
    await user.click(await screen.findByRole('button', { name: /generate recommendations/i }))
    await screen.findAllByText(/Suggestion 1/i, {}, wait)
    await user.click((await screen.findAllByRole('button', { name: /^accept /i }, wait))[0])
    await screen.findAllByText(/accepted/i, {}, wait)
  })

  it('admin: suggest matches for a need, then confirm one', async () => {
    const user = userEvent.setup()
    mount('/login'); await login(user, ADMIN)
    await user.click(screen.getAllByRole('link', { name: /matching review/i })[0])
    await screen.findByText(/suggested for open needs/i, {}, wait)
    await user.click(await screen.findByRole('button', { name: /suggest matches/i }, wait))
    const confirm = await screen.findAllByRole('button', { name: /^confirm$/i }, wait)
    await user.click(confirm[0])
    await screen.findAllByText(/confirmed/i, {}, wait)
  })

  it('admin: need alerts scan finds the urgent needs', async () => {
    const user = userEvent.setup()
    mount('/login'); await login(user, ADMIN)
    await user.click(screen.getAllByRole('link', { name: /need alerts/i })[0])
    await screen.findByText(/flagged for high urgency/i, {}, wait)
    await user.click(await screen.findByRole('button', { name: /scan needs/i }, wait))
    await screen.findByText(/Scan complete/i, {}, wait)
  })

  it('donor: records a donation that is saved and listed', async () => {
    const user = userEvent.setup()
    mount('/login'); await login(user, DONOR)
    await user.click(screen.getAllByRole('link', { name: /^donations$/i })[0])
    await user.click(await screen.findByRole('button', { name: /record donation/i }, wait))
    const dlg = await screen.findByRole('dialog')
    const [donorSel, needSel] = within(dlg).getAllByRole('combobox')
    await user.selectOptions(donorSel, donorSel.querySelectorAll('option')[1])
    await user.selectOptions(needSel, needSel.querySelectorAll('option')[1])
    await user.type(within(dlg).getByRole('spinbutton'), '2500')
    await user.type(within(dlg).getByPlaceholderText(/books and stationery/i), 'E2E test gift')
    await user.click(within(dlg).getByRole('button', { name: /save donation/i }))
    await screen.findByText('E2E test gift', {}, wait)
  })
})
