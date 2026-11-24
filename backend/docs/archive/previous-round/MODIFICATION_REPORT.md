# Modification Report

## Backend
- `app/schemas.py`: added `AdminNeedResponse`, `OrganizationNeedResponse`, `DonorNeedResponse`, `VolunteerNeedResponse` (+ `ApproxPosition`). Donor/volunteer schemas contain no latitude, longitude or address fields.
- `app/routers/needs.py`: `GET /needs/` now chooses the schema by role; donor/volunteer rows are built from an allow-list (`_public_need_dict`) and only expose `approximate_position` rounded to one decimal (~11 km). Donors and volunteers see only needs of verified organizations; organizations see only their own; unknown roles get 403. Admin and organization output is unchanged.
- `tests/test_needs_privacy.py`: new tests (donor, volunteer, other organization, donor write attempt).

## Frontend
- New `src/pages/KnowledgeCenter.jsx` (knowledge status, add entry, load guide, reindex, unanswered-question gaps, live insights). Route `/assistant/knowledge`.
- `/assistant/classic` now redirects to `/assistant/knowledge`; `AssistantClassic.jsx` deleted. Link in `Assistant.jsx` renamed "Knowledge & insights".
- Tests updated: `hub-guide.test.jsx`, `admin-theme.test.jsx`, `e2e.test.jsx`. Three assertions about the retired classic chat bubble (live-record card, low-confidence notice, confidence label) were removed or converted; the backend `/assistant/ask` API they exercised is untouched.

## Phone / SMS OTP (round 2)
Backend
- `alembic/versions/20261105_phone_verification.py`: adds `users.phone_e164` (unique index), `phone_verification_pending`, `phone_verified_at`; all nullable, so no existing account is affected; reversible.
- `app/models.py`, `app/schemas.py`: new columns; `UserRegister` accepts `phone_country_code` + `phone` and normalises to E.164 (Indian numbers must be +91 and 10 digits starting 6-9).
- `app/services/sms.py`: `Msg91Provider` (template API, DLT gate for +91, success judged from the response body), `delivery_mode`, `verification_required`, dev `outbox`/`console` modes (refused unless `APP_ENV` is development/test), `is_valid_mobile`. Twilio unchanged.
- `app/routers/phone_verification.py`: `GET /auth/phone-verification/config`, `POST /auth/verify-phone/request`, `POST /auth/verify-phone/confirm`. Reuses the existing OTP code path (keyed hashes, expiry, attempt limit, resend cooldown, hourly cap) and looks the account up by e-mail, not phone.
- `app/routers/auth.py`: register stores the number, rejects duplicates, marks the account pending when required; login refuses a pending account.
- `.env.example`: MSG91/DLT and phone-verification settings.
Frontend
- `CodeVerification.jsx` (generic one-time-code form) now backs both `EmailVerification.jsx` and the new `PhoneVerification.jsx`; new `/verify-phone` page; Register has a country-code selector and mobile field and walks phone then e-mail verification; Login links to `/verify-phone` when needed. The old free-text "Mobile / contact" field is now "Other contact (optional)".
Tests
- New: `tests/test_phone_verification_api.py`, MSG91/DLT/policy tests in `tests/test_sms.py`, `tests/phone-verification-lib.test.jsx`. Updated: `tests/test_migrations_sqlite.py`, `tests/e2e.test.jsx` (new field, unique number per run).

## Not changed
GPS sharing, map, dashboards.
