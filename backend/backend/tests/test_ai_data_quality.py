"""Phase 1: reliable data."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.ai import data_quality as dq
from app.database import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def clean_world(db):
    org = m.Organization(name="Hope", contact="c", verified=True, verification_status="verified")
    db.add(org)
    db.flush()
    need = m.Need(org_id=org.id, category="Books", quantity=40, urgency="high", status="open")
    donor = m.Donor(name="Edu", contact="e", preferences="education")
    db.add_all([need, donor])
    db.flush()
    db.add(m.Donation(donor_id=donor.id, need_id=need.id, amount=100))
    db.add(m.Resource(organization_id=org.id, name="Books", category="books", quantity_total=30, quantity_available=30))
    db.commit()
    return org, need, donor


def codes(report):
    return {i["code"] for i in report["issues"]}


def test_a_consistent_database_passes(db):
    clean_world(db)
    rep = dq.check(db)
    assert rep["ok"] and rep["errors"] == 0 and rep["issues"] == [] and rep["tables"]["needs"] == 1


def test_orphans_and_bad_values_are_reported_with_examples(db):
    org, need, donor = clean_world(db)
    db.add(m.Donation(donor_id=999, need_id=888, amount=-5))
    db.add(m.Need(org_id=777, category="X", quantity=-3, urgency="urgent!!", status="open"))
    db.add(m.User(email="o@x.org", hashed_password="x", role="organization"))
    db.commit()
    rep = dq.check(db)
    assert not rep["ok"] and rep["errors"] >= 4
    assert {"donation_need", "donation_donor", "need_org", "need_quantity", "need_vocab", "donation_value", "user_profile"} <= codes(rep)
    first = [i for i in rep["issues"] if i["code"] == "donation_need"][0]
    assert first["category"] == "relationship" and "888" in first["examples"][0] and first["hint"]


def test_inventory_must_add_up_and_can_be_repaired(db):
    org, need, donor = clean_world(db)
    res = db.query(m.Resource).one()
    db.add(m.ResourceAllocation(resource_id=res.id, need_id=need.id, quantity=10, status="approved"))
    db.commit()  # allocation approved, but stock was never reduced
    rep = dq.check(db)
    stock = [i for i in rep["issues"] if i["code"] == "resource_stock"][0]
    assert stock["auto_fixable"] and "expected 20" in stock["examples"][0]
    assert dq.repair(db, ["resource_stock"]) == {"resource_stock": 1}
    assert db.query(m.Resource).one().quantity_available == 20 and "resource_stock" not in codes(dq.check(db))
    with pytest.raises(ValueError):
        dq.repair(db, ["delete_everything"])


def test_over_allocation_and_flags_and_duplicates(db):
    org, need, donor = clean_world(db)
    res = db.query(m.Resource).one()
    db.add(m.ResourceAllocation(resource_id=res.id, need_id=need.id, quantity=45, status="delivered"))
    org.verified, org.verification_status = False, "verified"
    db.add(m.Donor(name="Edu", contact="e"))
    db.add(m.Need(org_id=org.id, category="Books", quantity=5, urgency="low", status="open"))
    db.commit()
    c = codes(dq.check(db))
    assert {"over_allocation", "verification_flags", "duplicate_donors", "duplicate_needs"} <= c
    dq.repair(db, ["verification_flags"])
    assert db.get(m.Organization, org.id).verification_status == "pending"


def test_calculation_rules_are_validated(db):
    org, need, donor = clean_world(db)
    db.add(m.DonorSuggestion(need_id=need.id, donor_id=donor.id, fit_score=0.8, urgency_score=0.6, priority_score=0.9, reasons=[], model_version="t"))
    db.commit()
    rule = [i for i in dq.check(db)["issues"] if i["code"] == "rule_ranges"][0]
    assert rule["category"] == "calculation" and "0.5 x urgency + 0.5 x fit" in rule["examples"][0]
