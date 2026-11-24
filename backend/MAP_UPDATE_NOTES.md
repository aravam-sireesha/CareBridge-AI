# CareBridge map update

19 files: 14 changed, 5 new (list at the bottom). No database change, so no Alembic migration.

## What is new
| Who | Where | What |
|---|---|---|
| Administrator | Sidebar > Records > **Map overview** (`/admin/map`) | One map with organizations, open needs, donors, volunteers and live deliveries. Layer switches, urgency filter, verified-only filter. A panel lists **needs with no volunteer in range** (click one to jump to it); each volunteer's own travel range is respected. Live deliveries refresh every 30 s. Records with no saved location are counted, never guessed. |
| Donor / volunteer | Dashboard > Needs near you | **List / Map** switch. The map shows you, a dashed search ring and the needs, coloured by urgency. Select a pin to open the need. |
| Organization | Needs > open a need > Helpers near this need | **Show reach on a map**: the need and its search ring. |
| Everyone with a map | Delivery map | Pan fix: dragging and the arrow keys moved the map the wrong way before. |

## Privacy decisions (please review)
* Donor and volunteer positions are **never sent to organizations** (your existing test requires this). The organization map shows only the ring and counts.
* Administrators see donors and volunteers snapped to about 1 km, never exact. Organization and need pins are exact to about 11 m.
* Donors and volunteers see need pins snapped to about 1 km, not the organization's door.
* Live deliveries follow the existing rule: only while picked up or in transit.
* One existing assertion in `backend/tests/test_locations.py` was made more precise: the old text check also matched the organization's own published place, which the map now needs. It still proves no donor or volunteer coordinate appears.

## Apply (PowerShell)
Back up first, then unzip over the project (only the 19 files below are touched):
```powershell
cd C:\Users\JNR_R\carebridge-ai2
Copy-Item -Recurse backend backend_backup_before_map
Copy-Item -Recurse frontend frontend_backup_before_map -Exclude node_modules
Expand-Archive -Path "$HOME\Downloads\carebridge-map-update.zip" -DestinationPath . -Force
```
Backend tests, then run:
```powershell
cd backend
python -m pytest tests/test_map_overview.py tests/test_locations.py -q
uvicorn app.main:app --reload
```
Frontend:
```powershell
cd ..\frontend
npm test
npm run dev
```
Try it: log in as admin, open Map overview. Pins appear only for records that have a saved location (Settings > Location for donors, volunteers and organizations).

## Files
Backend: app/main.py, app/routers/admin_map.py (new), app/routers/locations.py, app/services/geo.py, app/services/map_overview.py (new), tests/test_locations.py, tests/test_map_overview.py (new)
Frontend: src/App.jsx, src/api/client.js, src/components/{Layout,NearbyHelpers,NearbyNeeds,TileMap}.jsx, src/components/MapLegend.jsx (new), src/lib/mapLayers.js (new), src/lib/mapMath.js, src/map.css, src/pages/AdminMap.jsx (new), tests/map-layers.test.jsx (new)
