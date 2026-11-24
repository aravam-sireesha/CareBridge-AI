// What each role can do from its dashboard. Plain data so a test can check every link against the real routes.
// Only actions that work today are listed: delivery tracking and receipt confirmation are NOT here because the
// backend has no endpoint that records them yet.
export const DASHBOARD_ACTIONS = {
  organization: [
    { to: '/needs?new=1', title: 'Create a need', text: 'Tell donors and volunteers what your children need.', icon: 'plus', primary: true },
    { to: '/needs', title: 'My needs', text: 'See what is open, matched and fulfilled.', icon: 'needs' },
    { to: '/ai/matching', title: 'AI matching', text: 'Review suggested donors and volunteers for your needs.', icon: 'hand' },
    { to: '/deliveries', title: 'Deliveries', text: 'Arrange deliveries, follow them, and confirm what arrives.', icon: 'donations' },
    { to: '/donations', title: 'Donations', text: 'See what has been given and for which need.', icon: 'donations' }
  ],
  donor: [
    { to: '/needs', title: 'Browse needs', text: 'Verified needs you can help with.', icon: 'needs', primary: true },
    { to: '/deliveries', title: 'My deliveries', text: 'Commit to approved deliveries and follow them.', icon: 'donations' },
    { to: '/donations', title: 'My donations', text: 'Record a gift and see the ones you have made.', icon: 'donations' },
    { to: '/settings?tab=location', title: 'Share my location', text: 'Optional. See needs close to you.', icon: 'pin' }
  ],
  volunteer: [
    { to: '/deliveries', title: 'My tasks', text: 'Deliveries offered to you. Accept only what you can do.', icon: 'donations', primary: true },
    { to: '/needs', title: 'Find a need to help with', text: 'Verified needs where your time can make a difference.', icon: 'needs' },
    { to: '/settings?tab=location', title: 'Set where you can travel', text: 'Optional. Share your location and travel range.', icon: 'pin' },
    { to: '/assistant', title: 'Ask the assistant', text: 'Questions about how volunteering works.', icon: 'assistant' }
  ],
  admin: []
}
