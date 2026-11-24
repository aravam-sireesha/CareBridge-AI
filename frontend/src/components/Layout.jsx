import React, { createContext, useContext, useEffect, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useAuth, useLogout } from '../context/AuthContext.jsx'
import { api } from '../api/client.js'
import { useLiveStatus } from '../hooks/useLiveEvent.js'
import Logo from './Logo.jsx'
import StatusBadge from './StatusBadge.jsx'
import ProfileMenu, { ThemeToggle } from './ProfileMenu.jsx'
import Breadcrumbs from './Breadcrumbs.jsx'
import {
  IconDashboard, IconChildren, IconNeeds, IconDonations, IconPeople, IconAlert, IconShield, IconHand,
  IconBriefcase, IconAssistant, IconSettings, IconLogout, IconMenu, IconX, IconHome, IconKey, IconSpark, IconBuilding, IconCheck, IconChart, IconDatabase, IconBook,
  IconBell, IconUpload, IconChevronLeft, IconChevronRight, IconFile, IconPin
} from './icons.jsx'

const ALL = ['admin', 'organization', 'donor', 'volunteer']
const NAV = [
  { group: 'Overview', items: [
    { to: '/dashboard', label: 'Dashboard', icon: IconDashboard, roles: ['organization', 'donor', 'volunteer'] },
    { to: '/admin', end: true, label: 'Admin Dashboard', icon: IconDashboard, roles: ['admin'] }
  ] },
  {
    group: 'Platform management', items: [
      { to: '/admin/verification', label: 'Organization Verification', icon: IconBuilding, roles: ['admin'] },
      { to: '/admin/anomalies', label: 'Anomaly Detection', icon: IconAlert, roles: ['admin'] },
      { to: '/admin/users', label: 'Users & Roles', icon: IconKey, roles: ['admin'] },
      { to: '/admin/people', label: 'Volunteers & Donors', icon: IconPeople, roles: ['admin'] },
      { to: '/children', label: 'Children', icon: IconChildren, roles: ['admin', 'organization'] },
      { to: '/needs/bulk', label: 'Bulk upload', icon: IconUpload, roles: ['admin', 'organization'] },
      { to: '/needs', label: 'Needs', labels: { organization: 'My needs' }, icon: IconNeeds, roles: ['organization', 'donor', 'volunteer'] },
      { to: '/donations', label: 'Donations', icon: IconDonations, roles: ['admin', 'organization', 'donor'] },
      { to: '/deliveries', label: 'Deliveries', labels: { donor: 'My deliveries', volunteer: 'My tasks', admin: 'Delivery approvals' }, icon: IconHand, roles: ALL },
      { to: '/people', label: 'Donors & volunteers', icon: IconPeople, roles: ['organization'] },
      { to: '/resources', label: 'Resources', icon: IconDatabase, roles: ['organization'] },
      { to: '/notifications', label: 'Notifications', icon: IconBell, roles: ALL },
      { to: '/reports', label: 'Reports', icon: IconFile, roles: ['admin', 'organization'] }
    ]
  },
  {
    group: 'Review & AI', items: [
      { to: '/admin/review', label: 'Review queue', icon: IconCheck, roles: ['admin'] },
      { to: '/ai/fraud', label: 'Fraud flags', icon: IconShield, roles: ['admin'] },
      { to: '/ai/needs-alerts', label: 'Need alerts', icon: IconAlert, roles: ['admin', 'organization'] },
      { to: '/ai/matching', label: 'Matching review', labels: { organization: 'AI matching' }, icon: IconHand, roles: ['admin', 'organization'] },
      //{ to: '/ai/career', label: 'Career guidance', icon: IconBriefcase, roles: ['admin', 'organization'] },
      { to: '/admin/ai-lab', label: 'AI Lab', icon: IconAssistant, roles: ['admin'], badge: 'AI' },
      { to: '/admin/recommend', label: 'AI suggestion hub', icon: IconSpark, roles: ['admin'], badge: 'ML' },
      { to: '/admin/suggestions', label: 'Donor suggestions', icon: IconDonations, roles: ['admin'] },
      { to: '/admin/overview', label: 'Overview & AI model', icon: IconChart, roles: ['admin'] },
      { to: '/admin/forecast', label: 'Demand forecast', icon: IconChart, roles: ['admin'] },
      { to: '/admin/llm', label: 'Language model settings', icon: IconKey, roles: ['admin'] },
      { to: '/assistant', label: 'AI assistant', icon: IconAssistant, roles: ALL, badge: 'Chat' },
      { to: '/agent', label: 'AI agent', icon: IconSpark, roles: ALL, badge: 'Agent' }
    ]
  },
  {
    group: 'Records', items: [
      { to: '/map', label: 'Live map', icon: IconPin, roles: ALL },
      { to: '/admin/map', label: 'Map overview', icon: IconPin, roles: ['admin'] },
      { to: '/admin/needs', label: 'All needs', icon: IconNeeds, roles: ['admin'] },
      { to: '/admin/donors', label: 'All donors', icon: IconDonations, roles: ['admin'] },
      { to: '/admin/volunteers', label: 'All volunteers', icon: IconPeople, roles: ['admin'] },
      { to: '/admin/resources', label: 'Resources', icon: IconDatabase, roles: ['admin'] },
      { to: '/admin/organizations', label: 'Organizations', icon: IconBuilding, roles: ['admin'] }
    ]
  },
  {
    group: 'Administration', items: [
      { to: '/admin/team', label: 'Administrators', icon: IconPeople, roles: ['admin'] },
      { to: '/admin/audit', label: 'Audit trail', icon: IconShield, roles: ['admin'] },
      { to: '/settings', label: 'Settings', icon: IconSettings, roles: ALL },
      { to: '/guide', label: 'How it works', icon: IconBook, roles: ALL }
    ]
  }
]

const flatNav = () => NAV.flatMap((g) => g.items)
/** An item can show a different name to one role (an organization sees "My needs", a donor sees "Needs"). */
const labelOf = (item, role) => (item.labels && item.labels[role]) || item.label

/** Unread count in the header. Polls quietly; any failure just hides the number (never a toast, never a crash). */
function NotificationBell() {
  const [unread, setUnread] = useState(null)
  const liveStatus = useLiveStatus()
  const live = liveStatus === 'open'
  useEffect(() => {
    let alive = true
    const load = () => { if (!document.hidden) api.unreadCount().then((r) => alive && setUnread(r?.unread ?? 0)).catch(() => {}) }
    load()
    // While the live connection works the server tells us about new notifications, so polling is only a slow safety net.
    const t = setInterval(load, live ? 300000 : 60000)
    const onFocus = () => load()
    window.addEventListener('cb:notifications-changed', onFocus)
    window.addEventListener('focus', onFocus)
    return () => { alive = false; clearInterval(t); window.removeEventListener('cb:notifications-changed', onFocus); window.removeEventListener('focus', onFocus) }
  }, [live])
  const label = unread ? `Notifications, ${unread} unread` : 'Notifications'
  return (
    <Link to="/notifications" aria-label={label} title={label} className="relative rounded-xl p-2.5 text-ink-muted transition hover:bg-teal-50 hover:text-teal-700">
      <IconBell />
      {unread > 0 && <span className="absolute right-1 top-1 grid min-w-[1.1rem] place-items-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-4 text-white" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
    </Link>
  )
}

/** When a page is shown inside another page (e.g. as a tab) it must not draw a second frame. */
export const EmbeddedContext = createContext(false)

function ApiStatus() {
  const [state, setState] = useState('checking')
  useEffect(() => {
    let alive = true
    const check = () => api.ping().then(() => alive && setState('up')).catch(() => alive && setState('down'))
    check()
    const t = setInterval(check, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  const label = { checking: 'Checking API…', up: 'API online', down: 'API offline' }[state]
  const dot = { checking: 'bg-amber-400', up: 'bg-green-500', down: 'bg-red-500' }[state]
  return (
    <span className="hidden items-center gap-2 px-2 py-1.5 text-xs font-medium text-ink-muted xl:inline-flex" title="Backend connection">
      <span className={`h-2 w-2 rounded-full ${dot} `} />{label}
    </span>
  )
}

function SidebarContent({ role, onNavigate, collapsed = false }) {
  const location = useLocation()
  const [closed, setClosed] = useState(() => { try { return JSON.parse(localStorage.getItem('cb_nav_closed') || '[]') } catch { return [] } })
  const toggle = (name) => setClosed((c) => { const next = c.includes(name) ? c.filter((x) => x !== name) : [...c, name]; try { localStorage.setItem('cb_nav_closed', JSON.stringify(next)) } catch { /* private mode */ } return next })
  const isHere = (i) => (i.end ? location.pathname === i.to : location.pathname === i.to || location.pathname.startsWith(`${i.to}/`))
  return (
    <>
      <div className={collapsed ? 'px-3 py-4' : 'px-4 py-4'}><Link to={role === 'admin' ? '/admin' : '/'} onClick={onNavigate} aria-label={role === 'admin' ? 'CareBridge AI administration home' : 'CareBridge AI home'}><Logo size={34} compact={collapsed} /></Link></div>
      <nav className="min-h-0 flex-1 space-y-3 overflow-y-auto px-2.5 pb-3" aria-label="Main">
        {NAV.map((g) => {
          const items = g.items.filter((i) => i.roles.includes(role))
          if (!items.length) return null
          const hasActive = items.some(isHere)
          const open = collapsed || hasActive || !closed.includes(g.group)   // the group you are in is always open
          return (
            <div key={g.group}>
              {collapsed ? <p className="sr-only">{g.group}</p> : (
                <button type="button" onClick={() => toggle(g.group)} aria-expanded={open} disabled={hasActive}
                  className="mb-1 flex w-full items-center justify-between rounded-md px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/70 hover:text-ink-muted disabled:cursor-default">
                  {g.group}{!hasActive && <IconChevronRight className={`h-3 w-3 transition ${open ? 'rotate-90' : ''}`} />}
                </button>
              )}
              {open && (
                <div className="space-y-0.5">
                  {items.map((item) => (
                    <NavLink key={item.to} to={item.to} end={item.end} onClick={onNavigate}
                      className={({ isActive }) => `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors ${isActive ? 'bg-teal-50 text-teal-800 ring-1 ring-teal-100' : 'text-ink-muted hover:bg-bg hover:text-ink'} ${collapsed ? 'justify-center' : ''}`} title={collapsed ? labelOf(item, role) : undefined}>
                      <item.icon className="h-[18px] w-[18px] shrink-0" />
                      <span className={collapsed ? 'sr-only' : 'flex-1'}>{labelOf(item, role)}</span>
                      {item.badge && !collapsed && <span className="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700">{item.badge}</span>}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </nav>
      {!collapsed && <p className="mx-2.5 border-t border-line px-1.5 pb-3 pt-3 text-[11px] leading-snug text-ink-muted/70">Connecting Hearts, Fulfilling Needs.<br />AI recommends. Administrators decide.</p>}
    </>
  )
}

export default function Layout({ title = 'CareBridge', children, fullScreen = false }) {
  const { user } = useAuth()
  const handleLogout = useLogout()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const embedded = useContext(EmbeddedContext)
  const [prefCollapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('cb_sidebar') === 'collapsed' } catch { return false } })
  const collapsed = fullScreen || prefCollapsed   // focused pages (the chat) use the slim icon rail on desktop
  const toggleSidebar = () => setCollapsed((c) => { const next = !c; try { localStorage.setItem('cb_sidebar', next ? 'collapsed' : 'open') } catch { /* private mode */ } return next })
  const here = flatNav().filter((i) => i.roles.includes(user?.role)).find((i) => (i.end ? location.pathname === i.to : location.pathname === i.to || location.pathname.startsWith(`${i.to}/`)))
  const crumbs = [{ label: user?.role === 'admin' ? 'Administration' : 'Dashboard', to: user?.role === 'admin' ? '/admin' : '/dashboard' }, ...(here && here.to !== '/admin' && here.to !== '/dashboard' ? [{ label: labelOf(here, user?.role) }] : [])]

  useEffect(() => { document.title = `${title} · CareBridge AI` }, [title])
  useEffect(() => { setOpen(false) }, [location.pathname])


  if (embedded) return <>{children}</>

  return (
    <div className={`flex bg-bg ${fullScreen ? 'h-screen overflow-hidden' : 'min-h-screen'}`}>
      <aside className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-white transition-[width] duration-200 lg:flex ${collapsed ? 'w-[4rem]' : 'w-60'}`}>
        <SidebarContent role={user?.role} collapsed={collapsed} />
        {!fullScreen && <button type="button" onClick={toggleSidebar} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed}
          className="mx-2.5 mb-3 flex items-center justify-center gap-2 rounded-lg border border-line py-1.5 text-xs font-semibold text-ink-muted transition hover:bg-teal-50 hover:text-teal-700">
          {collapsed ? <IconChevronRight className="h-4 w-4" /> : <><IconChevronLeft className="h-4 w-4" /> Collapse</>}
        </button>}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside className="animate-pop absolute left-0 top-0 flex h-full w-72 flex-col bg-white shadow-lift">
            <button onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-lg p-1.5 text-ink-muted hover:bg-bg" aria-label="Close menu"><IconX /></button>
            <SidebarContent role={user?.role} onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className={`flex min-w-0 flex-1 flex-col ${fullScreen ? 'min-h-0' : ''}`}>
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-white/85 px-4 py-2 backdrop-blur sm:px-6">
          <div className="flex items-center gap-3">
            <button onClick={() => setOpen(true)} className="rounded-xl p-2 text-ink hover:bg-bg lg:hidden" aria-label="Open menu"><IconMenu /></button>
            <Link to="/" className="hidden items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-teal-50 hover:text-teal-700 sm:inline-flex"><IconHome className="h-4 w-4" /> Home</Link>
          </div>
          <div className="flex items-center gap-3">
            <ApiStatus />
            <StatusBadge status={user?.role} />
            <NotificationBell />
            <ThemeToggle />
            <ProfileMenu />
            <button onClick={handleLogout} className="rounded-xl p-2.5 text-ink-muted transition hover:bg-red-50 hover:text-red-600" title="Log out" aria-label="Log out"><IconLogout /></button>
          </div>
        </header>
        {fullScreen
          ? <main className="flex min-h-0 flex-1 flex-col">{children}</main>
          : <main className="flex-1 p-4 sm:p-6"><div className="mx-auto max-w-6xl"><Breadcrumbs crumbs={crumbs} />{children}</div></main>}
      </div>
    </div>
  )
}
