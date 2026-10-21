import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import Donations from '../src/pages/Donations.jsx'
import { api } from '../src/api/client.js'

vi.mock('../src/api/client.js', () => ({
  api: {
    listDonations: vi.fn(),
    listDonors: vi.fn(),
    listNeeds: vi.fn(),
    createDonation: vi.fn()
  }
}))

vi.mock('../src/context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { role: 'organization', name: 'Test Organization' } })
}))

vi.mock('../src/context/ToastContext.jsx', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() })
}))

vi.mock('../src/components/Layout.jsx', () => ({
  default: ({ children }) => <>{children}</>
}))

describe('donation need selection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.listDonations.mockResolvedValue([])
    api.listDonors.mockResolvedValue([])
    api.listNeeds.mockResolvedValue([])
  })

  async function openDonationForm() {
    render(<Donations />)
    fireEvent.click(await screen.findByRole('button', { name: /record donation/i }))
    return screen.findByRole('dialog')
  }

  it('explains when the current organization has no needs', async () => {
    const dialog = await openDonationForm()
    const needSelect = within(dialog).getByRole('combobox', { name: /for need/i })

    expect(await within(dialog).findByText(/no needs are available for your organization/i)).toBeInTheDocument()
    expect(needSelect).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: /save donation/i })).toBeDisabled()
  })

  it('shows request errors and lets the user retry loading needs', async () => {
    api.listNeeds
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce([{ id: 7, category: 'Food' }])
    const dialog = await openDonationForm()

    expect(await within(dialog).findByText('Could not load needs: Network error')).toBeInTheDocument()
    expect(within(dialog).getByRole('combobox', { name: /for need/i })).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('button', { name: /retry loading needs/i }))

    await waitFor(() => {
      expect(within(dialog).getByRole('option', { name: 'Food (#7)' })).toBeInTheDocument()
    })
    expect(within(dialog).getByRole('combobox', { name: /for need/i })).toBeEnabled()
  })
})
