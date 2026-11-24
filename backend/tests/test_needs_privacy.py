"""GET /needs/ must never hand exact coordinates or address text to donors, volunteers or other organizations."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.auth import hash_password
from app.database import Base, get_db
from app.main import app

PASSWORD = "StrongPass1234!"
EXACT_LAT, EXACT_LON, ADDRESS = 14.467891, 78.824567, "12 Private Lane, Kadapa"
FORBIDDEN_KEYS = {"latitude", "longitude", "location", "address", "lat", "lon"}


def _walk_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_keys(v)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    org = m.Organization(name="Hope", contact="c", verified=True)
    other = m.Organization(name="Other", contact="c", verified=True)
    unverified = m.Organization(name="Pending", contact="c", verified=False)
    db.add_all([org, other, unverified])
    db.flush()
    for o in (org, other, unverified):
        db.add(m.Need(org_id=o.id, category="Food", quantity=5, urgency="high", status="open", title=f"{o.name} need",
                      location=ADDRESS, latitude=EXACT_LAT, longitude=EXACT_LON))
    for email, role, org_id in [("org@x.org", "organization", org.id), ("other@x.org", "organization", other.id),
                                ("donor@x.org", "donor", None), ("vol@x.org", "volunteer", None)]:
        db.add(m.User(email=email, hashed_password=hash_password(PASSWORD), role=role, organization_id=org_id))
    db.commit()

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        def headers(email):
            token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}
        yield client, headers
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


@pytest.mark.parametrize("email", ["donor@x.org", "vol@x.org"])
def test_donor_and_volunteer_never_receive_exact_location_or_address(world, email):
    client, headers = world
    res = client.get("/needs/", headers=headers(email))
    assert res.status_code == 200
    body = res.json()
    assert body, "verified organizations' needs should still be listed"
    assert not (FORBIDDEN_KEYS & set(_walk_keys(body)))
    raw = res.text
    assert ADDRESS not in raw and "14.467891" not in raw and "78.824567" not in raw
    assert all(n["organization_name"] != "Pending" for n in body)          # unverified orgs stay hidden
    assert body[0]["approximate_position"] == {"lat": 14.5, "lon": 78.8}   # coarse area only


def test_organization_sees_only_own_needs_with_full_detail(world):
    client, headers = world
    body = client.get("/needs/", headers=headers("org@x.org")).json()
    assert [n["organization_name"] for n in body] == ["Hope"]
    assert body[0]["latitude"] == EXACT_LAT and body[0]["location"] == ADDRESS


def test_other_organization_cannot_read_or_edit_this_organizations_needs(world):
    client, headers = world
    body = client.get("/needs/", headers=headers("other@x.org")).json()
    assert all(n["organization_name"] == "Other" for n in body)
    hope_need = client.get("/needs/", headers=headers("org@x.org")).json()[0]["id"]
    assert client.patch(f"/needs/{hope_need}", headers=headers("other@x.org"), json={"status": "open"}).status_code == 404


def test_donor_cannot_modify_needs(world):
    client, headers = world
    need_id = client.get("/needs/", headers=headers("donor@x.org")).json()[0]["id"]
    assert client.patch(f"/needs/{need_id}", headers=headers("donor@x.org"), json={"status": "closed"}).status_code in (403, 404)
