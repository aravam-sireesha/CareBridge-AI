// Verification documents: what can be uploaded, and the checks done in the browser BEFORE sending (the server re-checks everything).
export const MAX_MB = 5
export const ALLOWED = { 'application/pdf': ['pdf'], 'image/jpeg': ['jpg', 'jpeg'], 'image/png': ['png'], 'image/webp': ['webp'] }

export const KIND_LABELS = {
  organization: { registration_certificate: 'Registration certificate', darpan: 'NGO DARPAN registration', jj_act_registration: 'Juvenile Justice Act registration', cert_12a: '12A certificate', cert_80g: '80G certificate', supporting: 'Other supporting document' },
  volunteer: { id_document: 'Identity document', police_verification: 'Police verification', code_of_conduct: 'Signed code of conduct', supporting: 'Other supporting document' },
}

export const REVIEW_TEXT = { pending: 'Waiting for review', approved: 'Accepted by an administrator', rejected: 'Not accepted' }

/** Which record a signed-in person's documents belong to (null if their account has none). */
export function ownerFor(user) {
  if (user?.role === 'organization' && user.organization_id) return { ownerType: 'organization', ownerId: user.organization_id }
  if (user?.role === 'volunteer' && user.volunteer_id) return { ownerType: 'volunteer', ownerId: user.volunteer_id }
  return null
}

/** Quick checks so a wrong file is refused before a large upload. Returns an error message or ''. */
export function checkFile(file, maxMb = MAX_MB) {
  if (!file) return 'Choose a file first.'
  if (!file.size) return 'That file is empty.'
  if (file.size > maxMb * 1024 * 1024) return `That file is too large. The limit is ${maxMb} MB.`
  const ext = String(file.name || '').split('.').pop().toLowerCase()
  const known = Object.entries(ALLOWED).find(([type]) => type === file.type)
  if (!known || !known[1].includes(ext)) return 'Only PDF, JPEG, PNG or WebP files can be uploaded.'
  return ''
}

export function fileToBase64(file, reader = () => new FileReader()) {
  return new Promise((resolve, reject) => {
    const r = reader()
    r.onerror = () => reject(new Error('The file could not be read.'))
    r.onload = () => { const url = String(r.result || ''); const i = url.indexOf(','); i < 0 ? reject(new Error('The file could not be read.')) : resolve(url.slice(i + 1)) }
    r.readAsDataURL(file)
  })
}

export const formatSize = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`)
