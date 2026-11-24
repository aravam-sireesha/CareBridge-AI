import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import DocumentsPanel from '../src/components/DocumentsPanel.jsx'
import AdminDocuments from '../src/components/AdminDocuments.jsx'
import { api } from '../src/api/client.js'
import { KIND_LABELS, MAX_MB, checkFile, fileToBase64, formatSize, ownerFor } from '../src/lib/documents.js'
import { REDACTED, beforeBreadcrumb, beforeSend, initMonitoring, scrub, scrubString } from '../src/lib/monitoring.js'

afterEach(() => cleanup())
const file = (name, type, size = 1000) => ({ name, type, size })

describe('documents library', () => {
  it.each([['scan.pdf', 'application/pdf'], ['photo.JPG', 'image/jpeg'], ['photo.jpeg', 'image/jpeg'], ['a.png', 'image/png'], ['a.webp', 'image/webp']])('accepts %s', (n, t) => { expect(checkFile(file(n, t))).toBe('') })
  it.each([['virus.exe', 'application/x-msdownload'], ['page.html', 'text/html'], ['a.svg', 'image/svg+xml'], ['a.pdf', 'image/png'], ['a.png', 'application/pdf'], ['noext', 'application/pdf'], ['a.gif', 'image/gif'], ['a.pdf', '']])('refuses %s declared as %s', (n, t) => { expect(checkFile(file(n, t))).toMatch(/Only PDF/) })
  it('refuses missing, empty and oversized files', () => {
    expect(checkFile(null)).toMatch(/Choose a file/); expect(checkFile(file('a.pdf', 'application/pdf', 0))).toMatch(/empty/)
    expect(checkFile(file('a.pdf', 'application/pdf', MAX_MB * 1024 * 1024 + 1))).toMatch(/too large/); expect(checkFile(file('a.pdf', 'application/pdf', MAX_MB * 1024 * 1024))).toBe('')
  })
  it('finds the record a person\u2019s documents belong to', () => {
    expect(ownerFor({ role: 'organization', organization_id: 4 })).toEqual({ ownerType: 'organization', ownerId: 4 })
    expect(ownerFor({ role: 'volunteer', volunteer_id: 9 })).toEqual({ ownerType: 'volunteer', ownerId: 9 })
    for (const u of [{ role: 'donor', donor_id: 1 }, { role: 'admin' }, { role: 'organization' }, { role: 'volunteer', volunteer_id: null }, null]) expect(ownerFor(u)).toBeNull()
  })
  it('keeps police and identity documents out of the organization list', () => {
    expect(KIND_LABELS.volunteer.police_verification).toBeTruthy(); expect(KIND_LABELS.organization.police_verification).toBeUndefined()
  })
  it('extracts the base64 part of a data URL and reports read failures', async () => {
    const ok = () => ({ readAsDataURL() { this.result = 'data:application/pdf;base64,QUJD'; this.onload() } })
    expect(await fileToBase64({}, ok)).toBe('QUJD')
    await expect(fileToBase64({}, () => ({ readAsDataURL() { this.onerror() } }))).rejects.toThrow(/could not be read/)
    await expect(fileToBase64({}, () => ({ readAsDataURL() { this.result = 'garbage'; this.onload() } }))).rejects.toThrow(/could not be read/)
  })
  it('formats sizes', () => { expect(formatSize(100)).toBe('1 KB'); expect(formatSize(2048)).toBe('2 KB'); expect(formatSize(3 * 1024 * 1024)).toBe('3.0 MB') })
})

describe('browser error monitoring scrubber', () => {
  it.each(['password', 'access_token', 'Authorization', 'otp', 'email', 'phone_e164', 'address', 'latitude', 'lng', 'coordinates', 'position', 'heading', 'child_name', 'guardian', 'aadhaar', 'session_id'])('redacts the %s field', (k) => { expect(scrub({ [k]: 'VALUE' })).toEqual({ [k]: REDACTED }) })
  it('keeps harmless fields and goes deep', () => {
    expect(scrub({ route: '/map', n: 3, a: [{ b: { latitude: 1, ok: true } }] })).toEqual({ route: '/map', n: 3, a: [{ b: { latitude: REDACTED, ok: true } }] })
  })
  it.each([['mail donor@example.org now', 'donor@example.org'], ['Bearer abcDEF123456789xyz', 'abcDEF123456789xyz'], ['at 17.385044, 78.486671', '17.385044'], ['call +91 98765 43210', '98765'], ['eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig12345678', 'eyJhbGciOiJIUzI1NiJ9']])('scrubs values by pattern: %s', (text, gone) => { expect(scrubString(text)).not.toContain(gone) })
  it('leaves ordinary numbers alone', () => { expect(scrubString('took 1234 ms, version 1.2.3, task 77')).toBe('took 1234 ms, version 1.2.3, task 77') })
  it('reduces a real-looking event to what is safe', () => {
    const ev = { message: 'failed at 17.385044, 78.486671 for a@b.org', user: { id: 7, email: 'a@b.org', ip_address: '1.2.3.4' }, request: { url: 'https://x/y', data: { latitude: 1 }, cookies: { s: 1 }, headers: { Authorization: 'Bearer abcdefghijkl' }, query_string: 'token=abc' }, extra: { otp: '123456' } }
    const out = beforeSend(ev); const text = JSON.stringify(out)
    for (const secret of ['17.385044', 'a@b.org', '1.2.3.4', 'abcdefghijkl', '123456', 'token=abc']) expect(text).not.toContain(secret)
    expect(out.user).toEqual({ id: '7' }); expect(out.request.data).toBeUndefined(); expect(out.request.headers).toEqual({})
  })
  it('does not mutate the original event, and drops an event it cannot scrub', () => {
    const ev = { message: 'x@y.org', user: { id: 1 } }; const copy = JSON.stringify(ev); beforeSend(ev); expect(JSON.stringify(ev)).toBe(copy)
    const hostile = {}; Object.defineProperty(hostile, 'message', { enumerable: true, get() { throw new Error('boom') } })
    expect(beforeSend(hostile)).toBeNull()
  })
  it('removes request URLs from fetch breadcrumbs', () => {
    const out = beforeBreadcrumb({ category: 'fetch', message: 'ok', data: { url: '/api/needs?lat=17.38', status_code: 200 } })
    expect(JSON.stringify(out)).not.toContain('lat=17.38'); expect(out.data.status_code).toBe(200)
  })
  it('does nothing without a DSN, starts with safe options with one, and survives a failed load', async () => {
    expect(await initMonitoring({ dsn: '' })).toBe(false)
    const init = vi.fn(); expect(await initMonitoring({ dsn: 'https://k@o.example/1', importer: async () => ({ init }) })).toBe(true)
    const opts = init.mock.calls[0][0]; expect(opts.sendDefaultPii).toBe(false); expect(opts.tracesSampleRate).toBe(0); expect(opts.beforeSend).toBe(beforeSend)
    const warn = console.warn; console.warn = () => {}
    expect(await initMonitoring({ dsn: 'https://k@o.example/1', importer: async () => { throw new Error('missing') } })).toBe(false); console.warn = warn
  })
})

const DOC = (extra = {}) => ({ id: 1, owner_type: 'organization', owner_id: 4, kind: 'darpan', original_name: 'darpan.pdf', content_type: 'application/pdf', size_bytes: 2048, review_status: 'pending', review_note: null, ...extra })
function setup(docs = [], props = {}) {
  api.documentsList = vi.fn().mockResolvedValue({ documents: docs }); api.documentUpload = vi.fn().mockResolvedValue({}); api.documentUrl = vi.fn().mockResolvedValue({ url: 'https://storage.example/x?sig=1', expires_in: 300 })
  api.documentDelete = vi.fn().mockResolvedValue({}); api.documentReview = vi.fn().mockResolvedValue({})
  return render(<DocumentsPanel ownerType="organization" ownerId={4} {...props} />)
}
const pickFile = (f) => fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [f] } })

describe('DocumentsPanel (owner)', () => {
  it('lists documents with their review state, and never calls a pending document verified', async () => {
    setup([DOC(), DOC({ id: 2, kind: 'cert_12a', review_status: 'approved' }), DOC({ id: 3, kind: 'cert_80g', review_status: 'rejected', review_note: 'The scan is cut off' })])
    expect(await screen.findByText('Waiting for review')).toBeTruthy(); expect(screen.queryByText('Accepted by an administrator')).toBeTruthy(); expect(screen.queryByText('Not accepted')).toBeTruthy()
    expect(screen.queryByText(/The scan is cut off/)).toBeTruthy(); expect(screen.queryByText(/does not verify anyone/)).toBeTruthy()
  })
  it('shows an empty state and a load error', async () => {
    setup([]); expect(await screen.findByText('No documents yet.')).toBeTruthy(); cleanup()
    api.documentsList = vi.fn().mockRejectedValue(new Error('Not found')); render(<DocumentsPanel ownerType="organization" ownerId={4} />)
    expect(await screen.findByRole('alert')).toBeTruthy()
  })
  it('refuses a wrong file in the browser without contacting the server', async () => {
    setup([]); await screen.findByText('No documents yet.')
    pickFile(file('virus.exe', 'application/x-msdownload')); fireEvent.click(screen.getByText('Upload'))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Only PDF/); expect(api.documentUpload).toHaveBeenCalledTimes(0)
    fireEvent.click(screen.getByText('Upload'))
  })
  it('uploads a valid file with the chosen type and the file contents as base64', async () => {
    setup([]); await screen.findByText('No documents yet.')
    const f = new File(['ABC'], 'darpan.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'cert_12a' } }); pickFile(f); fireEvent.click(screen.getByText('Upload'))
    await waitFor(() => expect(api.documentUpload).toHaveBeenCalledTimes(1))
    expect(api.documentUpload).toHaveBeenCalledWith({ owner_type: 'organization', owner_id: 4, kind: 'cert_12a', filename: 'darpan.pdf', content_type: 'application/pdf', data_base64: 'QUJD' })
    await waitFor(() => expect(api.documentsList).toHaveBeenCalledTimes(2))                                // the list is refreshed
  })
  it('shows the server\u2019s reason when storage is not set up or the file is refused', async () => {
    setup([]); api.documentUpload = vi.fn().mockRejectedValue(new Error('File storage is not set up on this server yet.')); await screen.findByText('No documents yet.')
    pickFile(new File(['ABC'], 'a.pdf', { type: 'application/pdf' })); fireEvent.click(screen.getByText('Upload'))
    expect((await screen.findByRole('alert')).textContent).toMatch(/not set up on this server/)
  })
  it('opens a document through a fresh short-lived link in a new, isolated window', async () => {
    setup([DOC()]); const open = vi.fn(); window.open = open
    fireEvent.click(await screen.findByText('Open'))
    await waitFor(() => expect(open).toHaveBeenCalledWith('https://storage.example/x?sig=1', '_blank', 'noopener,noreferrer')); expect(api.documentUrl).toHaveBeenCalledWith(1)
  })
  it('lets the owner remove a pending document but not an accepted one', async () => {
    setup([DOC(), DOC({ id: 2, review_status: 'approved' })]); await screen.findAllByText('Open')
    const removes = screen.getAllByText('Remove'); expect(removes.length).toBe(1)
    fireEvent.click(removes[0]); await waitFor(() => expect(api.documentDelete).toHaveBeenCalledWith(1))
  })
  it('offers no review controls to the owner', async () => {
    setup([DOC()]); await screen.findByText('Open'); expect(screen.queryByText('Accept')).toBeNull(); expect(screen.queryByText('Reject')).toBeNull()
  })
})

describe('DocumentsPanel (administrator review)', () => {
  it('accepts a document', async () => {
    setup([DOC()], { reviewer: true, canUpload: false }); fireEvent.click(await screen.findByText('Accept'))
    await waitFor(() => expect(api.documentReview).toHaveBeenCalledWith(1, 'approved', undefined))
  })
  it('will not reject without a reason, and sends the reason when given', async () => {
    setup([DOC()], { reviewer: true, canUpload: false }); fireEvent.click(await screen.findByText('Reject'))
    expect((await screen.findByRole('alert')).textContent).toMatch(/say why/); expect(api.documentReview).toHaveBeenCalledTimes(0)
    fireEvent.change(screen.getByLabelText('Reason for document 1'), { target: { value: 'Scan is unreadable' } }); fireEvent.click(screen.getByText('Reject'))
    await waitFor(() => expect(api.documentReview).toHaveBeenCalledWith(1, 'rejected', 'Scan is unreadable'))
  })
  it('does not offer upload or owner deletion, and an accepted document cannot be accepted again', async () => {
    setup([DOC({ review_status: 'approved' })], { reviewer: true, canUpload: false }); await screen.findByText('Open')
    expect(screen.queryByText('Upload')).toBeNull(); expect(screen.queryByText('Remove')).toBeNull(); expect(screen.getByText('Accept').disabled).toBe(true)
  })
  it('states that accepting a document does not verify the organization', async () => {
    setup([DOC()], { reviewer: true, canUpload: false }); expect(await screen.findByText(/does not by itself verify the organization or volunteer/)).toBeTruthy()
  })
})

describe('AdminDocuments', () => {
  it('needs a valid record number before showing anything, and keeps digits only', async () => {
    api.documentsList = vi.fn().mockResolvedValue({ documents: [] })
    render(<AdminDocuments />)
    const input = screen.getByLabelText('Record number'); expect(screen.getByText('Show documents').disabled).toBe(true)
    fireEvent.change(input, { target: { value: '12ab3' } }); expect(input.value).toBe('123'); expect(screen.getByText('Show documents').disabled).toBe(false)
    fireEvent.change(screen.getByLabelText('Whose documents'), { target: { value: 'volunteer' } }); fireEvent.click(screen.getByText('Show documents'))
    await waitFor(() => expect(api.documentsList).toHaveBeenCalledWith('volunteer', 123)); expect(await screen.findByText('No documents yet.')).toBeTruthy()
  })
  it('does not accept zero or an empty number', () => {
    render(<AdminDocuments />); fireEvent.change(screen.getByLabelText('Record number'), { target: { value: '0' } }); expect(screen.getByText('Show documents').disabled).toBe(true)
  })
})
