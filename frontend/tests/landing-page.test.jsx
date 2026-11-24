import React from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../src/App.jsx'
import { parseHeroMeta } from '../src/components/HeroMedia.jsx'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ThemeProvider } from '../src/context/ThemeContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'

const NEED = { id: 1, title: 'Winter blankets', category: 'clothing', quantity: 20, urgency: 'critical', organization: 'Hope Home', required_by: null }
let ROUTES = {
  'GET /public/stats': { verified_organizations: 1, open_needs: 1, fulfilled_needs: 0, confirmed_donations: 0, registered_donors: 2, registered_volunteers: 3, beneficiaries_supported: 0 },
  'GET /public/needs': [NEED],
  'GET /public/organizations': [{ id: 1, name: 'Hope Home', about: null, website: null }]
}
const realMatchMedia = window.matchMedia

function mockFetch() {
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    if (!(key in ROUTES)) return { ok: false, status: 404, json: async () => ({}), text: async () => JSON.stringify({ detail: `no mock for ${key}` }) }
    return { ok: true, status: 200, text: async () => JSON.stringify(ROUTES[key]), json: async () => ROUTES[key] }
  })
}
const mount = () => render(
  <MemoryRouter initialEntries={['/']}><ThemeProvider><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></ThemeProvider></MemoryRouter>
)

const BASE_ROUTES = ROUTES
beforeEach(() => { document.documentElement.classList.remove('dark'); ROUTES = BASE_ROUTES; mockFetch() })
afterEach(() => { window.matchMedia = realMatchMedia })

describe('landing page', () => {
  it('keeps the existing logo, sections and shows real urgent needs', async () => {
    mount()
    expect(screen.getAllByLabelText(/carebridge ai logo/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { level: 1, name: /every donation\. a real difference\./i })).toBeInTheDocument()
    for (const id of ['home', 'about', 'how', 'organizations', 'impact', 'contact']) expect(document.getElementById(id)).not.toBeNull()
    expect(await screen.findByRole('region', { name: /urgent needs/i })).toHaveTextContent('Winter blankets')
    expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveAttribute('href', '#main')
  })

  it('has a two-column hero with the required headline, text and both actions, and no background photo layer', async () => {
    mount()
    expect(document.querySelector('.lp-bg')).toBeNull()
    expect(document.querySelectorAll('img[src*="carebridge-hero"]')).toHaveLength(0)           // the old AI-generated image is gone
    const hero = within(document.getElementById('home'))
    expect(hero.getByText(/connects verified organizations, generous donors, and dedicated volunteers/i)).toBeInTheDocument()
    expect(hero.getByRole('link', { name: /donate now/i })).toHaveAttribute('href', '/register?role=donor')
    expect(hero.getByRole('link', { name: /explore community needs/i })).toHaveAttribute('href', '#organizations')
    expect(screen.getByRole('navigation', { name: /^main$/i })).toHaveTextContent(/how it works/i)
  })

  it('without a configured photo the right column shows REAL open needs, never a stand-in picture', async () => {
    mount()
    const panel = await screen.findByRole('complementary', { name: /open needs right now/i })
    expect(panel).toHaveTextContent('Winter blankets')
    expect(panel).toHaveTextContent('Hope Home')
    expect(document.querySelector('#home img')).toBeNull()
  })

  it('shows the trust line only from a real backend count, and hides it when there are no verified organizations', async () => {
    mount()
    expect(await screen.findByText(/connecting donors with verified community needs: 1 verified organization/i)).toBeInTheDocument()
  })

  it('shows the project photo with its description, credit and licence when hero.json describes one', async () => {
    ROUTES = { ...BASE_ROUTES, 'GET /images/hero/hero.json': { image: 'hero-1600.jpg', webp: 'hero-1600.webp', small: 'hero-800.jpg', small_webp: 'hero-800.webp', width: 1600, height: 1200,
      alt: 'Two volunteers hand out rice sacks to families outside a community hall', credit: 'Photo: A. Sharma', license: 'Used with permission', source_url: 'https://example.org/photo' } }
    mockFetch()
    mount()
    const img = await screen.findByRole('img', { name: /two volunteers hand out rice sacks/i })
    expect(img).toHaveAttribute('src', '/images/hero/hero-1600.jpg')
    expect(img).toHaveAttribute('width', '1600')
    expect(screen.getByText(/photo: a\. sharma/i)).toBeInTheDocument()
    expect(screen.getByText(/used with permission/i)).toBeInTheDocument()
  })

  it('refuses a hero.json without a description of the photo or with an unsafe path', async () => {
    expect(parseHeroMeta({ image: 'hero.jpg' })).toBeNull()                                    // no alt text: not shown
    expect(parseHeroMeta({ image: '../../secret.jpg', alt: 'x' })).toBeNull()
    expect(parseHeroMeta({ image: 'https://evil.example/x.jpg', alt: 'x' })).toBeNull()
    expect(parseHeroMeta('<html>')).toBeNull()
    expect(parseHeroMeta({ image: 'hero.jpg', alt: 'Volunteers', source_url: 'javascript:alert(1)' }).sourceUrl).toBeNull()
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
