# Phase 2: design tokens and dashboard cleanup

## Changed
- **Tokens** (`tailwind.config.js`, `src/index.css`): bg, surface, line, ink, ink-muted are CSS variables in `:root`
  (warm ivory page `#FAF8F3`, warm border `#E5E1D8`). New `accent` (coral) scale for ONE primary action per screen.
  Class names are unchanged, so no page needed editing. `dark.css` still works (it targets class names).
  Contrast measured (WCAG): ink/ivory 16.8, muted/ivory 7.1, white/teal-700 5.5, white/accent-700 5.6.
  accent-600 with white text is 3.95 and is NOT used for text buttons.
- **Dashboard** (`pages/Dashboard.jsx`, `components/RoleActions.jsx`, `lib/dashboardActions.js`):
  role-specific action row (org 4, donor 3, volunteer 3, admin none), charts only where they help
  (urgency/category for admin and organization; volunteers no donation chart; donors only their own trend).
- **Sidebar**: organizations see "My needs" and "AI matching" (`labels` override in `Layout.jsx`).
- **Dead links fixed**: the disabled Career Guidance page was still linked from the dashboard and the child profile
  (both sent users to the landing page). Hidden behind `lib/features.js: CAREER_ENABLED = false`.
- `/needs?new=1` opens the "Add a need" form (used by the dashboard's "Create a need").

## Deliberately NOT on the dashboard
"Track deliveries" and "Confirm receipt": no backend endpoint records delivery or receipt yet
(nothing sets `delivered_at` / `confirmed_at` or changes a donation's status after creation). Phase 4.
"Submit a match for approval": organizations cannot submit matches yet. Phase 5.

## Verify on your machine
    npm install ; npm test ; npm run build ; npm run dev
New test: `tests/dashboard-actions.test.jsx` (every dashboard link opens a real, permitted route).
Look at the dashboards in all four roles and both themes: the CSS was not built or viewed in my sandbox.
