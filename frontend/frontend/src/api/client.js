// All backend calls live here. In development the browser calls /api/... on the Vite
// origin and Vite proxies it to FastAPI (see vite.config.js), so there is no CORS problem.
// Set VITE_API_URL only if the API is hosted somewhere else.
const BASE_URL = import.meta.env.VITE_API_URL || '/api'

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem('cb_token'),
  set: (t) => localStorage.setItem('cb_token', t),
  clear: () => { localStorage.removeItem('cb_token'); localStorage.removeItem('cb_user') }
}

function describeDetail(detail, status) {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof detail.message === 'string') return detail.message
  if (Array.isArray(detail)) {
    // FastAPI validation errors -> "field: message"
    return detail
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
        const msg = String(e.msg || 'Invalid value').replace(/^Value error, /, '')
        return field ? `${field}: ${msg}` : msg
      })
      .join(' · ')
  }
  if (status >= 500) return 'The server hit an error. Check the backend terminal for the traceback.'
  return `Request failed (${status})`
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = tokenStore.get()
  if (auth && token) headers.Authorization = `Bearer ${token}`

  let res
  try {
    res = await fetch(`${BASE_URL}${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined })
  } catch {
    throw new ApiError('Cannot reach the CareBridge API. Make sure the backend is running (uvicorn app.main:app --reload) and try again.', 0)
  }

  let data = null
  const text = await res.text()
  if (text) {
    try { data = JSON.parse(text) } catch { data = { detail: text.slice(0, 200) } }
  }

  if (res.status === 401 && auth && token) {
    window.dispatchEvent(new CustomEvent('cb:unauthorized'))
    throw new ApiError('Your session has expired. Please sign in again.', 401)
  }
  if (!res.ok) throw new ApiError(describeDetail(data?.detail ?? data?.message, res.status), res.status)
  return data
}

/** Download a file (CSV report, template) with the signed-in token and hand it to the browser. */
export async function downloadFile(path, fallbackName = 'download.csv') {
  const token = tokenStore.get()
  let res
  try { res = await fetch(`${BASE_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} }) }
  catch { throw new ApiError('Cannot reach the CareBridge API.', 0) }
  if (!res.ok) {
    let msg = `Download failed (${res.status})`
    try { msg = describeDetail((await res.json())?.detail, res.status) } catch { /* keep default */ }
    throw new ApiError(msg, res.status)
  }
  const match = /filename="?([^";]+)"?/i.exec(res.headers.get('Content-Disposition') || '')
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url; a.download = match ? match[1] : fallbackName
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const qs = (params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))
  const s = q.toString()
  return s ? `?${s}` : ''
}

const get = (p) => request(p)
const post = (p, body) => request(p, { method: 'POST', body: body ?? {} })

export const api = {
  ping: () => request('/', { auth: false }),

  // --- Auth ---
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  register: (payload) => request('/auth/register', { method: 'POST', body: payload, auth: false }),
  requestPasswordReset: (email) => request('/auth/password-reset/request', { method: 'POST', body: { email }, auth: false }),
  completePasswordReset: (token, new_password) => request('/auth/password-reset/complete', { method: 'POST', body: { token, new_password }, auth: false }),
  me: () => get('/auth/me'),
  listUsers: () => get('/auth/users'),
  setUserRole: (id, role) => request(`/auth/users/${id}/role`, { method: 'PATCH', body: { role } }),
  issueResetCode: (id) => post(`/auth/users/${id}/reset-code`),

  // --- Administration ---
  adminLogin: (email, password) => request('/admin/login', { method: 'POST', body: { email, password }, auth: false }),
  adminSetupStatus: () => request('/admin/setup-status', { auth: false }),
  adminSetup: (body) => request('/admin/setup', { method: 'POST', body, auth: false }),
  adminLogout: () => post('/admin/logout'),
  adminOverview: () => get('/admin/overview'),
  adminNeeds: (query = '') => get(`/admin/needs${query}`),
  adminOrganizations: () => get('/admin/organizations'),
  adminModel: () => get('/admin/model'),
  adminSuggestDonors: (needId, topN = 5) => post(`/admin/needs/${needId}/suggest-donors?top_n=${topN}`),
  adminGenerateSuggestions: () => post('/admin/suggestions/generate'),
  adminSuggestions: (status) => get(`/admin/suggestions${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  adminDonors: (orgId) => get(`/admin/donors${orgId ? `?organization_id=${orgId}` : ''}`),
  adminDonor: (id) => get(`/admin/donors/${id}`),
  adminCreateDonor: (body) => post('/admin/donors', body),
  adminUpdateDonor: (id, body) => request(`/admin/donors/${id}`, { method: 'PATCH', body }),
  adminDeleteDonor: (id) => request(`/admin/donors/${id}`, { method: 'DELETE' }),
  adminDeleteNeed: (id) => request(`/admin/needs/${id}`, { method: 'DELETE' }),
  adminTeam: () => get('/admin/administrators'),
  adminAddAdmin: (body) => post('/admin/administrators', body),
  adminSetActive: (id, is_active) => request(`/admin/administrators/${id}`, { method: 'PATCH', body: { is_active } }),
  adminLoginVerify: (mfa_token, code) => request('/admin/login/verify', { method: 'POST', body: { mfa_token, code }, auth: false }),
  adminWorkflow: () => get('/admin/workflow'),
  adminRunScans: () => post('/admin/workflow/run-scans'),
  adminReviewQueue: (type) => get(`/admin/review-queue${type ? `?type=${encodeURIComponent(type)}` : ''}`),
  adminDecide: (type, id, decision) => post(`/admin/review-queue/${type}/${id}`, { decision }),
  adminAllocations: (status) => get(`/admin/allocations${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  adminSuggestResources: (needId) => post(`/admin/needs/${needId}/suggest-resources`),
  adminCreateAllocation: (body) => post('/admin/allocations', body),
  adminReviewAllocation: (id, decision) => post(`/admin/allocations/${id}/review`, { decision }),
  adminAudit: (query = '') => get(`/admin/audit${query}`),
  resources: () => get('/resources/'),
  createResource: (body) => post('/resources/', body),
  updateResource: (id, body) => request(`/resources/${id}`, { method: 'PATCH', body }),
  deleteResource: (id) => request(`/resources/${id}`, { method: 'DELETE' }),
  changePassword: (current_password, new_password) => post('/auth/change-password', { current_password, new_password }),
  logoutAll: () => post('/auth/logout-all'),
  twoFaStatus: () => get('/admin/2fa/status'),
  twoFaSetup: () => post('/admin/2fa/setup'),
  twoFaEnable: (code) => post('/admin/2fa/enable', { code }),
  twoFaDisable: (password, code) => post('/admin/2fa/disable', { password, code }),
  twoFaRecoveryCodes: (password) => post('/admin/2fa/recovery-codes', { password }),
  adminEntities: () => get('/admin/entities'),
  adminRecommend: (entity, id, topN = 5) => get(`/admin/recommend?entity=${entity}&id=${id}&top_n=${topN}`),
  adminForecast: () => get('/admin/forecast'),
  adminModels: () => get('/admin/models'),
  adminSuggestVolunteers: (needId, topN = 5) => post(`/admin/needs/${needId}/suggest-volunteers?top_n=${topN}`),
  adminVolunteers: (orgId) => get(`/admin/volunteers${orgId ? `?organization_id=${orgId}` : ''}`),
  adminVolunteer: (id) => get(`/admin/volunteers/${id}`),
  adminCreateVolunteer: (body) => post('/admin/volunteers', body),
  adminUpdateVolunteer: (id, body) => request(`/admin/volunteers/${id}`, { method: 'PATCH', body }),
  adminDeleteVolunteer: (id) => request(`/admin/volunteers/${id}`, { method: 'DELETE' }),
  seedKnowledge: () => post('/assistant/knowledge/seed-defaults'),
  knowledgeGaps: () => get('/assistant/gaps'),
  agentRun: (question, createProposals = false) => post('/agent/run', { question, create_proposals: createProposals }),
  agentTools: () => get('/agent/tools'),
  advancedAnswer: (question) => post('/assistant/answer', { question }),
  aiDataQuality: () => get('/admin/ai/data-quality'),
  aiRepair: (fixes) => post('/admin/ai/data-quality/repair', { fixes }),
  aiModels: () => get('/admin/ai/models'),
  aiTrain: () => post('/admin/ai/models/train'),
  aiPredict: (id) => get(`/admin/ai/predict/${id}`),
  aiForecast: () => get('/admin/ai/forecast'),
  aiAnomalies: () => get('/admin/ai/anomalies'),
  aiSegments: () => get('/admin/ai/segments'),
  aiOptimizeAllocation: (body) => post('/admin/ai/optimize/allocation', body),
  aiOptimizeMatching: (body) => post('/admin/ai/optimize/matching', body),
  aiReport: () => get('/admin/ai/report'),
  adminReviewSuggestion: (id, decision) => post(`/admin/suggestions/${id}/review`, { decision }),

  // --- Admin: verification, users, KPIs, anomalies ---
  verifications: (params) => get(`/admin/verifications/${qs(params)}`),
  verificationDetail: (id) => get(`/admin/verifications/${id}`),
  decideVerification: (id, body) => post(`/admin/verifications/${id}/decision`, body),
  adminUsers: (params) => get(`/admin/users/${qs(params)}`),
  adminSetUserActive: (id, is_active, reason) => request(`/admin/users/${id}/status`, { method: 'PATCH', body: { is_active, reason: reason || null } }),
  adminUserAudit: (id) => get(`/admin/users/${id}/audit`),
  adminKpis: () => get('/admin/kpis'),
  anomalies: (params) => get(`/admin/anomalies/${qs(params)}`),

  // --- Notifications ---
  notifications: (params) => get(`/notifications/${qs(params)}`),
  unreadCount: () => get('/notifications/unread-count'),
  markNotificationRead: (id) => post(`/notifications/${id}/read`),
  markAllNotificationsRead: () => post('/notifications/read-all'),
  notificationPrefs: () => get('/notifications/preferences'),
  saveNotificationPrefs: (body) => request('/notifications/preferences', { method: 'PUT', body }),

  // --- Reports, bulk upload, public landing data ---
  reportTypes: () => get('/reports/types'),
  downloadReport: (type, params) => downloadFile(`/reports/${type}${qs(params)}`),
  downloadNeedTemplate: () => downloadFile('/needs/bulk/template', 'carebridge-needs-template.csv'),
  validateBulkNeeds: (body) => post('/needs/bulk/validate', body),
  importBulkNeeds: (body) => post('/needs/bulk/import', body),
  publicStats: () => request('/public/stats', { auth: false }),
  publicNeeds: () => request('/public/needs', { auth: false }),
  publicOrganizations: () => request('/public/organizations', { auth: false }),
  listChildrenSummary: () => get('/children/?view=summary'),

  // --- Dashboard + health ---
  dashboard: () => get('/dashboard/summary'),
  health: () => get('/health/db'),

  // --- Organizations ---
  listOrganizations: () => get('/organizations/'),
  updateOrganization: (id, body) => request(`/organizations/${id}`, { method: 'PUT', body }),
  verifyOrganization: (id, verified) => request(`/organizations/${id}/verification`, { method: 'PATCH', body: { verified } }),

  // --- Children + career guidance ---
  listChildren: () => get('/children/'),
  getChild: (id) => get(`/children/${id}`),
  createChild: (body) => post('/children/', body),
  getCareerProfile: (childId) => get(`/career/profiles/${childId}`),
  saveCareerProfile: (childId, body) => post(`/career/profiles/${childId}`, body),
  listRecommendations: (childId) => get(`/career/recommendations/${childId}`),
  recommendCareer: (childId) => post(`/career/recommend/${childId}`),
  careerFeedback: (recId, body) => post(`/career/${recId}/feedback`, body),

  // --- Needs + alerts ---
  listNeeds: () => get('/needs/'),
  createNeed: (body) => post('/needs/', body),
  updateNeed: (id, body) => request(`/needs/${id}`, { method: 'PATCH', body }),
  listNeedAlerts: () => get('/needs/alerts'),
  scanNeeds: () => post('/needs/scan'),
  reviewNeedAlert: (id, decision) => post(`/needs/alerts/${id}/review`, { decision }),

  // --- Donors, volunteers, donations ---
  listDonors: () => get('/donors/'),
  createDonor: (body) => post('/donors/', body),
  listVolunteers: () => get('/volunteers/'),
  createVolunteer: (body) => post('/volunteers/', body),
  listDonations: () => get('/donations/'),
  createDonation: (body) => post('/donations/', body),

  // --- Fraud ---
  listFraudFlags: () => get('/fraud/flags'),
  scanDonations: () => post('/fraud/scan'),
  reviewFraudFlag: (id, decision) => post(`/fraud/flags/${id}/review?decision=${encodeURIComponent(decision)}`),

  // --- Matching ---
  listMatches: () => get('/matching/'),
  suggestMatches: (needId) => post(`/matching/suggest/${needId}`),
  reviewMatch: (id, status) => post(`/matching/${id}/review`, { status }),

  // --- RAG assistant ---
  askAssistant: (question) => post('/assistant/ask', { question }),
  assistantHistory: () => get('/assistant/history'),
  assistantStatus: () => get('/assistant/status'),
  assistantInsights: () => get('/assistant/insights'),
  reindexKnowledge: () => post('/assistant/reindex'),
  listKnowledge: () => get('/assistant/knowledge'),
  addKnowledge: (body) => post('/assistant/knowledge', body)
}
