# Implementation Plan

Done: Phase 1 audit; Phase 2 (duplicate assistant retired); Phase 3 (phone + SMS OTP, DLT-aware); Phase 6 (GET /needs/ fix).

Remaining, in recommended order:
1. Run both test suites locally and fix anything the edits broke (see TEST_REPORT.md). Run `alembic upgrade head` on a copy of your database.
2. Live location consent for donors during an active pickup/delivery and for organizations; an administrator tracking view limited to active, relevant sessions with every read written to the audit log; a scheduled purge for stale sessions. Build on `DeliveryLocation` (latest-only, deleted at the end of the delivery) rather than adding a second location table.
3. Map: add Leaflet + OpenStreetMap tiles with clustering; optional MapLibre 3D mode behind a 2D/3D toggle (`npm install leaflet maplibre-gl`; needs network).
4. JWT refresh tokens (the current design uses one access token with a server-side `token_version`).
5. Dashboard consolidation after an audit of repeated cards.
6. Remaining duplicate-code audit (routes, fields, unused dependencies), checking dependents before each deletion.
