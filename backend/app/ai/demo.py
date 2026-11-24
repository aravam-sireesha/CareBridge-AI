"""A reproducible demo dataset (organizations, 18 months of needs, donors, volunteers, donations, resources) used by the benchmark
script and by the tests. Everything here is made up; it exists so the AI pipeline can be demonstrated and verified without real children's data."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from .. import models as m
from ..knowledge.default_kb import ENTRIES, with_keywords

CATS = [("Books", "education"), ("Meals", "food"), ("Clothes", "clothing"), ("Medicine", "medical"), ("Tutoring", "education")]


def build_demo(db, seed: int = 7, now: datetime | None = None, with_knowledge: bool = True) -> dict:
    rng = np.random.default_rng(seed)
    now = now or datetime(2026, 6, 30, 12, 0)
    if with_knowledge:
        for t, s, c in ENTRIES:
            db.add(m.KnowledgeBase(title=t, source=s, content=with_keywords(t, c)))
    orgs = [m.Organization(name=n, contact=f"{n.split()[0].lower()}@demo.org", verified=True, verification_status="verified", latitude=17.3 + 0.1 * i, longitude=78.4 + 0.1 * i)
            for i, n in enumerate(["Hope Home", "Little Stars", "Sunrise Shelter", "Bright Futures", "Kind Hearts"])]
    db.add_all(orgs)
    db.flush()
    needs = []
    for age_months in range(17, -1, -1):
        for ci, (cat, _) in enumerate(CATS):
            lam = 1.2 + 0.18 * (17 - age_months) * (ci in (0, 3)) + 1.0 * np.sin(2 * np.pi * age_months / 12 + ci)  # rising books/medicine, seasonal others
            for _ in range(int(max(0, rng.poisson(max(lam, 0.2))))):
                created = now - timedelta(days=30 * age_months + int(rng.integers(0, 28)))
                urg = rng.choice(["low", "medium", "high", "critical"], p=[.2, .4, .28, .12])
                qty = int(np.clip(rng.lognormal(3.0, 0.7), 2, 300))
                org = orgs[int(rng.integers(0, len(orgs)))]
                quick = rng.random() < (0.35 + 0.12 * ["low", "medium", "high", "critical"].index(urg))
                done = None
                status = "open"
                if age_months >= 1 and rng.random() < 0.8:
                    days = float(rng.uniform(1, 14)) if quick else float(14 + rng.gamma(2.0, 8.0))
                    done = created + timedelta(days=days)
                    if done < now:
                        status = "fulfilled"
                    else:
                        done = None
                needs.append(m.Need(org_id=org.id, category=cat, quantity=qty, urgency=urg, status=status, created_at=created, fulfilled_at=done if status == "fulfilled" else None,
                                    beneficiaries=int(max(1, qty // 2)), latitude=org.latitude + float(rng.normal(0, 0.02)), longitude=org.longitude + float(rng.normal(0, 0.02))))
    db.add_all(needs)
    donors = [m.Donor(name=f"Donor {i + 1}", contact=f"d{i + 1}@demo.org", preferences=CATS[i % len(CATS)][1] + (", food" if i % 7 == 0 else ""), location="Hyderabad") for i in range(25)]
    vols = [m.Volunteer(name=f"Volunteer {i + 1}", contact=f"v{i + 1}@demo.org", skills=["teaching", "cooking", "first aid", "tutoring", "sewing"][i % 5], availability=["weekends", "evenings", "full time", "mornings"][i % 4],
                        location="Hyderabad", organization_id=orgs[i % 5].id if i % 3 == 0 else None) for i in range(15)]
    resources = [m.Resource(organization_id=orgs[i % 5].id, name=n, category=c, quantity_total=q, quantity_available=q, unit=u)
                 for i, (n, c, q, u) in enumerate([("Textbook sets", "books", 70, "sets"), ("Meal packs", "food", 90, "packs"), ("Winter clothes", "clothing", 40, "sets"),
                                                   ("First-aid kits", "medical", 25, "kits"), ("Tutoring hours", "education", 60, "hours"), ("Story books", "books", 50, "books")])]
    db.add_all(donors + vols + resources)
    db.flush()
    gifts = []
    open_needs = [n for n in needs if n.status == "open"] or needs[-10:]
    for i in range(120):
        d = donors[int(rng.integers(0, len(donors)))]
        n = open_needs[int(rng.integers(0, len(open_needs)))]
        gifts.append(m.Donation(donor_id=d.id, need_id=n.id, amount=float(np.round(rng.lognormal(7.0, 0.6), 0)), timestamp=now - timedelta(days=int(rng.integers(0, 400)), hours=int(rng.integers(8, 20)))))
    gifts.append(m.Donation(donor_id=donors[3].id, need_id=open_needs[0].id, amount=980000.0, timestamp=now - timedelta(days=2, hours=3)))   # injected: huge gift
    for k in range(5):                                                                                                      # injected: burst of gifts
        gifts.append(m.Donation(donor_id=donors[8].id, need_id=open_needs[1].id, amount=4000.0, timestamp=now - timedelta(days=1, minutes=7 * k)))
    db.add_all(gifts)
    db.commit()
    return {"orgs": orgs, "needs": needs, "donors": donors, "volunteers": vols, "resources": resources, "now": now}
