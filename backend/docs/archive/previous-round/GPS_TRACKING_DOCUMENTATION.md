# GPS Tracking (current state)

Implemented
- Volunteer live sharing per delivery (`POST /deliveries/{id}/tracking/start`, `PUT /deliveries/{id}/location`, `POST .../tracking/stop`, `GET .../location`). Opt-in, only while the task is in a holding stage (accepted, pickup scheduled, picked up, in transit), only the assigned volunteer can share, watchers are limited by `services/tracking.can_view`. One row per delivery holds the latest position only (no movement history) and is removed when the delivery leaves its active stages.
- Donors, volunteers and organizations can save an opt-in static position (`PUT /locations/me`) and delete it (`DELETE /locations/me`). Other people receive only distances rounded up to whole km and positions snapped to a ~1 km grid, never addresses.
- `GET /needs/` no longer exposes exact need coordinates or addresses to donors and volunteers.

Not implemented: live sharing by donors during pickup, organization live status, an administrator tracking dashboard, audit entries for location reads, a scheduled purge, live/stale/unavailable marker states beyond the delivery page, Redis/WebSockets, 3D map.

Browser limits: geolocation works in the foreground only, needs HTTPS (except localhost) and explicit permission; accuracy varies and can be coarse indoors.
