"""deploy/backup/*.sh against STUB pg_dump / pg_restore / createdb / psql / dropdb (PostgreSQL itself is not available here).
These prove the SAFETY LOGIC of the scripts. They do not prove a real restore works: rehearse that on real infrastructure (DEPLOYMENT_GUIDE.md)."""
import os
import pathlib
import stat
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "backup"

STUBS = {
    "pg_dump": '''#!/bin/bash
echo "pg_dump $*" >> "$STUB_LOG"
[ "${STUB_DUMP_FAIL:-}" = "1" ] && { echo "pg_dump: connection refused" >&2; exit 1; }
for a in "$@"; do case "$a" in --file=*) f="${a#--file=}";; esac; done
printf '%s' "${STUB_DUMP_CONTENT-PGDMP-fake-archive}" > "$f"
''',
    "pg_restore": '''#!/bin/bash
echo "pg_restore $*" >> "$STUB_LOG"
if [ "$1" = "--list" ]; then [ "${STUB_LIST_FAIL:-}" = "1" ] && exit 1; echo "; archive listing"; exit 0; fi
[ "${STUB_RESTORE_FAIL:-}" = "1" ] && { echo "pg_restore: error" >&2; exit 1; }
exit 0
''',
    "createdb": '#!/bin/bash\necho "createdb $*" >> "$STUB_LOG"\n',
    "dropdb": '#!/bin/bash\necho "dropdb $*" >> "$STUB_LOG"\n',
    "psql": '''#!/bin/bash
echo "psql $*" >> "$STUB_LOG"
case "$*" in *alembic_version*) echo "20261108_jobs_storage_payments";; *"count(*) FROM users"*) echo "${STUB_USERS-42}";; esac
''',
}


@pytest.fixture
def box(tmp_path):
    bin_dir, backups = tmp_path / "bin", tmp_path / "backups"
    bin_dir.mkdir(); backups.mkdir()
    for name, body in STUBS.items():
        p = bin_dir / name; p.write_text(body); p.chmod(p.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"; log.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_LOG": str(log), "BACKUP_DIR": str(backups), "PGDATABASE": "carebridge"}
    for k in ("STUB_DUMP_FAIL", "STUB_DUMP_CONTENT", "STUB_LIST_FAIL", "STUB_RESTORE_FAIL", "STUB_USERS", "I_UNDERSTAND_THIS_REPLACES_DATA", "BACKUP_RETENTION_DAYS"):
        env.pop(k, None)

    class Box:
        pass
    b = Box(); b.env, b.dir, b.log = env, backups, log
    b.run = lambda script, *args, **extra: subprocess.run(["bash", str(SCRIPTS / script), *args], env={**env, **extra}, capture_output=True, text=True, timeout=30)
    b.calls = lambda: [l for l in log.read_text().splitlines() if l]
    return b


def age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def dumps(box):
    return sorted(p.name for p in box.dir.glob("carebridge-*.dump"))


# ---------------------------------------------------------------- backup.sh
def test_a_good_backup_is_kept_checksummed_private_and_leaves_no_partial_file(box):
    r = box.run("backup.sh")
    assert r.returncode == 0 and r.stdout.startswith("OK carebridge-")
    (name,) = dumps(box)
    assert subprocess.run(["sha256sum", "--check", "--status", f"{name}.sha256"], cwd=box.dir).returncode == 0
    assert not list(box.dir.glob(".*partial")) and stat.S_IMODE((box.dir / name).stat().st_mode) == 0o600
    assert any("--format=custom" in c and "--no-owner" in c for c in box.calls())


@pytest.mark.parametrize("failure", [{"STUB_DUMP_CONTENT": ""}, {"STUB_LIST_FAIL": "1"}, {"STUB_DUMP_FAIL": "1"}])
def test_a_failed_empty_or_unreadable_backup_keeps_everything_that_was_already_there(box, failure):
    old = box.dir / "carebridge-20200101T000000Z.dump"; old.write_text("old good backup"); age(old, 400)       # older than any retention
    r = box.run("backup.sh", **failure)
    assert r.returncode != 0
    assert dumps(box) == [old.name] and old.read_text() == "old good backup"                                      # NOT pruned by a failed run
    assert not list(box.dir.glob(".*partial"))


def test_old_backups_are_pruned_only_after_a_new_good_one_exists(box):
    old, old_sum = box.dir / "carebridge-20200101T000000Z.dump", box.dir / "carebridge-20200101T000000Z.dump.sha256"
    recent, other = box.dir / "carebridge-20261101T000000Z.dump", box.dir / "notes.txt"
    for p in (old, old_sum, recent, other):
        p.write_text("x")
    age(old, 20); age(old_sum, 20); age(other, 400)
    r = box.run("backup.sh", BACKUP_RETENTION_DAYS="14")
    assert r.returncode == 0
    names = dumps(box)
    assert old.name not in names and recent.name in names and len(names) == 2 and not old_sum.exists()
    assert other.exists()                                                                                          # files that are not ours are never touched


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", "7; rm -rf /"])
def test_a_bad_retention_setting_is_refused_and_deletes_nothing(box, bad):
    old = box.dir / "carebridge-20200101T000000Z.dump"; old.write_text("x"); age(old, 400)
    r = box.run("backup.sh", BACKUP_RETENTION_DAYS=bad)
    assert r.returncode == 2 and old.exists() and not any(c.startswith("pg_dump") for c in box.calls())


# ---------------------------------------------------------------- restore.sh
def make_dump(box, name="carebridge-20261109T210000Z.dump", with_sum=True):
    d = box.dir / name; d.write_text("PGDMP-fake")
    if with_sum:
        subprocess.run(f"sha256sum {name} > {name}.sha256", shell=True, cwd=box.dir, check=True)
    return d


def test_restore_needs_an_existing_file(box):
    assert box.run("restore.sh").returncode == 2 and box.run("restore.sh", str(box.dir / "missing.dump")).returncode == 2


def test_restore_goes_to_a_new_database_by_default_never_the_live_one(box):
    d = make_dump(box)
    r = box.run("restore.sh", str(d))
    assert r.returncode == 0 and "checksum OK" in r.stdout
    calls = box.calls()
    created = [c for c in calls if c.startswith("createdb")][0].split()[-1]
    assert created.startswith("carebridge_restore_") and created != "carebridge"
    assert any(c.startswith("pg_restore") and f"--dbname={created}" in c and "--clean" not in c for c in calls)


def test_restoring_over_the_live_database_is_refused_without_explicit_confirmation(box):
    d = make_dump(box)
    r = box.run("restore.sh", str(d), "carebridge")
    assert r.returncode == 3 and "REFUSING" in r.stderr
    assert not any(c.startswith(("pg_restore --no", "pg_restore --clean", "createdb")) for c in box.calls())


def test_restoring_over_the_live_database_works_only_with_the_confirmation_and_cleans_first(box):
    d = make_dump(box)
    r = box.run("restore.sh", str(d), "carebridge", I_UNDERSTAND_THIS_REPLACES_DATA="yes")
    assert r.returncode == 0
    calls = box.calls()
    assert any(c.startswith("pg_restore") and "--clean" in c and "--dbname=carebridge" in c for c in calls) and not any(c.startswith("createdb") for c in calls)
    assert box.run("restore.sh", str(d), "carebridge", I_UNDERSTAND_THIS_REPLACES_DATA="YES").returncode == 3          # exact word only


@pytest.mark.parametrize("name", ["db; DROP DATABASE carebridge", "a b", "x$(id)", "../x", "a-b", "`id`", "db\nname"])
def test_a_database_name_cannot_carry_shell_or_sql(box, name):
    d = make_dump(box)
    r = box.run("restore.sh", str(d), name)
    assert r.returncode == 2 and not any(c.startswith(("createdb", "pg_restore --no", "pg_restore --clean")) for c in box.calls())


def test_a_damaged_backup_is_not_restored(box):
    d = make_dump(box); d.write_text("tampered contents")
    r = box.run("restore.sh", str(d))
    assert r.returncode == 4 and "checksum mismatch" in r.stderr and not any(c.startswith("createdb") for c in box.calls())


def test_a_missing_checksum_file_is_a_warning_not_a_silent_pass(box):
    d = make_dump(box, with_sum=False)
    r = box.run("restore.sh", str(d))
    assert r.returncode == 0 and "unchecked" in r.stderr


def test_a_failed_restore_reports_failure(box):
    d = make_dump(box)
    assert box.run("restore.sh", str(d), STUB_RESTORE_FAIL="1").returncode != 0


# ---------------------------------------------------------------- verify_restore.sh
def test_verification_restores_into_a_throwaway_database_checks_it_and_drops_it(box):
    d = make_dump(box)
    r = box.run("verify_restore.sh", str(d))
    assert r.returncode == 0 and "VERIFY OK" in r.stdout and "users=42" in r.stdout and "20261108_jobs_storage_payments" in r.stdout
    calls = box.calls()
    temp = [c for c in calls if c.startswith("createdb")][0].split()[-1]
    assert temp.startswith("carebridge_verify_") and any(c == f"dropdb --if-exists {temp}" for c in calls)
    assert not any("--dbname=carebridge " in c + " " for c in calls)                                              # never touched the live database


def test_verification_drops_its_temporary_database_even_when_the_restore_fails(box):
    d = make_dump(box)
    r = box.run("verify_restore.sh", str(d), STUB_RESTORE_FAIL="1")
    assert r.returncode != 0 and any(c.startswith("dropdb --if-exists carebridge_verify_") for c in box.calls())


def test_verification_fails_loudly_when_the_restored_database_is_empty(box):
    d = make_dump(box)
    r = box.run("verify_restore.sh", str(d), STUB_USERS="")
    assert r.returncode == 1 and "VERIFY FAILED" in r.stderr


def test_verification_defaults_to_the_newest_backup_and_needs_one_to_exist(box):
    assert box.run("verify_restore.sh").returncode == 2
    old = make_dump(box, "carebridge-20260101T000000Z.dump"); age(old, 30)
    new = make_dump(box, "carebridge-20261109T210000Z.dump")
    box.run("verify_restore.sh")
    assert any("carebridge-20261109T210000Z.dump" in c for c in box.calls() if c.startswith("pg_restore --no"))


# ---------------------------------------------------------------- backup_loop.sh
def spawn(box, seconds=2.5, **extra):
    """Run the loop in its OWN process group and kill the whole group, so its long `sleep` child cannot outlive the test or hold a pipe open."""
    import signal
    p = subprocess.Popen(["bash", str(SCRIPTS / "backup_loop.sh")], env={**box.env, "BACKUP_HOUR_UTC": "21", **extra}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
    time.sleep(seconds)
    alive = p.poll() is None
    os.killpg(p.pid, signal.SIGKILL)
    try:
        err = p.stderr.read()
    finally:
        p.stderr.close(); p.wait(timeout=10)
    return alive, err


def test_the_loop_takes_a_backup_at_start_when_none_exists(box):
    spawn(box)
    assert len(dumps(box)) == 1


def test_the_loop_does_not_back_up_again_at_start_when_a_recent_one_exists(box):
    make_dump(box, "carebridge-20261109T000000Z.dump")
    spawn(box)
    assert dumps(box) == ["carebridge-20261109T000000Z.dump"]


def test_the_loop_survives_a_failing_backup_and_keeps_running(box):
    alive, err = spawn(box, STUB_DUMP_FAIL="1")
    assert alive and "backup FAILED" in err and dumps(box) == []
