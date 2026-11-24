# CareBridge AI: implementation report (final state of this work)

"Tested" means a test actually ran in the sandbox this code was written in, which had NO FastAPI, SQLAlchemy, PostgreSQL, Tailwind, npm
packages, GPS or internet. Anything that needs those is marked "written, not run": run `backend/scripts/verify_everything.ps1` and follow
`MANUAL_VERIFICATION.md` before relying on it. Before you start: `pg_dump` your database.

## Status of every feature

| Feature | Status | Verified here | Not verified here |
|---|---|---|---|
| Design tokens, warm palette, role-specific dashboards, sidebar labels | Implemented, not fully tested | dashboard links open real permitted routes; real Dashboard + sidebar in Chrome for 4 roles (24 checks); contrast measured | CSS never built or viewed (no Tailwind) |
| Landing page: fixed full-screen photo, frosted sections, darkening on scroll, serif copy, real progress bar | Implemented and tested (layout) | real CSS and your real photo in Chrome (33 checks); worst-case text contrast 5.17:1 | rights/consent for the photo are NOT verified: put real credit and licence in `public/images/hero/hero.json` |
| Saved opt-in location, nearby needs and helpers | Implemented, not fully tested | 21 pure tests; components in Chrome (27) | endpoints and migration not run on a database |
| Live delivery tracking + navigation hand-off + dependency-free OpenStreetMap map | Implemented, not fully tested | rules 10 tests; panel in Chrome with controlled GPS (32 checks) | endpoints/migration not run; real GPS and real tiles never seen |
| Delivery workflow (propose, approve, commit, offer, accept, pickup, transit, deliver, confirm receipt, exceptions) | Implemented, not fully tested | state machine 28 tests, mutation-checked; page in Chrome (29) | router, locking, notifications not run on a database |
| Organization Matching Center (ranking, fit bands, reasons, unmatched explanations) | Implemented, not fully tested | 14 pure tests; admin matching proven unchanged; UI in Chrome (18) | endpoint not run |
| Volunteer availability (weekly schedule + timezone) and self-declared carrying capacity (kg per trip, NOT passenger seats), used in matching, offers and pickup scheduling; free text only ever SUGGESTED | Implemented, not fully tested | 13 pure + 6 unit tests; editor in Chrome (17) | endpoints/migration not run |
| Password recovery with one-time codes (email) | Implemented, not fully tested | 22 pure tests; 4-step screen in Chrome (26) | endpoints not run; no real email sent |
| Registration e-mail verification (opt-in, never locks anyone out, admin fallback) + Verify page + Login link | Implemented, not fully tested | policy tests; Register/Login/Verify flows in Chrome (22) | endpoints/migration not run; no real email |
| SMS provider boundary (Twilio over HTTPS, injectable transport, never logs numbers/codes/credentials) | Boundary only | 7 pure tests | NOT wired into sign-up or recovery (no phone-number field); no SMS ever sent |
| Knowledge upload: .txt .md .docx .pdf, by heading, idempotent, scope per organization, instruction-like text refused, bombs/fake types refused | Implemented, not fully tested | 22 pure tests incl. real .docx files and hostile ones; upload screen in Chrome (25) | endpoint not run; PDF path needs `pypdf` installed (written, test skipped here); no embedding model |
| AI assistant: streaming, stop, retry, copy, voice INPUT, history, per-role prompts, languages | Already existed in your code (audited, not rebuilt) | n/a | n/a |
| AI assistant: spoken replies (Listen/Pause/Resume/Stop, no voice for language = message, one voice at a time) | Implemented and tested (in Chrome) | 7 unit + 14 browser checks with a controllable fake engine | a real speech engine was never heard |
| Login / Register page REDESIGN | Not done | | only the verification step and link were added |
| AI Lab simplification; merging the three assistant screens | Not done | | needs your decision on which screens to retire |
| Risk-signal UI changes, exports, career guidance | Not changed | | career guidance stays disabled as you had it |
| Live GPS in the background / road routes / arrival times | Not implemented | | by design: see HOW_TO_USE_LOCATION_AND_NAVIGATION.md |

## Verification tooling (run these first)
`python scripts/static_check.py` (models/columns, 450+ test URLs vs real routes, undefined names; mutation-checked), `tests/test_migrations_sqlite.py`
(runs the 7 newest migrations on a database holding rows: data survives, twice is safe, downgrade works, constraints fire, tables equal models),
`scripts/verify_everything.ps1` (one command), `MANUAL_VERIFICATION.md` (database copy, row counts, real GPS, tiles, email, speech).
An esbuild bundle of all front-end files resolved every local import/export (stand-in for `vite build`; run the real one).

## Database changes (all additive: nothing dropped, rewritten or backfilled)
`20261024_locations` donors/volunteers coordinates; `20261025_otp` otp_challenges; `20261026_deliveries` delivery_tasks, delivery_events;
`20261027_tracking` delivery_locations (latest position only); `20261028_availability` volunteer timezone/transport/capacity + delivery weight;
`20261029_email_verification` users.email_verification_pending / email_verified_at (NULL = not pending, so existing users are unaffected).
Chain verified linear, 20 revisions, one head. Each upgrade skips anything that already exists. `alembic downgrade -1` undoes only the newest step.

## Environment variables (see backend/.env.example)
APP_ENV, OTP_DELIVERY, OTP_LENGTH, OTP_TTL_MINUTES, OTP_MAX_ATTEMPTS, OTP_RESEND_COOLDOWN_SECONDS, OTP_MAX_PER_HOUR, GEO_DEFAULT_RADIUS_KM,
DELIVERY_APPROVAL_REQUIRED, REQUIRE_EMAIL_VERIFICATION, APP_TIMEZONE, SMS_PROVIDER/TWILIO_*; existing SMTP_*. Frontend (optional): VITE_TILE_URL.
New Python packages: `pypdf` (PDF text), `tzdata` (timezones on Windows). Run `pip install -r requirements.txt`.

## Windows: run it
```powershell
cd backend ; .\venv\Scripts\Activate.ps1 ; pip install -r requirements.txt ; cd ..
.\backend\scripts\verify_everything.ps1          # static check, migration tests, new tests, your whole suite, npm test, npm run build
cd backend ; alembic upgrade head ; uvicorn app.main:app --reload          # after backing up and trying a COPY first
cd ..\frontend ; npm install ; npm run dev
```

## Decisions and risks you should know about
* Capacity means kilograms of donated items per trip (self-declared, shown as unverified), not passenger seats. Unknown never excludes anyone.
* Verification can never trap users: it is off by default and ignored when the server cannot send codes. Dev-only code delivery modes are refused in production.
* A recommendation never assigns anyone; volunteers accept, donors commit, only the receiving organization confirms receipt (counts what arrived, once).
* Others never receive coordinates, only a rounded distance; the shared live position is the latest only and is deleted when the delivery ends.
* `GET /needs/` still gives donors and volunteers the exact coordinates and address text of verified organizations' needs (pre-existing; not changed).
* The older `/donations` flow records gifts as already "confirmed" and runs separately from the new delivery workflow: decide whether to retire or link it.
* During this work I overwrote your `routers/verification.py` (organization verification) by mistake; the static check caught it and it was restored byte-for-byte
  from your upload. Every other original backend and frontend file was compared: only files I intended to change differ, and none is missing.
* Row locks protect against double allocation on PostgreSQL; the SQLite tests cannot exercise them.
