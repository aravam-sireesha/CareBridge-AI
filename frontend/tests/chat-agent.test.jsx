import React from 'react'
import fs from 'node:fs'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../src/context/AuthContext.jsx'
import { ToastProvider } from '../src/context/ToastContext.jsx'
import { createSseParser } from '../src/lib/sse.js'
import { api } from '../src/api/client.js'
import Markdown from '../src/components/ai/Markdown.jsx'
import Assistant from '../src/pages/Assistant.jsx'
import AgentWorkspace from '../src/pages/AgentWorkspace.jsx'

const enc = new TextEncoder()
const frame = (e, d) => enc.encode(`event: ${e}\ndata: ${JSON.stringify(d)}\n\n`)
const json = (v, status = 200) => new Response(JSON.stringify(v), { status, headers: { 'Content-Type': 'application/json' } })
const USER = { id: 1, email: 'o@x.org', role: 'organization', display_name: 'Priya Nair', organization_id: 1 }

/** A streaming response the test controls: push() sends one event now, end() closes it. */
function liveStream() {
  let ctl
  const body = new ReadableStream({ start(c) { ctl = c } })
  return { res: new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }), push: (e, d) => ctl.enqueue(frame(e, d)), end: () => ctl.close() }
}

function mockApi(handlers) {
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/^\/api/, '').split('?')[0]
    const key = `${init.method || 'GET'} ${path}`
    const base = { 'GET /auth/me': USER, 'GET /': { status: 'running' }, 'GET /notifications/unread-count': { unread: 0 }, 'GET /chat/status': { llm_configured: false, knowledge_entries: 3 }, 'GET /chat/conversations': [], 'GET /agent/runs': [], 'GET /agent/examples': { examples: [] } }
    const h = key in handlers ? handlers[key] : base[key]
    if (h === undefined) return json({ detail: `no mock for ${key}` }, 404)
    return typeof h === 'function' ? h(init) : json(h)
  })
}
const mount = (el) => render(<MemoryRouter><ToastProvider><AuthProvider>{el}</AuthProvider></ToastProvider></MemoryRouter>)

beforeEach(() => {
  localStorage.setItem('cb_token', 't')
  localStorage.setItem('cb_user', JSON.stringify({ id: 1, email: 'o@x.org', role: 'organization', name: 'Priya Nair', organization_id: 1 }))
})

describe('stream plumbing', () => {
  it('parses events that arrive split across chunks, with CRLF, comments and bad JSON', () => {
    const got = []
    const p = createSseParser((n, d) => got.push([n, d]))
    const wire = 'event: token\r\ndata: {"t":"Hel"}\r\n\r\n: keep-alive\n\nevent: token\ndata: {"t":"lo"}\n\nevent: raw\ndata: not json\n\n'
    for (let i = 0; i < wire.length; i += 7) p.push(wire.slice(i, i + 7))
    expect(got).toEqual([['token', { t: 'Hel' }], ['token', { t: 'lo' }], ['raw', 'not json']])
  })

  it('renders answer markdown without ever creating raw HTML or javascript: links', () => {
    const { container } = render(<Markdown text={'**bold** [1] <img src=x onerror=alert(1)> [bad](javascript:alert(1))\n\n- a\n- b\n\n| A | B |\n|---|---|\n| 1 | 2 |'} citations={['Policy']} />)
    expect(container.querySelector('strong')).toHaveTextContent('bold')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="javascript"]')).toBeNull()
    expect(container.querySelector('table')).not.toBeNull()
    expect(container.querySelector('.ai-cite')).toHaveAttribute('title', 'Source 1: Policy')
  })
})

describe('streaming chat', () => {
  it('shows the first words while the stream is still open, then just the answer: no timings, no mode labels', async () => {
    const stream = liveStream()
    mockApi({ 'POST /chat/stream': () => stream.res })
    const user = userEvent.setup()
    mount(<Assistant />)
    expect(await screen.findByText(/how can i help you today/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/your question/i), 'What is machine learning?')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByRole('button', { name: /stop generating/i })).toBeInTheDocument()
    await act(async () => { stream.push('conversation', { conversation_id: 9, title: 'ML' }); stream.push('token', { t: 'Machine learning is ' }) })
    expect(await screen.findByText(/machine learning is/i)).toBeInTheDocument()           // visible although the answer is not finished
    await act(async () => { stream.push('token', { t: 'learning from data.' }); stream.push('done', { message_id: 5, route: 'general', mode: 'llm_general', validation: {}, follow_ups: [], timings: { first_token_ms: 20, total_ms: 90 } }); stream.end() })
    expect(await screen.findByText(/learning from data/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^send$/i })).toBeInTheDocument()
    expect(screen.queryByText(/first words|ms\b|language model was used|from your data|generated/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/sources \(/i)).not.toBeInTheDocument()                     // a general answer has no sources panel
  })

  it('offers the suggested prompts and sends one when clicked', async () => {
    const stream = liveStream()
    mockApi({ 'POST /chat/stream': (init) => { stream.body = JSON.parse(init.body); return stream.res } })
    const user = userEvent.setup()
    mount(<Assistant />)
    await user.click(await screen.findByRole('button', { name: /what is artificial intelligence\?/i }))
    await waitFor(() => expect(stream.body?.message).toBe('What is artificial intelligence?'))
    await act(async () => { stream.end() })
  })

  it('"Try again" asks the server to answer the last question again instead of adding a new one', async () => {
    let calls = 0
    const bodies = []
    mockApi({ 'POST /chat/stream': (init) => { bodies.push(JSON.parse(init.body)); const s = liveStream(); setTimeout(() => { s.push('conversation', { conversation_id: 9, title: 'Hi' }); s.push('token', { t: 'Hello!' }); s.push('done', { message_id: 40 + (calls++), route: 'smalltalk', mode: 'smalltalk', validation: {}, follow_ups: [], timings: {} }); s.end() }, 0); return s.res } })
    const user = userEvent.setup()
    mount(<Assistant />)
    await user.type(await screen.findByLabelText(/your question/i), 'hi')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    await user.click(await screen.findByRole('button', { name: /try again/i }))
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toMatchObject({ message: 'hi', conversation_id: 9, regenerate: true })
    expect(screen.getAllByText('hi')).toHaveLength(1)                                     // the question is not duplicated
  })

  it('searches conversations on the server', async () => {
    const queries = []
    mockApi({ 'GET /chat/conversations': () => { queries.push(1); return json([]) } })
    const user = userEvent.setup()
    mount(<Assistant />)
    await user.type(await screen.findByLabelText(/search conversations/i), 'verification')
    await waitFor(() => expect(global.fetch.mock.calls.some(([u]) => String(u).includes('/chat/conversations?q=verification'))).toBe(true))
  })

  it('shows a clear message when the server refuses the request', async () => {
    mockApi({ 'POST /chat/stream': () => json({ detail: 'You are sending messages too quickly. Please wait a moment.' }, 429) })
    const user = userEvent.setup()
    mount(<Assistant />)
    await user.type(await screen.findByLabelText(/your question/i), 'hello')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByText(/sending messages too quickly/i)).toBeInTheDocument()
  })
})

describe('agent workspace', () => {
  const PLAN = { id: 3, goal: 'How many open needs?', status: 'awaiting_approval', steps: [], answer: null, plan: [
    { index: 0, tool: 'calculate', kind: 'python', why: 'Compute exactly.', requires_approval: false, admin_only: false, allowed: true },
    { index: 1, tool: 'optimize_allocation', kind: 'optimization', why: 'Allocate stock.', requires_approval: true, admin_only: true, allowed: false }] }

  it('proposes a plan first and runs nothing until the person approves', async () => {
    const stream = liveStream()
    mockApi({ 'POST /agent/runs': () => json(PLAN, 201), 'POST /agent/runs/3/approve': () => stream.res })
    const user = userEvent.setup()
    mount(<AgentWorkspace />)
    await user.type(await screen.findByLabelText(/goal for the ai agent/i), 'How many open needs?')
    await user.click(screen.getByRole('button', { name: /propose a plan/i }))
    expect(await screen.findByText(/nothing has run yet/i)).toBeInTheDocument()
    expect(screen.getByText(/your role cannot run this tool/i)).toBeInTheDocument()
    expect(global.fetch.mock.calls.some(([u]) => String(u).includes('/approve'))).toBe(false)
    await user.click(screen.getByRole('button', { name: /approve and run/i }))
    await act(async () => { stream.push('step_done', { index: 0, tool: 'calculate', status: 'ok', ms: 8, attempts: 1, summary: 'Open needs: 2.' }); stream.push('answer', { text: 'Open needs: 2.', validation: { numbers_ok: true, constraints_ok: true, steps_failed: 0, warnings: [] }, proposals: [] }); stream.push('done', { id: 3, status: 'completed', duration_ms: 20 }); stream.end() })
    expect(await screen.findByText(/every number traced to a tool result/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /download report/i })).toBeInTheDocument())
  })
})


describe('regression: "path.run_id: Input should be a valid integer"', () => {
  it('the API client has no duplicate function names (a later duplicate silently replaced the AI Lab agent call)', () => {
    const src = fs.readFileSync(new URL('../src/api/client.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
    const body = src.slice(src.indexOf('export const api = {'))
    const keys = [...body.matchAll(/^ {2}([A-Za-z0-9_]+):/gm)].map((m) => m[1])
    const dupes = keys.filter((k, i) => keys.indexOf(k) !== i)
    expect(dupes).toEqual([])
  })

  it('the AI Lab agent call posts the question to /agent/run and never puts it in a URL path', async () => {
    mockApi({ 'POST /agent/run': () => json({ answer: 'ok', steps: [] }) })
    await api.agentRun('Which needs are most urgent right now?', false)
    const urls = global.fetch.mock.calls.map(([u, init]) => `${init?.method || 'GET'} ${String(u).replace(/^\/api/, '')}`)
    expect(urls).toContain('POST /agent/run')
    expect(urls.some((u) => u.includes('/agent/runs/') && u.includes('Which'))).toBe(false)
  })

  it('looking up a run uses its numeric id', async () => {
    mockApi({ 'GET /agent/runs/12': () => json({ id: 12 }) })
    await api.agentGetRun(12)
    expect(global.fetch.mock.calls.map(([u]) => String(u))).toEqual(['/api/agent/runs/12'])
  })
})
