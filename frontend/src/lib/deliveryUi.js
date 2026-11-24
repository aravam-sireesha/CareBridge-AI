// Pure helpers for the Deliveries screen. The SERVER decides which actions exist (allowed_actions); this file only
// describes how to ask for the extra details an action needs, and checks them before sending (the server checks again).

export const FIELD_META = {
  reason: { label: 'Reason', type: 'textarea', hint: 'Recorded with the decision so everyone can see why.' },
  note: { label: 'Note', type: 'textarea', hint: '' },
  volunteer_id: { label: 'Volunteer', type: 'volunteer', hint: 'Only volunteers of your organization, or ones recommended for this need.' },
  pickup_at: { label: 'Pickup date and time', type: 'datetime-local', hint: 'Within the next 90 days.' },
  received_quantity: { label: 'Quantity received', type: 'number', hint: 'Count what actually arrived.' },
  resolution: { label: 'Resolution', type: 'resolution', hint: '' }
}
// "deliver" asks for a note that serves as proof of delivery; "confirm_receipt" notes are optional unless quantities differ.
export const FIELD_OVERRIDES = {
  deliver: { note: { label: 'Proof of delivery', hint: 'Who received it, and where. At least 3 characters.' } },
  confirm_receipt: { note: { label: 'Note (required if the quantity differs)', hint: '' } },
  resolve_exception: { note: { label: 'Note', hint: 'What was decided and why.' } }
}
export const RESOLUTIONS = [
  { value: 'resume', label: 'Resume the delivery' },
  { value: 'reoffer', label: 'Offer it to another volunteer (only before pickup)' },
  { value: 'cancel', label: 'Cancel the delivery' }
]

export const fieldFor = (action, field) => ({ ...FIELD_META[field], ...(FIELD_OVERRIDES[action]?.[field] || {}) })

/** datetime-local gives "2026-10-30T09:30" in the person's own time; send it as an unambiguous UTC instant. */
export function localToUtcIso(value) {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

/** Collects the values an action needs. Returns { ok, payload, errors }. Server rules are the authority; this saves a round trip. */
export function buildPayload(action, fields, values) {
  const payload = {}; const errors = {}
  for (const f of fields) {
    const raw = values[f]
    const text = typeof raw === 'string' ? raw.trim() : raw
    if (f === 'reason') { if (!text || text.length < 3) errors[f] = 'Please give a reason (at least 3 characters).'; else payload[f] = text }
    else if (f === 'volunteer_id') { const n = Number(text); if (!text || !Number.isInteger(n) || n < 1) errors[f] = 'Choose a volunteer.'; else payload[f] = n }
    else if (f === 'pickup_at') { const iso = text ? localToUtcIso(text) : null; if (!iso) errors[f] = 'Choose a date and time.'; else payload[f] = iso }
    else if (f === 'received_quantity') { const n = Number(text); if (text === '' || text == null || !Number.isInteger(n) || n < 0) errors[f] = 'Enter a whole number, 0 or more.'; else payload[f] = n }
    else if (f === 'resolution') { if (!RESOLUTIONS.some((r) => r.value === text)) errors[f] = 'Choose how to resolve it.'; else payload[f] = text }
    else if (f === 'note') { if (action === 'deliver' && (!text || text.length < 3)) errors[f] = 'Describe the proof of delivery (at least 3 characters).'; else if (text) payload[f] = text }
  }
  // An optional note travels with any action that shows a note box without listing it as required (receipt, resolution).
  if (!fields.includes('note') && typeof values.note === 'string' && values.note.trim()) payload.note = values.note.trim()
  // A different quantity needs an explanation (checked again on the server).
  if (action === 'confirm_receipt' && values.__expected != null && payload.received_quantity != null && payload.received_quantity !== values.__expected && !payload.note) {
    errors.note = 'The quantity differs from what was expected. Please explain the difference.'
  }
  return { ok: Object.keys(errors).length === 0, payload, errors }
}

export const NEEDS_ATTENTION_ACTIONS = new Set(['approve', 'commit', 'accept', 'confirm_receipt', 'resolve_exception', 'submit', 'offer', 'pick_up', 'start_transit', 'deliver', 'schedule_pickup'])

/** Which tab a delivery belongs in. "action" = this person has something to do now. */
export function groupOf(task) {
  if (task.allowed_actions?.some((a) => NEEDS_ATTENTION_ACTIONS.has(a.action))) return 'action'
  if (['receipt_confirmed', 'cancelled', 'rejected'].includes(task.status)) return 'done'
  return 'progress'
}

export const STATUS_TONE = {
  proposed: 'gray', awaiting_approval: 'amber', approved: 'sky', rejected: 'red', committed: 'sky', offered: 'amber', accepted: 'teal',
  pickup_scheduled: 'teal', picked_up: 'teal', in_transit: 'teal', delivered: 'green', receipt_confirmed: 'green', cancelled: 'gray', exception: 'red'
}

/** The five steps of the happy path, for the progress strip. */
export const JOURNEY = [
  { key: 'approved', label: 'Approved' }, { key: 'committed', label: 'Committed' }, { key: 'accepted', label: 'Volunteer accepted' },
  { key: 'picked_up', label: 'Picked up' }, { key: 'delivered', label: 'Delivered' }, { key: 'receipt_confirmed', label: 'Receipt confirmed' }
]
const ORDER = ['proposed', 'awaiting_approval', 'approved', 'committed', 'offered', 'accepted', 'pickup_scheduled', 'picked_up', 'in_transit', 'delivered', 'receipt_confirmed']
/** How many of the JOURNEY steps are complete for this status (-1 for cancelled/rejected/exception: no progress claim). */
export function journeyProgress(status) {
  if (!ORDER.includes(status)) return -1
  const at = ORDER.indexOf(status)
  return JOURNEY.filter((s) => ORDER.indexOf(s.key) <= at).length
}
