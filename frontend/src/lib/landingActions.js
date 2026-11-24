// The call-to-action buttons in the landing hero. Pure, so a test can check every visitor type.
// Visitors who are not signed in choose what they came for; signed-in people only see what is relevant to their role.
export function heroActions(isAuthenticated, role) {
  if (!isAuthenticated) {
    return [
      { label: 'Donate Resources', to: '/register?role=donor', kind: 'primary' },
      { label: 'Become a Volunteer', to: '/register?role=volunteer', kind: 'secondary' },
      { label: 'Find Support', to: '/register?role=organization', kind: 'secondary' },
      { label: 'Sign In', to: '/login', kind: 'ghost' }
    ]
  }
  const home = role === 'admin' ? { label: 'Open admin dashboard', to: '/admin' } : { label: 'Open dashboard', to: '/dashboard' }
  const next = {
    organization: { label: 'Create a need', to: '/needs?new=1' },
    donor: { label: 'Donate resources', to: '/donations' },
    volunteer: { label: 'Find a need to help with', to: '/needs' }
  }[role]
  return [{ ...home, kind: 'primary' }, ...(next ? [{ ...next, kind: 'secondary' }] : [])]
}
