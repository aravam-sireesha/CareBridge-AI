# Location, tracking and navigation: where it is and how to use it

Everything is opt-in. Nobody's position is stored until that person presses a button, and other people never see exact
coordinates except where a delivery needs it (see "Who sees what").

## 1. Save your location (everyone except administrators)
**Where:** profile menu (top right) > Settings > **Location** tab (`/settings?tab=location`).
1. Press **Use my current location** (your browser asks permission), or type latitude and longitude yourself.
2. Check the numbers, then press **Save location**. Nothing is saved before this.
3. Volunteers can also set **how far they can travel** (km). Organizations: this sets where your needs are measured from.
4. **Remove my location** deletes it at any time.
Organizations and donors should do this FIRST: it is what puts their pickup and delivery places on the map for volunteers.

## 2. Find needs and helpers near you
* **Donors and volunteers:** Dashboard > **Needs near you** (rounded distance such as "within 5 km"; change the radius there).
* **Organizations and administrators:** Needs > open a need > **Helpers near this need**.
* **Organizations:** AI matching shows a distance reason for each suggested donor and volunteer.

## 3. Navigation and live tracking for a delivery
**Where:** sidebar > **Deliveries** (volunteers see **My tasks**, donors **My deliveries**, administrators **Delivery approvals**)
> open a delivery > the **Navigation and live location** panel at the top of the details.

**Volunteer**
1. Accept the task. The panel then shows the pickup and delivery places on the map (if the donor and organization saved a location).
2. Press **Navigate** to open the destination in Google Maps, **Open in maps app** for your phone's own app, or **OpenStreetMap**.
3. Optional: press **Start sharing my location**. Read the explanation first. Your phone then sends your position about every 6 seconds while this page is open.
4. **Stop sharing** erases your position immediately. It is also erased automatically when the delivery is delivered, cancelled, reported as a problem, or you step back.
5. Keep the page open and the screen on: browsers pause location in the background.

**Organization, donor, administrator**
* After the volunteer has **picked up** the items, the same panel shows a live map of the delivery. It says "Waiting for the volunteer" until a
  position arrives, shows **Live** with its age when fresh, and **Last known position** when older than 2 minutes. Positions are rounded to about 11 m.

## Who sees what
| | Pickup place | Delivery place | Volunteer's live position |
|---|---|---|---|
| Volunteer (assigned) | after accepting, until the job ends | after accepting, until the job ends | their own, exact |
| Donor (giving) | their own | yes | during pickup/transit, rounded |
| Organization (receiving) | no (never sees donor coordinates) | their own | during pickup/transit, rounded |
| Administrator | yes | yes | during pickup/transit, rounded |
| Anyone else | no | no | no (they cannot even tell the delivery exists) |

## What it does NOT do (so nobody assumes it does)
* No road routes, turn-by-turn guidance or arrival times inside CareBridge: it shows straight-line distance and hands the destination to a real maps app.
* No movement history: only the latest position exists, and it is deleted when the delivery ends.
* No tracking in the background: when the page or phone screen closes, sending stops.
* Browsers share location only on **https** pages or on `localhost`.

## Setup
* Backend: `alembic upgrade head` (adds `delivery_locations`; additive only). Back up first.
* Map pictures come from OpenStreetMap by default (free, no account, credit shown). For a busy production site set `VITE_TILE_URL`
  in `frontend/.env` to a tile provider you have an account with, using `{z}`, `{x}`, `{y}` in the URL.
* If the pictures cannot load, the map says so and the navigation links keep working.
