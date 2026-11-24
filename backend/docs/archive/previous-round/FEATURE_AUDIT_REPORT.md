# CareBridge AI - Feature Audit

Method: static reading of both codebases. Neither test suite could be run in the review environment (no network, no Python dependencies, Windows-built node_modules), so nothing here is "verified by execution".

## Already implemented (extend, do not rebuild)
- Auth: JWT sessions, lockout, rate limits, password-reset OTP, optional e-mail verification at sign-up (`REQUIRE_EMAIL_VERIFICATION`), administrator setup flow, audit service.
- Delivery workflow with stage-gated addresses/coordinates (`routers/deliveries.py`, `services/delivery_flow.py`) and volunteer live-location sharing during held tasks (`services/tracking.py`, `DeliveryLocation`).
- Distance features that return coarse values only (`services/geo.py`: ~1 km snapped positions, rounded distances, no addresses).
- AI: RAG (hybrid retrieval, confidence abstention), live-data retrieval scoped per role, streaming chat (`/chat`), agent planner/runner with human approval, ML models, optimisation tools (admin-only by default).

## Gaps against the brief
| Brief item | Current state |
|---|---|
| Phone number + country code at registration | DONE (this round): country-code selector + mobile field, stored as E.164, unique, never returned by APIs |
| SMS OTP / Indian DLT | DONE (this round, untested against a live provider): MSG91 template provider with DLT gating (`SMS_SENDER_ID`, `DLT_ENTITY_ID`, `DLT_TEMPLATE_ID` required before any +91 message), Twilio kept |
| Registration OTP activating the account | DONE: with `REQUIRE_PHONE_VERIFICATION=true` the account cannot sign in until the SMS code is confirmed; requesting a code never activates it. E-mail OTP unchanged. Not done: refresh tokens |
| GPS sharing by donors, organizations, admins | Partly present: volunteers share live position per delivery; donors/organizations can save an opt-in static position (`PUT /locations/me`, deletable). Not present: live donor sharing during pickup, organization live status, administrator tracking dashboard, access audit for location reads |
| Location retention | Delivery positions: latest only, no history, deleted when the delivery leaves its active stages. Saved static positions: kept until the owner deletes them. No scheduled purge, no encryption at rest beyond the database |
| 2D map with OpenStreetMap + clustering, 3D MapLibre mode | No Leaflet/MapLibre dependency in package.json; existing map is custom. No 3D mode |
| Redis / WebSocket live architecture | SSE only; no Redis |
| Role-specific dashboards | Exist; not redesigned |

## AI surfaces
| Route | Decision |
|---|---|
| /assistant (streaming `/chat`) | KEEP - the unified assistant |
| /assistant/classic | RETIRED. Chat duplicated /assistant (the `/chat` engine already uses the same live_assistant / live_retrieval / live_facts services). Knowledge tools and live insights preserved in /assistant/knowledge; the old URL redirects there |
| /agent | KEEP - separate plan -> approve -> run workflow |
| /admin/ai-lab | KEEP - ML tooling, not chat |

## Security findings
1. CRITICAL: `GET /needs/` leaked exact latitude/longitude and address text to donors and volunteers. Fixed (see MODIFICATION_REPORT).
2. The uploaded backend archive contained `.env`. It is excluded from the delivered zip. Rotate `SECRET_KEY` and the database password.
3. Audited and found acceptable: deliveries (stage-gated), nearby/map services (coarse), live retrieval (role-scoped, needs records carry no location), agent tools (route tool admin-only and returns IDs/distances only).
4. Residual to review: `donor.location` free text is included in live-retrieval records and donor profiles shown to admins/owning organizations (intended scoping, but confirm it matches your privacy policy).
