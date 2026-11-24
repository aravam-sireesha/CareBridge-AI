import React, { useEffect, useMemo, useState } from 'react'
import { useMediaQuery } from '../hooks/useMediaQuery.js'
import Drawer from './Drawer.jsx'
import { EmptyState, ErrorState, TableSkeleton } from './ui.jsx'

const norm = (v) => String(v ?? '').toLowerCase()
const cmp = (a, b) => (typeof a === 'number' && typeof b === 'number' ? a - b : String(a ?? '').localeCompare(String(b ?? ''), undefined, { numeric: true, sensitivity: 'base' }))

/**
 * The one table for the whole app.
 *  columns   [{ key, header, render?(row), sortValue?(row)|true, searchable?, hideOnMobile?, className? }]
 *  filters   [{ key, label, options: [{ value, label }], get?(row) }]  exact-match dropdowns
 *  actions   (row) => node      buttons shown at the end of each row (and card)
 *  detail    (row) => node      when given, a row opens a side drawer with this content
 * Rows are filtered, sorted and paged in the browser, so pass the records already authorised by the server.
 * Small screens get one readable card per record instead of a wide table. */
export default function DataTable({
  columns, rows, rowKey = (r) => r.id, loading = false, error = null, onRetry, searchPlaceholder = 'Search', filters = [], pageSize = 10,
  initialSort = null, actions, detail, detailTitle = (r) => String(rowKey(r)), emptyTitle = 'Nothing to show yet', emptyText, emptyAction, caption, label = 'Records', openId = null
}) {
  const mobile = useMediaQuery('(max-width: 767px)')
  const [query, setQuery] = useState('')
  const [filterValues, setFilterValues] = useState({})
  const [sort, setSort] = useState(initialSort)           // { key, dir: 'asc' | 'desc' }
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)

  const cellText = (c, r) => (c.sortValue && typeof c.sortValue === 'function' ? c.sortValue(r) : r[c.key])
  const visible = useMemo(() => {
    const q = norm(query).trim()
    let out = (rows || []).filter((r) => filters.every((f) => { const v = filterValues[f.key]; return !v || String(f.get ? f.get(r) : r[f.key]) === v }))
    if (q) out = out.filter((r) => columns.some((c) => c.searchable !== false && norm(cellText(c, r)).includes(q)))
    if (sort) {
      const col = columns.find((c) => c.key === sort.key)
      if (col) out = [...out].sort((a, b) => (sort.dir === 'asc' ? 1 : -1) * cmp(cellText(col, a), cellText(col, b)))
    }
    return out
  }, [rows, query, filterValues, sort, columns, filters])

  useEffect(() => { setPage(1) }, [query, filterValues, sort, rows])
  // a link such as /needs?open=12 opens that record's details once the rows have loaded
  useEffect(() => {
    if (openId == null || !rows || !detail) return
    const hit = rows.find((r) => String(rowKey(r)) === String(openId))
    if (hit) setOpen(hit)
  }, [openId, rows]) // eslint-disable-line react-hooks/exhaustive-deps
  const pages = Math.max(1, Math.ceil(visible.length / pageSize))
  const current = Math.min(page, pages)
  const slice = visible.slice((current - 1) * pageSize, current * pageSize)
  const toggleSort = (c) => { if (!c.sortValue && c.sortable !== true) return; setSort((s) => (s?.key === c.key ? (s.dir === 'asc' ? { key: c.key, dir: 'desc' } : null) : { key: c.key, dir: 'asc' })) }
  const sortable = (c) => c.sortValue || c.sortable === true
  const hasControls = (rows?.length || 0) > 0 || query || Object.values(filterValues).some(Boolean)
  const activeFilters = Boolean(query) || Object.values(filterValues).some(Boolean)

  const body = () => {
    if (error) return <ErrorState message={typeof error === 'string' ? error : 'These records could not be loaded.'} onRetry={onRetry} />
    if (loading && !rows) return <div role="status" aria-live="polite"><span className="sr-only">Loading {label.toLowerCase()}…</span><TableSkeleton rows={Math.min(pageSize, 6)} cols={Math.max(3, columns.length)} /></div>
    if (!rows?.length) return <EmptyState title={emptyTitle} text={emptyText} action={emptyAction} />
    if (!visible.length) return <EmptyState title="No matching records" text="Try a different search or clear the filters." action={<button type="button" className="btn-soft" onClick={() => { setQuery(''); setFilterValues({}) }}>Clear search and filters</button>} />
    if (mobile) {
      return (
        <ul className="space-y-3" aria-label={label}>
          {slice.map((r) => (
            <li key={rowKey(r)} className="card p-4">
              <dl className="space-y-1.5 text-sm">
                {columns.filter((c) => !c.hideOnMobile).map((c) => (
                  <div key={c.key} className="flex items-start justify-between gap-3"><dt className="shrink-0 text-ink-muted">{c.header}</dt><dd className="min-w-0 text-right font-medium text-ink">{c.render ? c.render(r) : String(r[c.key] ?? '–')}</dd></div>
                ))}
              </dl>
              {(detail || actions) && <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">{actions?.(r)}{detail && <button type="button" className="btn-soft" onClick={() => setOpen(r)}>Details</button>}</div>}
            </li>
          ))}
        </ul>
      )
    }
    return (
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[36rem] text-left text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-bg text-xs uppercase tracking-wide text-ink-muted">
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" className={`px-3 py-2.5 font-semibold ${c.className || ''}`} aria-sort={sort?.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : sortable(c) ? 'none' : undefined}>
                  {sortable(c)
                    ? <button type="button" onClick={() => toggleSort(c)} className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink">{c.header}<span aria-hidden="true" className="text-[10px]">{sort?.key === c.key ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}</span></button>
                    : c.header}
                </th>
              ))}
              {(actions || detail) && <th scope="col" className="px-3 py-2.5 text-right font-semibold"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line bg-white">
            {slice.map((r) => (
              <tr key={rowKey(r)} className="hover:bg-bg/60">
                {columns.map((c) => <td key={c.key} className={`px-3 py-2.5 align-middle text-ink ${c.className || ''}`}>{c.render ? c.render(r) : String(r[c.key] ?? '–')}</td>)}
                {(actions || detail) && <td className="px-3 py-2.5 text-right"><div className="flex items-center justify-end gap-2">{actions?.(r)}{detail && <button type="button" className="btn-soft" onClick={() => setOpen(r)} aria-label={`Details for ${detailTitle(r)}`}>Details</button>}</div></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div>
      {hasControls && !error && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={searchPlaceholder} aria-label={searchPlaceholder} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100 sm:w-64" />
          {filters.map((f) => (
            <select key={f.key} aria-label={f.label} value={filterValues[f.key] || ''} onChange={(e) => setFilterValues((v) => ({ ...v, [f.key]: e.target.value }))} className="rounded-lg border border-line bg-white px-2.5 py-2 text-sm text-ink outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100">
              <option value="">{f.label}: all</option>
              {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ))}
          {activeFilters && <button type="button" className="text-sm font-semibold text-teal-700 hover:underline" onClick={() => { setQuery(''); setFilterValues({}) }}>Clear</button>}
        </div>
      )}
      {body()}
      {!error && !(loading && !rows) && visible.length > pageSize && (
        <nav className="mt-3 flex items-center justify-between gap-3 text-sm" aria-label="Pagination">
          <p className="text-ink-muted" role="status">Showing {(current - 1) * pageSize + 1}–{Math.min(current * pageSize, visible.length)} of {visible.length}</p>
          <div className="flex items-center gap-2">
            <button type="button" className="btn-soft" disabled={current <= 1} onClick={() => setPage(current - 1)}>Previous</button>
            <span className="text-ink-muted">Page {current} of {pages}</span>
            <button type="button" className="btn-soft" disabled={current >= pages} onClick={() => setPage(current + 1)}>Next</button>
          </div>
        </nav>
      )}
      {detail && <Drawer open={Boolean(open)} title={open ? detailTitle(open) : ''} onClose={() => setOpen(null)}>{open && detail(open)}</Drawer>}
    </div>
  )
}
