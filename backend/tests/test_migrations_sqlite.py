"""Runs the four most recent (additive) migrations against a SQLite database that already holds data.

Uses the real SQLAlchemy and Alembic when they are installed; otherwise a small DDL shim (tests/_migration_shim.py) that
executes the same migration files on a real SQLite connection. Either way the migration code runs, and the result is compared
with the columns defined in app/models.py. PostgreSQL itself is NOT exercised: run `alembic upgrade head` on a copy of your
database for that.

Run with:  python -m pytest tests/test_migrations_sqlite.py -q
"""
import ast
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"
CHAIN = ["20261024_locations", "20261025_otp", "20261026_deliveries", "20261027_tracking", "20261028_availability", "20261029_email_verification", "20261105_phone_verification", "20261106_tracking_sessions", "20261107_push_notifications", "20261108_jobs_storage_payments"]
NEW_TABLES = {"otp_challenges": "OtpChallenge", "delivery_tasks": "DeliveryTask", "delivery_events": "DeliveryEvent", "delivery_locations": "DeliveryLocation",
              "tracking_sessions": "TrackingSession", "location_history": "LocationHistory",
              "push_subscriptions": "PushSubscription", "notification_events": "NotificationEvent",
              "background_jobs": "BackgroundJob", "stored_documents": "StoredDocument", "payment_transactions": "PaymentTransaction", "payment_events": "PaymentEvent"}

try:
    import sqlalchemy  # noqa: F401
    import alembic.operations  # noqa: F401
    REAL = True
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    import _migration_shim as shim
    shim.install()                    # `import sqlalchemy as sa` and `from alembic import op` now resolve to the shim
    REAL = False


# ------------------------------------------------------------------ helpers
def model_columns(cls_name: str) -> dict[str, bool]:
    """{column: nullable} for a model class, read from app/models.py."""
    for node in ast.parse((ROOT / "app" / "models.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            out = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and getattr(stmt.value.func, "id", "") == "Column":
                    kw = {k.arg: getattr(k.value, "value", None) for k in stmt.value.keywords}
                    out[stmt.targets[0].id] = bool(kw.get("nullable", True)) and not kw.get("primary_key", False)
            return out
    raise AssertionError(f"model {cls_name} not found")


def load(revision: str):
    spec = importlib.util.spec_from_file_location(f"mig_{revision}", next(VERSIONS.glob(f"{revision}*.py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Db:
    """A SQLite database with the parent tables the migrations point at, and some existing rows."""
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self._seed()

    def _seed(self):
        self.conn.execute("PRAGMA foreign_keys=ON")
        for t in ("users", "needs", "organizations", "matches"):
            self.conn.execute(f'CREATE TABLE {t} (id INTEGER PRIMARY KEY, name TEXT)')
        self.conn.execute("CREATE TABLE donors (id INTEGER PRIMARY KEY, name TEXT, location TEXT)")
        self.conn.execute("CREATE TABLE volunteers (id INTEGER PRIMARY KEY, name TEXT, skills TEXT)")
        self.conn.execute("INSERT INTO users VALUES (1, 'u')"); self.conn.execute("INSERT INTO needs VALUES (1, 'need')"); self.conn.execute("INSERT INTO organizations VALUES (1, 'org')")
        self.conn.execute("INSERT INTO donors VALUES (1, 'Dana', 'Banjara Hills'), (2, 'Ravi', NULL)")
        self.conn.execute("INSERT INTO volunteers VALUES (1, 'Vik', 'driving')")

    def run(self, revision: str, direction: str):
        module = load(revision)
        shim.op.conn = self.conn
        getattr(module, direction)()

    def tables(self): return {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def columns(self, table):      # {column: nullable}. SQLite reports a PRIMARY KEY as nullable, but it never is.
        return {r[1]: not (r[3] or r[5]) for r in self.conn.execute(f'PRAGMA table_info("{table}")')}


class RealDb(Db):
    """Same database, but the migrations run through the real Alembic Operations on a SQLAlchemy connection (used when
    SQLAlchemy and Alembic are installed). Not executed in the sandbox this file was written in: run it on your machine."""
    def __init__(self):
        import sqlalchemy as sa
        self.engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool)
        self.conn = self.engine.raw_connection().driver_connection          # the same SQLite connection SQLAlchemy uses
        self.conn.isolation_level = None
        self._seed()

    def run(self, revision: str, direction: str):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        module = load(revision)
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(module, direction)()


def new_db():
    return RealDb() if REAL else Db()


def upgrade_all(db):
    for rev in CHAIN:
        db.run(rev, "upgrade")


# ------------------------------------------------------------------ tests
def test_the_chain_is_linear_and_follows_the_previous_head():
    expected_down = ["20261023_llm"] + CHAIN[:-1]
    for rev, down in zip(CHAIN, expected_down):
        src = next(VERSIONS.glob(f"{rev}*.py")).read_text(encoding="utf-8")
        assert f'down_revision: Union[str, Sequence[str], None] = "{down}"' in src, (rev, down)
        assert len(rev) <= 32                                        # alembic_version.version_num is VARCHAR(32)


def test_upgrade_creates_exactly_the_tables_and_columns_the_models_define():
    db = new_db(); upgrade_all(db)
    for table, cls in NEW_TABLES.items():
        assert table in db.tables(), table
        assert db.columns(table) == {c: nullable for c, nullable in model_columns(cls).items()}, f"{table} differs from model {cls}"
    donors, volunteers = db.columns("donors"), db.columns("volunteers")
    for col in ("latitude", "longitude", "location_updated_at"):
        assert col in donors and donors[col] is True and col in volunteers and volunteers[col] is True
    assert "service_radius_km" in volunteers and "service_radius_km" not in donors
    users = db.columns("users")
    for col in ("email_verification_pending", "email_verified_at"):
        assert users[col] is True and col in model_columns("User"), col                 # nullable: nobody is locked out by the migration
    for col in ("phone_e164", "phone_verification_pending", "phone_verified_at"):
        assert users[col] is True and col in model_columns("User"), col                 # nullable: existing accounts are never blocked
    for col in ("availability_timezone", "transport_mode", "carry_capacity_kg"):
        assert volunteers[col] is True and col in model_columns("Volunteer"), col
    for col in ("latitude", "longitude", "location_updated_at"):
        assert col in model_columns("Donor") and col in model_columns("Volunteer")


def test_existing_rows_survive_and_new_columns_start_empty():
    db = new_db(); upgrade_all(db)
    assert db.conn.execute("SELECT id, name, location FROM donors ORDER BY id").fetchall() == [(1, "Dana", "Banjara Hills"), (2, "Ravi", None)]
    assert db.conn.execute("SELECT id, name, skills FROM volunteers").fetchall() == [(1, "Vik", "driving")]
    assert db.conn.execute("SELECT latitude, longitude, location_updated_at FROM donors WHERE id = 1").fetchone() == (None, None, None)
    assert db.conn.execute("SELECT service_radius_km FROM volunteers").fetchone() == (None,)


def test_existing_users_are_untouched_and_not_pending_after_the_verification_migration():
    db = new_db(); upgrade_all(db)
    assert db.conn.execute("SELECT id, name, email_verification_pending, email_verified_at FROM users").fetchall() == [(1, "u", None, None)]


def test_running_the_upgrade_twice_is_harmless():
    db = new_db(); upgrade_all(db)
    before = {t: db.columns(t) for t in db.tables()}
    upgrade_all(db)
    assert {t: db.columns(t) for t in db.tables()} == before
    assert db.conn.execute("SELECT COUNT(*) FROM donors").fetchone() == (2,)


def test_a_column_added_by_hand_does_not_break_the_upgrade():
    db = new_db(); db.conn.execute("ALTER TABLE donors ADD COLUMN latitude REAL"); db.conn.execute("UPDATE donors SET latitude = 17.5 WHERE id = 1")
    upgrade_all(db)
    assert db.conn.execute("SELECT latitude FROM donors WHERE id = 1").fetchone() == (17.5,)           # their data is left alone


def test_database_constraints_actually_fire():
    db = new_db(); upgrade_all(db); c = db.conn
    c.execute("INSERT INTO donors (id, name) VALUES (9, 'Z')")
    ok = "INSERT INTO delivery_tasks (need_id, org_id, donor_id, quantity, status) VALUES (1, 1, 1, ?, 'proposed')"
    c.execute(ok, (5,))
    for bad, why in [((0,), "quantity 0 violates the CHECK"), ((-3,), "negative quantity violates the CHECK")]:
        try:
            c.execute(ok, bad); raise AssertionError(why)
        except sqlite3.IntegrityError:
            pass
    try:
        c.execute("INSERT INTO delivery_tasks (need_id, org_id, donor_id, quantity) VALUES (999, 1, 1, 5)"); raise AssertionError("dangling need accepted")
    except sqlite3.IntegrityError:
        pass
    c.execute("INSERT INTO volunteers (id, name) VALUES (5, 'V5')")
    c.execute("INSERT INTO delivery_locations (task_id, volunteer_id, consented_at) VALUES (1, 5, CURRENT_TIMESTAMP)")
    try:
        c.execute("INSERT INTO delivery_locations (task_id, volunteer_id, consented_at) VALUES (1, 5, CURRENT_TIMESTAMP)"); raise AssertionError("two position rows for one delivery")
    except sqlite3.IntegrityError:
        pass
    try:
        c.execute("INSERT INTO delivery_events (task_id, action, to_status) VALUES (777, 'x', 'y')"); raise AssertionError("event for a missing delivery")
    except sqlite3.IntegrityError:
        pass


def test_otp_codes_can_be_stored_only_as_hashes_with_all_required_fields():
    db = new_db(); upgrade_all(db); c = db.conn
    try:
        c.execute("INSERT INTO otp_challenges (user_id, purpose) VALUES (1, 'password_reset')"); raise AssertionError("missing hash/salt accepted")
    except sqlite3.IntegrityError:
        pass
    c.execute("INSERT INTO otp_challenges (user_id, code_hash, salt, expires_at, sent_at) VALUES (1, 'h', 's', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
    assert c.execute("SELECT purpose, attempts FROM otp_challenges").fetchone() == ("password_reset", 0)       # server defaults apply


def test_downgrade_removes_only_what_the_upgrade_added_and_keeps_the_data():
    db = new_db(); original = {t: db.columns(t) for t in db.tables()}
    upgrade_all(db)
    for rev in reversed(CHAIN):
        db.run(rev, "downgrade")
    assert {t: db.columns(t) for t in db.tables()} == original
    assert db.conn.execute("SELECT id, name, location FROM donors ORDER BY id").fetchall() == [(1, "Dana", "Banjara Hills"), (2, "Ravi", None)]
    upgrade_all(db)                                                                                           # and it can go up again
    assert "delivery_locations" in db.tables()


def test_additive_migrations_never_add_a_required_column_to_an_existing_table():
    """A NOT NULL column without a default would fail on a table that already has rows. The shim refuses it; this checks the source too."""
    for rev in CHAIN:
        src = next(VERSIONS.glob(f"{rev}*.py")).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_column":
                column = node.args[1]
                nullable = [k.value.value for k in column.keywords if k.arg == "nullable"]
                assert nullable == [True], f"{rev}: add_column must be nullable=True"


def test_a_resent_trail_point_is_rejected_by_the_database_itself():
    """Duplicate protection must not depend on application code: (session_id, seq) is UNIQUE in the schema."""
    db = new_db(); upgrade_all(db)
    db.conn.execute("PRAGMA foreign_keys = OFF")                     # isolate the UNIQUE constraint from the parent-row chain
    row = ("INSERT INTO location_history (session_id, task_id, seq, latitude, longitude, recorded_at, flagged) "
           "VALUES (1, 1, ?, 17.4, 78.4, '2026-11-05 10:00:00', 0)")
    db.conn.execute(row, (0,))
    db.conn.execute(row, (1,))                                       # a different sequence number is fine
    try:
        db.conn.execute(row, (1,))
    except sqlite3.IntegrityError:
        return
    raise AssertionError("a duplicate (session_id, seq) was accepted")
