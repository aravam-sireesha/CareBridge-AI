"""Fill the database with realistic demo rows so every screen has data to read.

    python scripts/seed_demo.py --org-email your-org@example.org

* attaches children / needs / donors / volunteers / donations to that organization account
* marks the organization as verified so donor and volunteer accounts can see its needs
* adds RAG knowledge-base entries when the table is empty (then run embed_knowledge_base.py)
Safe to re-run: it does nothing if the organization already has data (use --force to add more).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402

KNOWLEDGE = [
    ("What CareBridge Does", "CareBridge is an AI-assisted platform that connects child-welfare organizations with donors and volunteers. AI components only recommend; administrators make every final decision.", "CareBridge Overview"),
    ("Career Guidance Module", "The career guidance module suggests three possible career paths for a child profile using a similarity recommender plus the child's stated interest. Suggestions are reviewed and accepted, modified or rejected by an administrator.", "CareBridge Technical Docs"),
    ("Fraud Detection Module", "Donations are screened for unusual patterns such as an amount far above the donor's history, a large first donation, or many donations within an hour. Flags are reviewed by an administrator before any action.", "CareBridge Technical Docs"),
    ("Donor and Volunteer Matching", "Open needs are matched to donors by preference and to volunteers by skills and availability, weighted by urgency. Every suggested match shows its score and reasons and must be confirmed or rejected by an administrator.", "CareBridge Technical Docs"),
    ("Need Alerts", "Open needs are flagged when they are high urgency, have stayed open too long, or request an unusually large quantity. Administrators mark each alert as actioned or dismissed.", "CareBridge Technical Docs"),
    ("Volunteer Background Check Policy", "Volunteers working directly with children must complete a background verification recorded by an organization administrator before a match can be confirmed.", "CareBridge Policy Manual"),
    ("Donation Receipt Process", "Donors receive a confirmation after a donation is recorded. Official receipts are issued by the receiving organization, normally within seven working days.", "CareBridge FAQ"),
    ("Data Privacy for Children", "Child records are visible only to authenticated administrators and to the organization that owns the record. Donors and volunteers never see child details.", "CareBridge Policy Manual"),
    ("Organization Verification", "New organizations register with an organization account. An administrator verifies the organization before its needs become visible to donors and volunteers.", "CareBridge FAQ"),
    ("Urgency Levels", "Needs are marked low, medium, high or critical. High and critical needs are prioritised in alerts and matching suggestions.", "CareBridge Policy Manual"),
    ("Password Reset", "Use Forgot password on the sign-in page. A one-time reset code is e-mailed when the server has e-mail delivery configured; the code expires after 30 minutes.", "CareBridge FAQ"),
    ("Reporting a Concern", "Anyone who notices a suspicious donation or an incorrect match should tell an administrator. Every flag is stored with its reasons and reviewed manually.", "CareBridge FAQ"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-email", required=True, help="e-mail of an existing organization account")
    parser.add_argument("--force", action="store_true", help="add demo rows even if data already exists")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == args.org_email.strip()).first()
        if user is None or user.organization_id is None:
            raise SystemExit("No organization account with that e-mail. Register it first (role: organization).")
        org = db.get(models.Organization, user.organization_id)
        org.verified = True
        has_data = db.query(models.Need).filter(models.Need.org_id == org.id).count() > 0
        if has_data and not args.force:
            print("Organization already has needs - skipping demo rows (use --force to add more).")
        else:
            now = datetime.utcnow()
            children = [
                (9, "Drawing, storytelling", "Painting", "Good in language, needs maths support"),
                (12, "Cricket, science projects", "Team sports", "Above average, loves science"),
                (15, "Computers, robotics", "Basic coding", "Strong in maths and physics"),
                (7, "Music, dancing", "Singing", "Needs reading support"),
                (16, "Cooking, business ideas", "Cooking", "Good in commerce subjects"),
            ]
            for age, interests, skills, perf in children:
                db.add(models.Child(org_id=org.id, age=age, interests=interests, skills=skills, academic_performance=perf))
            needs = [
                ("School supplies", 120, "high"), ("Nutritious meals", 300, "critical"),
                ("Medical check-up kits", 40, "medium"), ("Winter clothing", 80, "medium"),
                ("Tutoring hours", 60, "low"),
            ]
            created_needs = []
            for i, (category, qty, urgency) in enumerate(needs):
                need = models.Need(org_id=org.id, category=category, quantity=qty, urgency=urgency, status="open",
                                   created_at=now - timedelta(days=i * 3 + 1))
                db.add(need)
                created_needs.append(need)
            donors = [("Asha Foundation", "education, school supplies", "Hyderabad"),
                      ("Ravi Kumar", "food, nutrition", "Bengaluru"),
                      ("Green Leaf Trust", "medical, health", "Chennai")]
            created_donors = []
            for name, pref, loc in donors:
                donor = models.Donor(name=name, contact=f"{name.split()[0].lower()}@example.org", preferences=pref,
                                     location=loc, organization_id=org.id)
                db.add(donor)
                created_donors.append(donor)
            for name, skills, avail, loc in [("Meena Iyer", "tutoring, mentoring", "weekends", "Hyderabad"),
                                             ("Arjun Rao", "first aid, health awareness", "evenings", "Chennai"),
                                             ("Sana Khan", "career guidance, mentoring", "weekends", "Bengaluru")]:
                db.add(models.Volunteer(name=name, contact=f"{name.split()[0].lower()}@example.org", skills=skills,
                                        availability=avail, location=loc, organization_id=org.id))
            db.flush()
            amounts = [5000, 4500, 6000, 5200, 4800, 52000]  # last one is deliberately unusual
            for i, amount in enumerate(amounts):
                donor = created_donors[i % len(created_donors)] if i < 5 else created_donors[0]
                db.add(models.Donation(donor_id=donor.id, need_id=created_needs[i % len(created_needs)].id,
                                       amount=float(amount), resource_description="Demo donation",
                                       timestamp=now - timedelta(days=(len(amounts) - i) * 20)))
            print("Demo children, needs, donors, volunteers and donations added.")

        if db.query(models.KnowledgeBase).count() == 0:
            for title, content, source in KNOWLEDGE:
                db.add(models.KnowledgeBase(title=title, content=content, source=source))
            print(f"{len(KNOWLEDGE)} knowledge-base entries added. Now run: python scripts/embed_knowledge_base.py")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
