# What still needs YOUR machine, and exactly how to check it

Everything below was impossible in the sandbox this code was written in (no PostgreSQL, no GPS, no internet, no npm packages).
Do these in order. Each step says what you should see. If anything differs, send me the exact output.

## 0. One command for everything that does not need your database
```powershell
cd <folder containing backend and frontend>
cd backend ; .\venv\Scripts\Activate.ps1 ; cd ..
.\backend\scripts\verify_everything.ps1
```
You get a PASS/FAIL table covering: the static consistency check, the migration tests, the pure-logic tests, the API tests for the
new features, your whole existing backend suite, `npm test` and `npm run build`.

## 1. Run the migrations on a COPY of your database first
```powershell
pg_dump -U <user> -h localhost -Fc -f carebridge_backup.dump <dbname>          # your safety net
createdb -U <user> -h localhost carebridge_verify
pg_restore -U <user> -h localhost -d carebridge_verify carebridge_backup.dump
# point the backend at the COPY: in backend\.env set DATABASE_URL so it ends with /carebridge_verify (the same variable your backend already reads)
cd backend
alembic current                    # shows where the copy is now
alembic upgrade head               # applies locations, otp, deliveries, tracking, availability, email verification
python scripts\check_schema.py     # expect: schema matches the models
python -m pytest tests\test_migrations_sqlite.py -q
```
**Expect:** `alembic upgrade head` ends without an error; `alembic current` shows `20261029_email_verification`; `check_schema.py` reports no missing tables or columns.

Check that no data was lost (run in psql against the COPY and against your original, before and after; the numbers must match):
```sql
SELECT 'users', count(*) FROM users UNION ALL SELECT 'needs', count(*) FROM needs UNION ALL SELECT 'donors', count(*) FROM donors
UNION ALL SELECT 'volunteers', count(*) FROM volunteers UNION ALL SELECT 'organizations', count(*) FROM organizations UNION ALL SELECT 'donations', count(*) FROM donations;
```
Only when the copy is happy, repeat `alembic upgrade head` on the real database (keep the dump).
To undo the newest step: `alembic downgrade -1` (this deletes only what that step created).

## 2. Real GPS
Browsers share location only on https or localhost.
* **Desktop (no phone needed):** open the app in Chrome, press F12 > three dots > More tools > **Sensors** > Location: choose a city or enter
  coordinates. In Settings > Location press "Use my current location": the fields fill with those numbers.
* **A real phone, with real GPS:** connect the phone by USB, enable USB debugging, then in desktop Chrome open `chrome://inspect/#devices` >
  **Port forwarding** > add `5173 -> localhost:5173`. On the phone open `http://localhost:5173`: the phone treats it as a secure origin, so GPS works.
  Sign in as a volunteer who has accepted a delivery, open Deliveries > the delivery > **Start sharing my location**.
  **Expect:** the blue "You" marker appears at your real position; the status line says "last sent just now" and refreshes about every 6 seconds.
  Walk 50 m: the marker moves. Press **Stop sharing**: it must stop. On a second device signed in as the organization (delivery status picked up or in transit) the volunteer marker appears,
  and goes grey "last known" about 2 minutes after you stop.

## 3. Real map pictures
Open the delivery map and the browser's Network tab. **Expect:** requests to `tile.openstreetmap.org/<z>/<x>/<y>.png` returning 200, and
"© OpenStreetMap contributors" in the corner. If they fail, the map shows a clear message and the Navigate links still work.
For a busy site set `VITE_TILE_URL` in `frontend\.env` to a tile provider you have an account with.

## 4. Recovery codes by email
Set `SMTP_HOST`, `SMTP_FROM` (and port/username/password) in `backend\.env`, then use Forgot password with a real account. **Expect:** an email with a
6-digit code; a wrong code 5 times burns it; the same code cannot be used twice. Without SMTP, use local testing:
`APP_ENV=development` and `OTP_DELIVERY=console` (the code prints in the backend window).

## 5. Registration verification (off until you turn it on)
In `backend\.env` set `REQUIRE_EMAIL_VERIFICATION=true` together with working `SMTP_HOST` and `SMTP_FROM`, restart the backend, and register a NEW test account.
**Expect:** after the form you see "Verify your email"; a 6-digit code arrives; signing in before verifying says to verify first and shows a "Verify your email" link;
after entering the code you can sign in. Existing accounts (including administrators) must still sign in normally. If you cannot send mail, leave it `false`, or let an
administrator allow someone in with `POST /auth/verify-email/admin/{user_id}`.

## 6. Spoken replies
Open the AI assistant, choose a language in the selector, ask a question and press **Listen** under the answer. **Expect:** it reads the answer (without symbols),
Pause/Resume/Stop work, and starting a second answer stops the first. If the device has no voice for that language you see a message instead of mispronounced speech.
