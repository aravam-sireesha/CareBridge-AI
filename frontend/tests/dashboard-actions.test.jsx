// Every dashboard action must open a real page that the role is allowed to see. Reads the real src/App.jsx.
import fs from 'node:fs'
import { describe, it, expect } from 'vitest'
import { DASHBOARD_ACTIONS } from '../src/lib/dashboardActions.js'
import { CAREER_ENABLED } from '../src/lib/features.js'

const ALL = ['admin', 'organization', 'donor', 'volunteer']
const read = (rel) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')

function routeTable() {
  const rows = []
  for (const line of read('../src/App.jsx').split('\n')) {
    const t = line.trim()
    if (t.startsWith('//') || t.startsWith('{/*')) continue
    const m = t.match(/<Route path="([^"]+)" element=\{(.*)\} \/>/)
    if (!m || m[1] === '*') continue
    const [, path, el] = m
    let roles = ALL
    if (el.startsWith('adminGuard(')) roles = ['admin']
    else if (el.startsWith('guard(')) { const r = el.match(/\[([^\]]*)\]/); if (r) roles = r[1].split(',').map((x) => x.trim().replace(/'/g, '')).filter(Boolean) }
    rows.push({ path, roles, redirect: el.startsWith('<Navigate') })
  }
  return rows
}
const find = (rows, url) => {
  const p = url.split('?')[0]
  return rows.find((r) => new RegExp('^' + r.path.replace(/:[A-Za-z]+/g, '[^/]+') + '$').test(p))
}

describe('dashboard actions', () => {
  const rows = routeTable()

  it('the route table was actually read', () => { expect(rows.length > 30).toBe(true) })

  it('every action points at a real route', () => {
    const missing = []
    for (const [role, list] of Object.entries(DASHBOARD_ACTIONS)) for (const a of list) if (!find(rows, a.to)) missing.push(`${role}: ${a.to}`)
    expect(missing).toEqual([])
  })

  it('every action opens a page that role is allowed to see', () => {
    const forbidden = []
    for (const [role, list] of Object.entries(DASHBOARD_ACTIONS)) for (const a of list) {
      const r = find(rows, a.to)
      if (r && !r.redirect && !r.roles.includes(role)) forbidden.push(`${role}: ${a.to} (allowed: ${r.roles.join('/')})`)
    }
    expect(forbidden).toEqual([])
  })

  it('each role has exactly one primary action, and at most five actions', () => {
    for (const [role, list] of Object.entries(DASHBOARD_ACTIONS)) {
      if (!list.length) continue
      expect([role, list.filter((a) => a.primary).length]).toEqual([role, 1])
      expect(list.length <= 5).toBe(true)
    }
  })

  it('the organization can create a need straight from the dashboard', () => {
    expect(DASHBOARD_ACTIONS.organization.some((a) => a.to === '/needs?new=1' && a.primary)).toBe(true)
  })

  it('nothing links to the disabled career page unless it is switched on', () => {
    const offenders = []
    for (const f of ['../src/pages/Dashboard.jsx', '../src/pages/ChildProfile.jsx']) {
      for (const line of read(f).split('\n')) if (line.includes('/ai/career') && !line.includes('CAREER_ENABLED')) offenders.push(f)
    }
    expect(offenders).toEqual([])
    expect(CAREER_ENABLED || !find(rows, '/ai/career')).toBe(true) // disabled flag <=> no route
  })
})
