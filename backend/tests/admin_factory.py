"""Test helper: create an administrator directly in the test database.

Public sign-up no longer exists, so tests that just need an admin account insert one, exactly like the
first-administrator setup would. The setup flow itself is tested in test_admin_setup.py."""
from app import models
from app.auth import hash_password
from app.database import get_db
from app.main import app


def make_admin(client, email="boss@x.org", password="StrongPass1234!", full_name="Asha"):
    """Returns 201 if created, 409 if the email already exists (mirrors the old API for existing assertions)."""
    from types import SimpleNamespace
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    if db.query(models.User).filter(models.User.email.ilike(email)).first():
        return SimpleNamespace(status_code=409)
    user = models.User(email=email, hashed_password=hash_password(password), role="admin")
    db.add(user)
    db.flush()
    db.add(models.Administrator(user_id=user.id, full_name=full_name, phone="99999",
                                designation="Program Director", is_active=True))
    db.commit()
    return SimpleNamespace(status_code=201)
