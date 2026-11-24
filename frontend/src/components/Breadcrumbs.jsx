import React from 'react'
import { Link } from 'react-router-dom'
import { IconChevronRight } from './icons.jsx'

/** crumbs: [{ label, to? }]. The last crumb is the current page. */
export default function Breadcrumbs({ crumbs }) {
  if (!crumbs?.length) return null
  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-ink-muted">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1
          return (
            <li key={`${c.label}-${i}`} className="flex items-center gap-1">
              {i > 0 && <IconChevronRight className="h-3 w-3" />}
              {last || !c.to ? <span aria-current={last ? 'page' : undefined} className={last ? 'font-semibold text-ink' : ''}>{c.label}</span>
                : <Link to={c.to} className="hover:text-teal-700 hover:underline">{c.label}</Link>}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
