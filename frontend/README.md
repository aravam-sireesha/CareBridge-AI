# CareBridge AI frontend

React 18 + Vite + Tailwind. Talks to the FastAPI backend, which reads and writes PostgreSQL.

## Run

```bash
npm install
npm run dev            # http://localhost:5173
```
Start the backend first (`python -m uvicorn app.main:app --reload` in the backend folder, same terminal where the
virtual environment is active). The browser calls `/api/...` on the Vite server, and Vite forwards it to
`http://127.0.0.1:8000`, so **there is no CORS setup and no .env needed**. Different backend address:
`VITE_BACKEND_URL=http://host:port npm run dev`. API hosted elsewhere: set `VITE_API_URL` (see `.env.example`).

The **API online / offline** pill in the top bar shows whether the backend is reachable. If a screen shows
"Cannot reach the CareBridge API", the backend is not running.

## Screens (13 + the new first frame)

| Frame | Route | Roles |
|-------|-------|-------|
| **Home** (new first frame: top bar with Login, sidebar, logo, about, AI modules, how it works) | `/` | public |
| Login / Create account / Forgot password | `/login` `/register` `/forgot-password` | public |
| Dashboard (live charts) | `/dashboard` | all |
| Children, Child profile | `/children`, `/children/:id` | admin, organization |
| Needs | `/needs` | all (donors/volunteers see verified organizations only) |
| Donors & volunteers | `/people` | admin, organization |
| Donations | `/donations` | admin, organization, donor |
| Need alerts / Fraud flags / Matching review / Career guidance | `/ai/...` | see sidebar |
| AI assistant (RAG) | `/assistant` | all |
| Settings (profile, users + reset codes, organizations + verification, knowledge base, system & database health) | `/settings` | all / admin tabs |

The sidebar only shows pages the signed-in role may open; the backend enforces the same rules.

## Tests (real UI against the real backend + PostgreSQL)

```bash
# backend running, demo data seeded (see backend/FIXES_AND_RUNBOOK.md)
CAREBRIDGE_E2E_API=http://127.0.0.1:8000 E2E_ADMIN_EMAIL=you@admin E2E_ADMIN_PASSWORD=... npm test
```
Windows PowerShell: `$env:CAREBRIDGE_E2E_API="http://127.0.0.1:8000"; npm test`.
`tests/e2e.test.jsx` registers accounts, logs in, adds rows, runs the fraud scan, the RAG assistant and the system page.
`tests/ai-modules.test.jsx` drives career guidance, matching, need alerts and a donor donation (needs `scripts/seed_demo.py`).

## Design

Teal/sky palette on a soft off-white, Lexend headings + Inter body, handwritten Caveat accent for the quotes.
Every list has loading skeletons, empty states and error states with a retry button. Success and failure toasts appear
for every save. Your photo is `public/images/child-portrait.jpg` (resized to 172 KB for fast loading).
