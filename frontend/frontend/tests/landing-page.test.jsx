import React from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ThemeProvider } from '../src/context/ThemeContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const NEED = { id: 1, title: 'Winter blankets', category: 'clothing', quantity: 20, urgency: 'critical', organization: 'Hope Home', required_by: null }
const ROUTES = {
  'GET /public/stats': { verified_organizations: 1, open_needs: 1, fulfilled_needs: 0, confirmed_donations: 0, registered_donors: 2, registered_volunteers: 3, beneficiaries_supported: 0 },
  'GET /public/needs': [NEED],
  'GET /public/organizations': [{ id: 1, name: 'Hope Home', about: null, website: null }]
}
const realMatchMedia = window.matchMedia

function mockFetch() {
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    if (!(key in ROUTES)) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: `no mock for ${key}` }) }
    return { ok: true, status: 200, text: async () => JSON.stringify(ROUTES[key]) }
  })
}
const mount = () => render(
  <MemoryRouter initialEntries={['/']}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>
)

beforeEach(() => { document.documentElement.classList.remove('dark'); mockFetch() })
afterEach(() => { window.matchMedia = realMatchMedia })

describe('landing page', () => {
  it('keeps the existing logo, sections and shows real urgent needs', async () => {
    mount()
    expect(screen.getAllByLabelText(/carebridge ai logo/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { level: 1, name: /connecting compassion with every need/i })).toBeInTheDocument()
    for (const id of ['home', 'about', 'how', 'organizations', 'impact', 'contact']) expect(document.getElementById(id)).not.toBeNull()
    expect(await screen.findByRole('region', { name: /urgent needs/i })).toHaveTextContent('Winter blankets')
    expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveAttribute('href', '#main')
  })

  it('has one fixed photo layer behind the content and a minimal hero with the existing actions', async () => {
    mount()
    const bg = document.querySelector('.lp-bg')
    expect(bg).not.toBeNull()
    expect(bg).toHaveAttribute('aria-hidden', 'true')
    expect(document.querySelectorAll('img[src*="carebridge-hero"]')).toHaveLength(1)
    const hero = within(document.getElementById('home'))
    expect(hero.getByRole('link', { name: /explore needs/i })).toHaveAttribute('href', '/login')
    expect(hero.getByRole('link', { name: /become a volunteer/i })).toHaveAttribute('href', '/register?role=volunteer')
    expect(screen.getByRole('navigation', { name: /^main$/i })).toHaveTextContent(/how it works/i)
  })

  it('the header sun/moon button switches theme and saves the choice', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: /switch to dark mode/i }))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('cb_theme')).toBe('dark')
    await user.click(screen.getByRole('button', { name: /switch to light mode/i }))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('cb_theme')).toBe('light')
  })

  it('a saved choice wins; a first visit follows the operating system', async () => {
    localStorage.setItem('cb_theme', 'dark')
    mount()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('first visit with a dark operating system starts in dark mode', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener() {}, removeEventListener() {} })
    mount()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('cb_theme')).toBeNull()
  })
})
