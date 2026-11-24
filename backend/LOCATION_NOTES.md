# Location support (round 4, phase 1)

Saved, opt-in location for organizations, donors and volunteers. NOT live GPS tracking.

## Apply
```powershell
pg_dump -U <user> -h localhost -Fc -f carebridge_backup.dump <dbname>   # backup first
cd backend ; alembic upgrade head ; python scripts\check_schema.py
python -m pytest tests\test_geo.py tests\test_locations.py -q ; python -m pytest -q
cd ..\frontend ; npm install ; npm run build ; npm run dev
```
Migration `20261024_locations` only ADDS nullable columns (donors: latitude, longitude, location_updated_at;
volunteers: the same plus service_radius_km). Existing rows are untouched (NULL = not shared).

## Endpoints
GET/PUT/DELETE /locations/me, GET /locations/nearby-needs, GET /locations/needs/{id}/nearby.

## Privacy rules
- Exact coordinates: owner only. Others get a distance rounded UP to whole km (stops trilateration by probe needs).
- Organizations see only their own donors/volunteers; administrators see all.
- Audit log records that a location changed, never the coordinates.
- Distances are straight-line (haversine), not road routes or travel times.
- Matching scores are unchanged; distance is a reason, a tie-breaker, and (volunteers with a set travel range) an eligibility rule.
- Config: GEO_DEFAULT_RADIUS_KM (default 25, clamped 1..500).
- Browsers share location only on https or localhost.

## Known gaps
- GET /needs/ still gives donors/volunteers exact need coordinates and address text (pre-existing; not changed).
- The need form has no coordinate fields; needs fall back to the organization's saved location.
- Donor/volunteer records created by an organization (no account) cannot be located by anyone.
- No map view and no live tracking (needs a delivery-task model first).
