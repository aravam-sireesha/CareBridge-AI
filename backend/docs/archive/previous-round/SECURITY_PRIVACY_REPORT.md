# Security & Privacy Report

## Fixed
- GET /needs/ exposure of exact coordinates and address text to donors and volunteers: enforced in the API response schema, not the UI.

## Verified by reading code (not by running it)
- Delivery addresses/coordinates appear only at the workflow stages allowed by `delivery_flow.can_see_addresses`.
- Nearby-need and nearby-people responses use coarse distance and ~1 km snapped positions.
- Live-assistant retrieval scopes data by role; need records contain no location.
- Agent tools are admin-only unless explicitly marked; routing returns IDs and distances.

## Phone verification (round 2)
- Codes are cryptographic, stored only as keyed hashes, expire, are limited by attempts, resend cooldown and an hourly cap; requesting a code never activates an account; the lookup is by e-mail so the endpoints cannot be used to discover registered phone numbers; a duplicate number gets a generic refusal.
- Mobile numbers are stored as plain E.164 text in `users.phone_e164`, never returned by the user APIs and never logged (the SMS layer logs neither numbers nor codes). They are not encrypted at the application level.
- Registration itself still reveals whether an e-mail is already registered (existing behaviour, 409). Fully closing that needs a "check your inbox" flow for every sign-up.
- SMS credentials come only from environment variables.

## Open items
- Rotate `SECRET_KEY` and DB password (the `.env` was inside the uploaded archive).
- Delivery positions are latest-only and deleted when the delivery leaves its active stages; saved static positions persist until the owner deletes them. No scheduled purge or application-level encryption.
- Donor/organization/admin location consent flows are not implemented (see FEATURE_AUDIT_REPORT.md).
- Browser geolocation only works while the page is open; background tracking is not possible from a web page.
- The in-memory rate limiter is per server process; use a shared store (e.g. Redis) when running several workers.
