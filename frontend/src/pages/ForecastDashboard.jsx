import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import ForecastChart from '../components/ForecastChart.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { EmptyState, ErrorState, PageHeader, Skeleton, StatCard, StatSkeleton } from '../components/ui.jsx'
import { IconChart } from '../components/icons.jsx'

const pct = (v) => `${Math.round(v * 100)}%`

export default function ForecastDashboard() {
  const { data, loading, error, reload } = useAsync(() => api.adminForecastDashboard(), [])
  const [picked, setPicked] = useState(null)
  const cats = data?.categories || []
  const c = cats.find((x) => x.category === picked) || cats[0]
  const when = data?.generated_at ? new Date(`${data.generated_at}Z`).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : null
  const high = cats.filter((x) => x.shortfall?.risk === 'high').length

  return (
    <Layout title="Demand forecast">
      <PageHeader icon={IconChart} title="Demand forecast" subtitle={data ? `Expected needs per category for the ${data.horizon}. Calculated ${when}.` : 'Expected needs per category and the risk of a shortfall.'} />
      {error ? <ErrorState message={error} onRetry={reload} />
        : loading && !data ? <><StatSkeleton count={3} /><Skeleton className="mt-4 h-72 w-full" /></>
        : cats.length === 0 ? <div className="card"><EmptyState title="Not enough need history yet" text="Forecasts appear once needs have been recorded over several months." /></div>
        : (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <StatCard label="Categories at high shortfall risk" value={high} hint={`of ${cats.length} categories`} tone={high ? 'red' : 'green'} />
              <StatCard label="Expected needs, next 30 days" value={cats.reduce((a, x) => a + x.forecast.value, 0).toFixed(1)} hint="sum of the category forecasts" />
              <StatCard label="With a backtested method" value={cats.filter((x) => x.confident).length} hint="others use a simple recent average" tone="sky" />
            </div>

            <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Category">
              {cats.map((x) => (
                <button key={x.category} type="button" aria-pressed={x.category === c.category} onClick={() => setPicked(x.category)}
                  className={`rounded-full border px-3.5 py-1.5 text-xs font-semibold capitalize transition ${x.category === c.category ? 'border-teal-700 bg-teal-700 text-white' : 'border-line bg-white text-ink-muted hover:border-teal-300'}`}>{x.category}</button>
              ))}
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <section className="card p-4 lg:col-span-2" aria-label={`Forecast for ${c.category}`}>
                <h2 className="mb-1 font-display text-base font-semibold text-ink"><span className="capitalize">{c.category}</span>: needs per 30-day period</h2>
                <ForecastChart history={c.history} forecast={c.forecast} category={c.category} />
                <details className="mt-2 text-xs text-ink-muted"><summary className="cursor-pointer font-semibold">View the numbers</summary>
                  <table className="mt-2 w-full max-w-sm text-left"><thead><tr><th className="py-1 font-semibold">Period</th><th className="font-semibold">Needs</th></tr></thead>
                    <tbody>{c.history.map((p) => <tr key={p.label} className="border-t border-line"><td className="py-1">{p.label}</td><td>{p.value}</td></tr>)}
                      <tr className="border-t border-line font-semibold text-ink"><td className="py-1">{c.forecast.label} (forecast)</td><td>{c.forecast.value}</td></tr></tbody></table></details>
              </section>

              <div className="space-y-4">
                <section className="card p-4" aria-label="Forecast details">
                  <h2 className="font-display text-base font-semibold text-ink">Forecast</h2>
                  <p className="mt-1 font-display text-3xl font-semibold text-ink">{c.forecast.value}<span className="ml-1.5 text-sm font-normal text-ink-muted">needs</span></p>
                  <p className="mt-1 text-sm text-ink-muted">{c.forecast.band
                    ? `Typically within ${c.forecast.band.lower} to ${c.forecast.band.upper}: past forecasts by this method were that close about 4 times in 5 (based on ${c.forecast.band.n} past forecasts).`
                    : 'No range is shown: at least 5 past forecasts are needed to measure how far off this method usually is.'}</p>
                  <dl className="mt-3 space-y-1.5 text-sm">
                    <div className="flex justify-between gap-3"><dt className="text-ink-muted">Method</dt><dd className="text-right font-medium capitalize">{c.method}</dd></div>
                    <div className="flex justify-between gap-3"><dt className="text-ink-muted">History</dt><dd className="font-medium">{c.periods} period{c.periods === 1 ? '' : 's'}</dd></div>
                    {c.confident && <div className="flex justify-between gap-3"><dt className="text-ink-muted">Past error (MAE)</dt><dd className="font-medium">{c.backtest_mae} vs {c.naive_mae} for “same as last period”</dd></div>}
                  </dl>
                  <p className="mt-2 text-xs text-ink-muted">{c.confident ? (c.skill_vs_naive > 0 ? `Backtesting shows this method beats “same as last period” by ${pct(c.skill_vs_naive)}.` : 'Backtesting did not find a method better than “same as last period”, so that is what is used.') : (c.reason || 'Not enough history for a backtest.')}</p>
                </section>

                <section className="card p-4" aria-label="Shortfall risk">
                  <div className="flex items-center justify-between gap-2"><h2 className="font-display text-base font-semibold text-ink">Shortfall risk</h2>{c.shortfall && <StatusBadge status={c.shortfall.risk} />}</div>
                  {c.shortfall ? (
                    <>
                      <dl className="mt-2 space-y-1.5 text-sm">
                        <div className="flex justify-between"><dt className="text-ink-muted">Expected units</dt><dd className="font-medium">{c.shortfall.expected_units}</dd></div>
                        <div className="flex justify-between"><dt className="text-ink-muted">In stock</dt><dd className="font-medium">{c.shortfall.stock_units}</dd></div>
                        <div className="flex justify-between"><dt className="text-ink-muted">Gap</dt><dd className="font-medium">{c.shortfall.gap_units}</dd></div>
                        <div className="flex justify-between"><dt className="text-ink-muted">Interested donors</dt><dd className="font-medium">{c.shortfall.matching_donors}</dd></div>
                      </dl>
                      {c.shortfall.notes.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-muted">{c.shortfall.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
                    </>
                  ) : <p className="mt-2 text-sm text-ink-muted">Risk cannot be calculated for this category right now: the supply data needed for it is not available.</p>}
                </section>
              </div>
            </div>

            <details className="card mt-4 p-4 text-sm text-ink-muted"><summary className="cursor-pointer font-semibold text-ink">How to read this, and its limits</summary>
              <p className="mt-2">{data.risk_method}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">{data.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details>
          </>
        )}
    </Layout>
  )
}
