"""Create the FIRST administrator from the command line (alternative to the /admin/setup page).

Safe by design:
  * refuses to run if any administrator already exists (add more under Administration > Team);
  * never changes or promotes an existing account, and never overwrites a password;
  * enforces the same password rules as the website, asks twice, and never echoes the password;
  * creates the profile row and writes an audit entry.

Usage (PowerShell, from the backend folder):   python scripts/create_admin.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from getpass import getpass

from sqlalchemy import func, text

from app import auth, models
from app.database import SessionLocal
from app.services import audit, security

LOCK_KEY = 724_018_001   # same key as the /admin/setup endpoint, so the two can never race each other


def main() -> None:
    db = SessionLocal()
    try:
        if db.query(models.User.id).filter(models.User.role == "admin").first() is not None:
            raise SystemExit("An administrator already exists. Sign in and add more under Administration > Team.")
        email = input("Administrator email: ").strip().lower()
        full_name = input("Full name: ").strip()
        if "@" not in email or not full_name:
            raise SystemExit("A valid email and a name are required.")
        if db.query(models.User).filter(func.lower(models.User.email) == email).first():
            raise SystemExit("An account with this email already exists. Use a different email.")
        password = getpass("Password (12+ characters, three kinds of characters): ")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        problems = security.password_problems(password, email)
        if problems:
            raise SystemExit("Password is too weak: " + "; ".join(problems))

        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        if db.query(models.User.id).filter(models.User.role == "admin").first() is not None:
            raise SystemExit("An administrator was created in the meantime. Nothing was changed.")
        user = models.User(email=email, hashed_password=auth.hash_password(password), role="admin")
        db.add(user)
        db.flush()
        profile = models.Administrator(user_id=user.id, full_name=full_name, is_active=True)
        db.add(profile)
        db.flush()
        audit.record(db, {"id": user.id, "email": email, "role": "admin"}, "admin.setup_completed",
                     "administrator", profile.id, {"via": "cli"})
        db.commit()
        print(f"Administrator created: {email}. Sign in at /admin/login.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
