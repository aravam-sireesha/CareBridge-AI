import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'

const ms = (n) => (n == null ? '–' : `${n} ms`)

function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b py-2.5 text-sm last:border-0" style={{ borderColor: 'var(--ai-line)' }}>
      <dt className="ai-muted">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}

export default function AdminLLM() {
  const status = useAsync(() => api.adminLlmStatus(), [])
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)
  const s = status.data

  const test = async () => {
    setTesting(true); setResult(null)
    try { setResult(await api.adminLlmTest()) } catch (e) { setResult({ ok: false, message: e.message }) } finally { setTesting(false); status.reload({ silent: true }) }
  }

  return (
    <Layout title="Language model settings">
      <div className="ai-root">
        <div className="mb-5">
          <h1 className="font-display text-xl font-semibold">Language model settings</h1>
          <p className="ai-muted mt-1 text-sm">The model that writes assistant answers. Credentials are set on the server and are never shown here or sent to the browser.</p>
        </div>
        {status.loading && <p className="ai-muted text-sm" role="status">Loading…</p>}
        {status.error && <p className="ai-note bad" role="alert">{status.error}</p>}
        {s && (
          <div className="grid gap-5 lg:grid-cols-2">
            <section className="ai-panel p-5" aria-label="Connection">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold">Connection</h2>
                <span className={`ai-badge ${s.configured ? 'ok' : 'warn'}`}>{s.configured ? 'Configured' : 'Not configured'}</span>
              </div>
              <dl>
                <Row label="Provider">{s.provider_host || '–'}</Row>
                <Row label="Chat model">{s.model || '–'}</Row>
                <Row label="Fast model (short questions)">{s.fast_model || '–'}</Row>
                <Row label="API key">{s.configured ? (s.key_required ? (s.api_key || 'Set') : 'Not required (local server)') : '–'}</Row>
                <Row label="Embedding model">{s.embedding_model}</Row>
                <Row label="Timeout">{s.timeout_seconds ? `${s.timeout_seconds} s` : '–'}</Row>
                <Row label="Retries on rate limit or server error">{s.max_retries}</Row>
                <Row label="Daily request limit">{s.daily_request_limit ?? 'None'}</Row>
              </dl>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="button" className="ai-primary" onClick={test} disabled={testing}>{testing ? 'Testing…' : 'Test connection'}</button>
                {result && <p className={`ai-note ${result.ok ? '' : 'bad'}`} style={result.ok ? { background: 'var(--ai-ok-bg)', color: 'var(--ai-ok)' } : undefined} role="status">{result.ok ? `Connected: ${result.model} answered in ${ms(result.latency_ms)}.` : result.message}</p>}
              </div>
            </section>

            <section className="ai-panel p-5" aria-label="Usage">
              <h2 className="mb-2 text-sm font-semibold">Usage</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="ai-muted text-left text-xs"><th className="py-1.5 font-medium">Period</th><th className="font-medium">Requests</th><th className="font-medium">Failed</th><th className="font-medium">Avg latency</th></tr></thead>
                  <tbody>
                    {[['Today', s.usage.today], ['Last 24 hours', s.usage.last_24h], ['Last 7 days', s.usage.last_7d]].map(([label, u]) => (
                      <tr key={label} className="border-t" style={{ borderColor: 'var(--ai-line)' }}><td className="py-2">{label}</td><td>{u.requests}</td><td>{u.failures}</td><td>{ms(u.avg_latency_ms)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="ai-faint mt-3 text-xs">{s.cost_note}</p>
            </section>

            <section className="ai-panel p-5 lg:col-span-2" aria-label="How to configure">
              <h2 className="mb-2 text-sm font-semibold">How to change the model or rotate the key</h2>
              <ol className="ai-muted list-decimal space-y-1 pl-5 text-sm">
                <li>Edit the server's environment (the <code className="ai-md-code">.env</code> file or your secret manager): <code className="ai-md-code">LLM_API_KEY</code>, <code className="ai-md-code">LLM_MODEL</code>, optionally <code className="ai-md-code">LLM_BASE_URL</code> (for example a local Ollama server) and <code className="ai-md-code">LLM_DAILY_REQUEST_LIMIT</code>.</li>
                <li>Restart the backend.</li>
                <li>Return here and press <strong>Test connection</strong>. The result is real: it sends one tiny request to the configured model.</li>
              </ol>
            </section>
          </div>
        )}
      </div>
    </Layout>
  )
}
